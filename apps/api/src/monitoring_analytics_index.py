from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import db
from models import Base, BiasTileSet, HistoricalStatisticArtifact


def _parse_iso_datetime(value: str) -> datetime:
    raw = (value or "").strip()
    if raw == "":
        raise ValueError("datetime must not be empty")
    candidate = raw
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    dt = datetime.fromisoformat(candidate)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iter_statistics_metadata_files(statistics_root: Path) -> Iterable[Path]:
    if not statistics_root.is_dir():
        return []
    return statistics_root.rglob("statistics.nc.meta.json")


def _load_json(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"metadata json must be an object: {path}")
    return data


def _upsert_historical_statistics(
    session: Session, *, statistics_root: Path, metadata_path: Path
) -> bool:
    meta = _load_json(metadata_path)
    source = str(meta.get("output_source") or meta.get("source_kind") or "").strip()
    variable = str(meta.get("variable") or "").strip()
    window_kind = str(meta.get("window_kind") or "").strip()
    window_key = str(meta.get("window_key") or "").strip()
    version = str(meta.get("version") or "").strip()

    if not all((source, variable, window_kind, window_key, version)):
        raise ValueError(f"missing required metadata fields: {metadata_path}")

    window_start = _parse_iso_datetime(str(meta.get("window_start") or ""))
    window_end = _parse_iso_datetime(str(meta.get("window_end") or ""))
    samples = int(meta.get("samples") or 0)

    dataset_path = metadata_path.name.replace(".meta.json", "")
    dataset_rel = (
        metadata_path.with_name(dataset_path)
        .resolve()
        .relative_to(statistics_root.resolve())
        .as_posix()
    )
    metadata_rel = (
        metadata_path.resolve().relative_to(statistics_root.resolve()).as_posix()
    )

    extra = dict(meta)

    stmt = select(HistoricalStatisticArtifact).where(
        HistoricalStatisticArtifact.source == source,
        HistoricalStatisticArtifact.variable == variable,
        HistoricalStatisticArtifact.window_kind == window_kind,
        HistoricalStatisticArtifact.window_key == window_key,
        HistoricalStatisticArtifact.version == version,
    )
    existing = session.execute(stmt).scalar_one_or_none()
    if existing is None:
        session.add(
            HistoricalStatisticArtifact(
                source=source,
                variable=variable,
                window_kind=window_kind,
                window_key=window_key,
                version=version,
                window_start=window_start,
                window_end=window_end,
                samples=samples,
                dataset_path=dataset_rel,
                metadata_path=metadata_rel,
                extra=extra,
            )
        )
        return True

    existing.window_start = window_start
    existing.window_end = window_end
    existing.samples = samples
    existing.dataset_path = dataset_rel
    existing.metadata_path = metadata_rel
    existing.extra = extra
    return False


def index_historical_statistics(
    session: Session, *, statistics_root: Path
) -> tuple[int, int]:
    created = 0
    updated = 0

    for meta_path in _iter_statistics_metadata_files(statistics_root):
        was_created = _upsert_historical_statistics(
            session, statistics_root=statistics_root, metadata_path=meta_path
        )
        if was_created:
            created += 1
        else:
            updated += 1

    return created, updated


def _detect_formats(level_dir: Path) -> list[str]:
    formats: list[str] = []
    for ext in ("png", "webp"):
        found = next(level_dir.rglob(f"*.{ext}"), None)
        if found is not None and ext not in formats:
            formats.append(ext)
    return formats


def _detect_zoom_range(level_dir: Path) -> tuple[int, int] | None:
    zooms: list[int] = []
    for child in level_dir.iterdir():
        if not child.is_dir():
            continue
        if not child.name.isdigit():
            continue
        zooms.append(int(child.name))
    if not zooms:
        return None
    return min(zooms), max(zooms)


def index_bias_tiles(session: Session, *, tiles_root: Path) -> tuple[int, int]:
    bias_root = tiles_root / "bias"
    if not bias_root.is_dir():
        return 0, 0

    created = 0
    updated = 0

    for element_dir in sorted(bias_root.iterdir()):
        if not element_dir.is_dir():
            continue
        layer = f"bias/{element_dir.name}"
        for time_dir in sorted(element_dir.iterdir()):
            if not time_dir.is_dir():
                continue
            time_key = time_dir.name
            for level_dir in sorted(time_dir.iterdir()):
                if not level_dir.is_dir():
                    continue
                level_key = level_dir.name

                zoom_range = _detect_zoom_range(level_dir)
                if zoom_range is None:
                    continue
                min_zoom, max_zoom = zoom_range
                formats = _detect_formats(level_dir)
                if not formats:
                    continue

                stmt = select(BiasTileSet).where(
                    BiasTileSet.layer == layer,
                    BiasTileSet.time_key == time_key,
                    BiasTileSet.level_key == level_key,
                )
                existing = session.execute(stmt).scalar_one_or_none()
                if existing is None:
                    session.add(
                        BiasTileSet(
                            layer=layer,
                            time_key=time_key,
                            level_key=level_key,
                            min_zoom=min_zoom,
                            max_zoom=max_zoom,
                            formats=formats,
                        )
                    )
                    created += 1
                else:
                    existing.min_zoom = min_zoom
                    existing.max_zoom = max_zoom
                    existing.formats = formats
                    updated += 1

    return created, updated


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Index statistics artifacts and bias tiles into the API database."
    )
    parser.add_argument(
        "--statistics-root",
        default=None,
        help="Root directory for statistics outputs (default: Data/statistics)",
    )
    parser.add_argument(
        "--tiles-root",
        default=None,
        help="Root directory for tiles outputs (default: Data/tiles)",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Optional SQLAlchemy DATABASE_URL override (otherwise uses app config)",
    )
    parser.add_argument(
        "--only",
        choices=("all", "statistics", "bias"),
        default="all",
        help="Index only a subset (default: all)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)

    repo_root = Path(__file__).resolve().parents[3]
    statistics_root = (
        (repo_root / "Data" / "statistics")
        if args.statistics_root is None
        else Path(args.statistics_root)
    ).resolve()
    tiles_root = (
        (repo_root / "Data" / "tiles")
        if args.tiles_root is None
        else Path(args.tiles_root)
    ).resolve()

    engine = create_engine(args.database_url) if args.database_url else db.get_engine()
    Base.metadata.create_all(engine)

    try:
        with Session(engine) as session:
            created_stats = updated_stats = 0
            created_bias = updated_bias = 0

            if args.only in {"all", "statistics"}:
                created_stats, updated_stats = index_historical_statistics(
                    session, statistics_root=statistics_root
                )

            if args.only in {"all", "bias"}:
                created_bias, updated_bias = index_bias_tiles(
                    session, tiles_root=tiles_root
                )

            session.commit()

        print(
            json.dumps(
                {
                    "historical_statistics": {
                        "created": created_stats,
                        "updated": updated_stats,
                    },
                    "bias_tile_sets": {
                        "created": created_bias,
                        "updated": updated_bias,
                    },
                },
                ensure_ascii=False,
            )
        )
        return 0
    except SQLAlchemyError as exc:
        raise SystemExit(f"Database error: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
