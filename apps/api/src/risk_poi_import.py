from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from sqlalchemy import Engine, select, tuple_
from sqlalchemy.orm import Session

import db
from models import RiskPOI


InputFormat = Literal["csv", "geojson"]
DuplicateReason = Literal["duplicate_in_file", "duplicate_in_db"]


@dataclass(frozen=True)
class RiskPOIKey:
    name: str
    poi_type: str
    lon: float
    lat: float


@dataclass(frozen=True)
class RiskPOIRecord:
    name: str
    poi_type: str
    lon: float
    lat: float
    alt: float | None
    weight: float
    tags: list[str] | None

    @property
    def key(self) -> RiskPOIKey:
        return RiskPOIKey(
            name=self.name,
            poi_type=self.poi_type,
            lon=self.lon,
            lat=self.lat,
        )


@dataclass(frozen=True)
class ImportErrorRow:
    row: int
    message: str
    raw: Any | None = None


@dataclass(frozen=True)
class ImportDuplicateRow:
    row: int
    reason: DuplicateReason
    key: RiskPOIKey


@dataclass
class RiskPOIImportReport:
    source: str
    format: InputFormat
    total_rows: int = 0
    inserted_rows: int = 0
    error_rows: list[ImportErrorRow] = field(default_factory=list)
    duplicate_rows: list[ImportDuplicateRow] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len(self.error_rows)

    @property
    def duplicate_count(self) -> int:
        return len(self.duplicate_rows)

    @property
    def valid_unique_rows(self) -> int:
        return self.total_rows - self.error_count - self.duplicate_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "format": self.format,
            "summary": {
                "total_rows": self.total_rows,
                "inserted_rows": self.inserted_rows,
                "error_rows": self.error_count,
                "duplicate_rows": self.duplicate_count,
            },
            "errors": [
                {"row": err.row, "message": err.message, "raw": err.raw}
                for err in self.error_rows
            ],
            "duplicates": [
                {"row": dup.row, "reason": dup.reason, "key": _key_to_dict(dup.key)}
                for dup in self.duplicate_rows
            ],
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


def import_risk_pois(
    *,
    engine: Engine,
    source: Path,
    input_format: InputFormat | None = None,
    dry_run: bool = False,
    strict: bool = False,
    dedupe_existing: bool = True,
    insert_batch_size: int = 1000,
    db_dedupe_chunk_size: int = 200,
) -> RiskPOIImportReport:
    resolved_format = _resolve_format(source, input_format)
    report = RiskPOIImportReport(source=str(source), format=resolved_format)

    candidates: list[tuple[int, RiskPOIRecord]] = []
    seen_keys: set[RiskPOIKey] = set()

    for row_number, raw in _iter_input_rows(source, resolved_format):
        report.total_rows += 1
        record = _parse_record(raw, row_number=row_number, report=report)
        if record is None:
            continue

        if record.key in seen_keys:
            report.duplicate_rows.append(
                ImportDuplicateRow(
                    row=row_number,
                    reason="duplicate_in_file",
                    key=record.key,
                )
            )
            continue

        seen_keys.add(record.key)
        candidates.append((row_number, record))

    existing_keys: set[RiskPOIKey] = set()
    if dedupe_existing and candidates:
        existing_keys = _fetch_existing_keys(
            engine,
            keys=[record.key for _, record in candidates],
            chunk_size=db_dedupe_chunk_size,
        )

    to_insert: list[RiskPOIRecord] = []
    for row_number, record in candidates:
        if record.key in existing_keys:
            report.duplicate_rows.append(
                ImportDuplicateRow(
                    row=row_number,
                    reason="duplicate_in_db",
                    key=record.key,
                )
            )
            continue
        to_insert.append(record)

    if strict and report.error_rows:
        return report

    if dry_run:
        report.inserted_rows = 0
        return report

    if not to_insert:
        report.inserted_rows = 0
        return report

    with Session(engine) as session:
        for chunk in _chunked(to_insert, insert_batch_size):
            session.add_all([_record_to_model(rec) for rec in chunk])
        session.commit()

    report.inserted_rows = len(to_insert)
    return report


def _resolve_format(source: Path, input_format: InputFormat | None) -> InputFormat:
    if input_format is not None:
        return input_format

    suffix = source.suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix in {".geojson", ".json"}:
        return "geojson"
    raise ValueError(f"Unable to infer input format from {source.name!r}")


def _iter_input_rows(
    source: Path, input_format: InputFormat
) -> Sequence[tuple[int, dict[str, Any]]]:
    if input_format == "csv":
        return list(_iter_csv_rows(source))
    return list(_iter_geojson_rows(source))


def _iter_csv_rows(source: Path) -> Sequence[tuple[int, dict[str, Any]]]:
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV missing header row")
        normalized_fieldnames = [field.strip().lower() for field in reader.fieldnames]
        if any(not field for field in normalized_fieldnames):
            raise ValueError("CSV contains empty header name")

        rows: list[tuple[int, dict[str, Any]]] = []
        for row_number, raw in enumerate(reader, start=2):
            normalized = {
                key.strip().lower(): (
                    value.strip() if isinstance(value, str) else value
                )
                for key, value in raw.items()
                if key is not None
            }
            rows.append((row_number, normalized))
        return rows


def _iter_geojson_rows(source: Path) -> Sequence[tuple[int, dict[str, Any]]]:
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("type") != "FeatureCollection":
        raise ValueError("GeoJSON must be a FeatureCollection")

    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("GeoJSON FeatureCollection missing features list")

    rows: list[tuple[int, dict[str, Any]]] = []
    for idx, feature in enumerate(features, start=1):
        if not isinstance(feature, dict):
            raise ValueError("GeoJSON feature must be an object")
        rows.append((idx, feature))
    return rows


def _parse_record(
    raw: Mapping[str, Any], *, row_number: int, report: RiskPOIImportReport
) -> RiskPOIRecord | None:
    if report.format == "csv":
        return _parse_record_from_mapping(raw, row_number=row_number, report=report)
    return _parse_record_from_geojson(raw, row_number=row_number, report=report)


def _parse_record_from_mapping(
    raw: Mapping[str, Any], *, row_number: int, report: RiskPOIImportReport
) -> RiskPOIRecord | None:
    errors_before = len(report.error_rows)

    name = str(raw.get("name") or "").strip()
    poi_type = str(_get_first(raw, ["type", "poi_type", "poitype"]) or "").strip()
    lon_raw = _get_first(raw, ["lon", "lng", "longitude"])
    lat_raw = _get_first(raw, ["lat", "latitude"])

    missing_fields = [
        field
        for field, value in [
            ("name", name),
            ("type", poi_type),
            ("lon", lon_raw),
            ("lat", lat_raw),
        ]
        if value in {None, ""}
    ]
    if missing_fields:
        report.error_rows.append(
            ImportErrorRow(
                row=row_number,
                message=f"Missing required field(s): {', '.join(missing_fields)}",
                raw=dict(raw),
            )
        )
        return None

    lon = _parse_float(lon_raw, field="lon", row_number=row_number, report=report)
    lat = _parse_float(lat_raw, field="lat", row_number=row_number, report=report)
    if lon is None or lat is None:
        return None

    if not _validate_lon_lat(lon, lat, row_number=row_number, report=report):
        return None

    alt_value = _parse_optional_float(
        _get_first(raw, ["alt", "altitude", "elevation"]),
        field="alt",
        row_number=row_number,
        report=report,
    )
    weight_errors_before = len(report.error_rows)
    weight = _parse_optional_float(
        raw.get("weight"), field="weight", row_number=row_number, report=report
    )
    if weight is None and len(report.error_rows) == weight_errors_before:
        weight = 1.0

    tags = _parse_tags(raw.get("tags"), row_number=row_number, report=report)
    if len(report.error_rows) != errors_before:
        return None

    return RiskPOIRecord(
        name=name,
        poi_type=poi_type,
        lon=lon,
        lat=lat,
        alt=alt_value,
        weight=weight,
        tags=tags,
    )


def _parse_record_from_geojson(
    raw: Mapping[str, Any], *, row_number: int, report: RiskPOIImportReport
) -> RiskPOIRecord | None:
    errors_before = len(report.error_rows)

    geometry = raw.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        report.error_rows.append(
            ImportErrorRow(
                row=row_number,
                message="GeoJSON feature geometry must be a Point",
                raw=_safe_raw(raw),
            )
        )
        return None

    coords = geometry.get("coordinates")
    if not isinstance(coords, list) or len(coords) < 2:
        report.error_rows.append(
            ImportErrorRow(
                row=row_number,
                message="GeoJSON Point coordinates must be [lon, lat] (alt optional)",
                raw=_safe_raw(raw),
            )
        )
        return None

    lon = _parse_float(coords[0], field="lon", row_number=row_number, report=report)
    lat = _parse_float(coords[1], field="lat", row_number=row_number, report=report)
    if lon is None or lat is None:
        return None

    if not _validate_lon_lat(lon, lat, row_number=row_number, report=report):
        return None

    alt_value = None
    if len(coords) >= 3:
        alt_value = _parse_optional_float(
            coords[2], field="alt", row_number=row_number, report=report
        )

    properties = raw.get("properties")
    if properties is None:
        properties = {}
    if not isinstance(properties, dict):
        report.error_rows.append(
            ImportErrorRow(
                row=row_number,
                message="GeoJSON feature properties must be an object",
                raw=_safe_raw(raw),
            )
        )
        return None

    name = str(properties.get("name") or "").strip()
    poi_type = str(
        _get_first(properties, ["type", "poi_type", "poiType", "poitype"]) or ""
    ).strip()

    missing_fields = [
        field
        for field, value in [("name", name), ("type", poi_type)]
        if value in {None, ""}
    ]
    if missing_fields:
        report.error_rows.append(
            ImportErrorRow(
                row=row_number,
                message=f"Missing required field(s): {', '.join(missing_fields)}",
                raw=_safe_raw(raw),
            )
        )
        return None

    weight_errors_before = len(report.error_rows)
    weight = _parse_optional_float(
        properties.get("weight"), field="weight", row_number=row_number, report=report
    )
    if weight is None and len(report.error_rows) == weight_errors_before:
        weight = 1.0

    tags = _parse_tags(properties.get("tags"), row_number=row_number, report=report)
    if len(report.error_rows) != errors_before:
        return None

    return RiskPOIRecord(
        name=name,
        poi_type=poi_type,
        lon=lon,
        lat=lat,
        alt=alt_value,
        weight=weight,
        tags=tags,
    )


def _parse_float(
    value: Any, *, field: str, row_number: int, report: RiskPOIImportReport
) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        report.error_rows.append(
            ImportErrorRow(
                row=row_number,
                message=f"Invalid {field}: expected number, got {value!r}",
                raw=_safe_raw(value),
            )
        )
        return None

    if not math.isfinite(parsed):
        report.error_rows.append(
            ImportErrorRow(
                row=row_number,
                message=f"Invalid {field}: must be finite, got {value!r}",
                raw=_safe_raw(value),
            )
        )
        return None

    return parsed


def _parse_optional_float(
    value: Any, *, field: str, row_number: int, report: RiskPOIImportReport
) -> float | None:
    if value is None or value == "":
        return None
    return _parse_float(value, field=field, row_number=row_number, report=report)


def _validate_lon_lat(
    lon: float, lat: float, *, row_number: int, report: RiskPOIImportReport
) -> bool:
    if not (-180.0 <= lon <= 180.0):
        report.error_rows.append(
            ImportErrorRow(row=row_number, message=f"lon out of range: {lon}")
        )
        return False
    if not (-90.0 <= lat <= 90.0):
        report.error_rows.append(
            ImportErrorRow(row=row_number, message=f"lat out of range: {lat}")
        )
        return False
    return True


def _parse_tags(
    value: Any, *, row_number: int, report: RiskPOIImportReport
) -> list[str] | None:
    if value is None or value == "":
        return None

    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            normalized = [item.strip() for item in value if item.strip()]
            return normalized or None
        report.error_rows.append(
            ImportErrorRow(
                row=row_number,
                message="tags must be a list of strings",
                raw=_safe_raw(value),
            )
        )
        return None

    raw_text = str(value).strip()
    if not raw_text:
        return None

    if raw_text.startswith("["):
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            report.error_rows.append(
                ImportErrorRow(
                    row=row_number,
                    message="tags must be valid JSON when using JSON array syntax",
                    raw=_safe_raw(value),
                )
            )
            return None
        return _parse_tags(parsed, row_number=row_number, report=report)

    parts = [part.strip() for part in raw_text.replace(";", ",").split(",")]
    tags = [part for part in parts if part]
    return tags or None


def _fetch_existing_keys(
    engine: Engine, *, keys: Sequence[RiskPOIKey], chunk_size: int
) -> set[RiskPOIKey]:
    if not keys:
        return set()

    existing: set[RiskPOIKey] = set()
    with Session(engine) as session:
        for chunk in _chunked(keys, chunk_size):
            stmt = select(
                RiskPOI.name,
                RiskPOI.poi_type,
                RiskPOI.lon,
                RiskPOI.lat,
            ).where(
                tuple_(
                    RiskPOI.name,
                    RiskPOI.poi_type,
                    RiskPOI.lon,
                    RiskPOI.lat,
                ).in_(
                    [(item.name, item.poi_type, item.lon, item.lat) for item in chunk]
                )
            )
            for name, poi_type, lon, lat in session.execute(stmt).all():
                existing.add(RiskPOIKey(name=name, poi_type=poi_type, lon=lon, lat=lat))
    return existing


def _chunked(items: Sequence[Any], chunk_size: int) -> Sequence[Sequence[Any]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    return [items[idx : idx + chunk_size] for idx in range(0, len(items), chunk_size)]


def _record_to_model(record: RiskPOIRecord) -> RiskPOI:
    return RiskPOI(
        name=record.name,
        poi_type=record.poi_type,
        lon=record.lon,
        lat=record.lat,
        alt=record.alt,
        weight=record.weight,
        tags=record.tags,
    )


def _get_first(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _key_to_dict(key: RiskPOIKey) -> dict[str, Any]:
    return {"name": key.name, "type": key.poi_type, "lon": key.lon, "lat": key.lat}


def _safe_raw(value: Any) -> dict[str, Any] | Any:
    if isinstance(value, dict):
        return dict(value)
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="risk-poi-import",
        description="Import Risk POIs from CSV or GeoJSON into the risk_pois table.",
    )
    parser.add_argument("source", type=Path, help="CSV/GeoJSON file path")
    parser.add_argument(
        "--format",
        dest="input_format",
        choices=["csv", "geojson"],
        help="Input format (default: infer from extension)",
    )
    parser.add_argument(
        "--database-url",
        dest="database_url",
        help="Override database URL (defaults to DATABASE_URL / settings)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate only")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Abort without inserting if any row errors are found",
    )
    parser.add_argument(
        "--no-dedupe-existing",
        action="store_true",
        help="Do not check existing DB rows for duplicates",
    )
    parser.add_argument(
        "--insert-batch-size",
        type=int,
        default=1000,
        help="Batch size for DB inserts (default: 1000)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Write JSON report to file instead of stdout",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    engine = (
        db.get_engine()
        if not args.database_url
        else db.create_engine(args.database_url, pool_pre_ping=True)
    )

    report = import_risk_pois(
        engine=engine,
        source=args.source,
        input_format=args.input_format,
        dry_run=args.dry_run,
        strict=args.strict,
        dedupe_existing=not args.no_dedupe_existing,
        insert_batch_size=args.insert_batch_size,
    )

    payload = report.to_json(indent=2)
    if args.report:
        args.report.write_text(payload, encoding="utf-8")
    else:
        print(payload)

    if report.error_rows:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
