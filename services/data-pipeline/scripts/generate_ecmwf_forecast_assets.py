from __future__ import annotations

import argparse
import sys
import warnings
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Iterable, Optional


REPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_SRC = Path(__file__).resolve().parents[1] / "src"
CONFIG_SRC = REPO_ROOT / "packages" / "config" / "src"
SHARED_SRC = REPO_ROOT / "packages" / "shared" / "src"
API_SRC = REPO_ROOT / "apps" / "api" / "src"

for src in (PIPELINE_SRC, CONFIG_SRC, SHARED_SRC, API_SRC):
    sys.path.insert(0, str(src))

import numpy as np  # noqa: E402
import xarray as xr  # noqa: E402
from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import cfgrib  # noqa: E402

from datacube.storage import DataCubeWriteOptions, write_datacube  # noqa: E402
from data_source import LocalDataSource  # noqa: E402
from datacube.core import DataCube  # noqa: E402
from models import Base, EcmwfAsset, EcmwfRun, EcmwfTime  # noqa: E402
from tiling.precip_amount_tiles import PrecipAmountTileGenerator  # noqa: E402
from tiling.tcc_tiles import TccTileGenerator  # noqa: E402
from tiling.temperature_tiles import TemperatureTileGenerator  # noqa: E402


def _parse_time(value: str) -> datetime:
    raw = (value or "").strip()
    if raw == "":
        raise ValueError("time value must not be empty")

    candidate = raw
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        parsed = datetime.strptime(raw, "%Y%m%dT%H%M%SZ")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _time_key(dt: datetime) -> str:
    normalized = dt
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    normalized = normalized.astimezone(timezone.utc)
    return normalized.strftime("%Y%m%dT%H%M%SZ")


def _time_iso_z(dt: datetime) -> str:
    normalized = dt
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    value = normalized.astimezone(timezone.utc).isoformat()
    if value.endswith("+00:00"):
        return value[:-6] + "Z"
    return value


def _iter_valid_times(
    *, run_time: datetime, start_hour: int, end_hour: int, step_hour: int
) -> list[datetime]:
    if step_hour <= 0:
        raise ValueError("step_hour must be > 0")
    if end_hour < start_hour:
        raise ValueError("end_hour must be >= start_hour")

    # ECMWF standard output cadence: 0–72h every 3h, 72–240h every 6h.
    # Preserve backwards compatibility: only apply the mixed cadence when the caller
    # requests the default 3-hour step with an end beyond 72h.
    if int(step_hour) == 3 and int(end_hour) > 72:
        early = range(0, 72 + 1, 3)
        late = range(72, int(end_hour) + 1, 6)
        lead_hours = sorted(set(early).union(late))
        return [
            run_time + timedelta(hours=int(h))
            for h in lead_hours
            if int(start_hour) <= int(h) <= int(end_hour)
        ]

    return [
        run_time + timedelta(hours=int(h))
        for h in range(int(start_hour), int(end_hour) + 1, int(step_hour))
    ]


def _default_database_url(*, repo_root: Path) -> str:
    db_path = (repo_root / "Data" / "catalog.db").resolve()
    return f"sqlite+pysqlite:///{db_path}"


def _ensure_catalog_times(
    engine,
    *,
    run_time: datetime,
    valid_times: list[datetime],
    run_status: str = "complete",
) -> tuple[int, list[tuple[int, datetime]]]:
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        run = session.execute(
            select(EcmwfRun).where(EcmwfRun.run_time == run_time)
        ).scalar_one_or_none()
        if run is None:
            run = EcmwfRun(run_time=run_time, status=run_status)
            session.add(run)
            session.flush()
        else:
            run.status = run_status

        existing = {
            _time_iso_z(item.valid_time): item
            for item in session.execute(
                select(EcmwfTime).where(EcmwfTime.run_id == run.id)
            )
            .scalars()
            .all()
        }
        for dt in valid_times:
            if _time_iso_z(dt) not in existing:
                session.add(EcmwfTime(run_id=run.id, valid_time=dt))

        session.commit()

        ordered = (
            session.execute(
                select(EcmwfTime)
                .where(
                    EcmwfTime.run_id == run.id,
                    EcmwfTime.valid_time.in_(valid_times),
                )
                .order_by(EcmwfTime.valid_time.asc())
            )
            .scalars()
            .all()
        )
        return int(run.id), [(int(item.id), item.valid_time) for item in ordered]


def _score_grib_item(item) -> tuple[int, int, int, int]:
    size = int(getattr(item, "size", 0) or 0)
    file_ts = (getattr(item, "meta", {}) or {}).get("file_timestamp")
    ts_num = int(file_ts) if isinstance(file_ts, str) and file_ts.isdigit() else 0
    mtime_ns = int(getattr(item, "mtime_ns", 0) or 0)
    subset = (getattr(item, "meta", {}) or {}).get("subset")
    subset_num = int(subset) if isinstance(subset, str) and subset.isdigit() else -1
    return (size, ts_num, mtime_ns, subset_num)


def _resolve_grib_files(
    data_source: LocalDataSource,
    *,
    run_time: datetime,
    valid_times: list[datetime],
) -> dict[datetime, Path]:
    index = data_source.list_files(kinds={"ecmwf"})
    run_iso = _time_iso_z(run_time)

    wanted = {_time_iso_z(dt): dt for dt in valid_times}
    buckets: dict[str, list[object]] = defaultdict(list)

    for item in index.items:
        meta = getattr(item, "meta", {}) or {}
        if meta.get("init_time") != run_iso:
            continue
        valid_iso = meta.get("valid_time")
        if valid_iso not in wanted:
            continue
        buckets[str(valid_iso)].append(item)

    missing: list[str] = []
    resolved: dict[datetime, Path] = {}
    for valid_iso, dt in wanted.items():
        candidates = buckets.get(valid_iso)
        if not candidates:
            missing.append(valid_iso)
            continue
        best = max(candidates, key=_score_grib_item)
        rel_path = getattr(best, "relative_path", None)
        if not isinstance(rel_path, str) or rel_path.strip() == "":
            raise RuntimeError(f"Invalid relative_path for GRIB index item: {best}")
        resolved[dt] = data_source.open_path(rel_path)

    if missing:
        raise FileNotFoundError(
            "Missing ECMWF GRIB files for valid_time(s): " + ", ".join(missing)
        )
    return resolved


@dataclass(frozen=True)
class SurfaceFields:
    lat: np.ndarray
    lon: np.ndarray
    t2m_k: np.ndarray
    tcc: np.ndarray
    tp_m: Optional[np.ndarray]
    u10: np.ndarray
    v10: np.ndarray


def _pick_surface_dataset(datasets: list[xr.Dataset]) -> xr.Dataset:
    desired = ("t2m", "tcc", "u10", "v10", "tp")
    best: tuple[tuple[int, int], xr.Dataset] | None = None
    for ds in datasets:
        present = set(ds.data_vars)
        score = sum(1 for name in desired if name in present)
        if score <= 0:
            continue
        lat_len = int(ds.sizes.get("latitude", 0))
        lon_len = int(ds.sizes.get("longitude", 0))
        area = lat_len * lon_len
        key = (score, area)
        if best is None or key > best[0]:
            best = (key, ds)
    if best is None:
        raise ValueError("No suitable surface dataset found in GRIB")
    return best[1]


def _load_surface_fields(grib_path: Path) -> SurfaceFields:
    datasets = cfgrib.open_datasets(str(grib_path), backend_kwargs={"indexpath": ""})
    try:
        ds = _pick_surface_dataset(datasets)

        missing = [name for name in ("t2m", "tcc", "u10", "v10") if name not in ds]
        if missing:
            raise ValueError(
                f"GRIB surface dataset missing required variables: {missing} ({grib_path.name})"
            )

        lat = np.asarray(ds["latitude"].values, dtype=np.float32)
        lon = np.asarray(ds["longitude"].values, dtype=np.float32)
        t2m = np.asarray(ds["t2m"].values, dtype=np.float32)
        tcc = np.asarray(ds["tcc"].values, dtype=np.float32)
        u10 = np.asarray(ds["u10"].values, dtype=np.float32)
        v10 = np.asarray(ds["v10"].values, dtype=np.float32)
        tp = np.asarray(ds["tp"].values, dtype=np.float32) if "tp" in ds else None

        return SurfaceFields(
            lat=lat,
            lon=lon,
            t2m_k=t2m,
            tcc=tcc,
            tp_m=tp,
            u10=u10,
            v10=v10,
        )
    finally:
        for candidate in datasets:
            try:
                candidate.close()
            except Exception:
                pass


def _build_tile_cube(
    *,
    time_value: datetime,
    lat: np.ndarray,
    lon: np.ndarray,
    t2m_k: np.ndarray,
    tcc: np.ndarray,
    precip_amount_m: np.ndarray,
) -> DataCube:
    time64 = np.datetime64(time_value.strftime("%Y-%m-%dT%H:%M:%S"))
    ds = xr.Dataset(
        data_vars={
            "t2m": (("time", "lat", "lon"), t2m_k[None, :, :]),
            "tcc": (("time", "lat", "lon"), tcc[None, :, :]),
            "precipitation_amount": (
                ("time", "lat", "lon"),
                precip_amount_m[None, :, :],
            ),
        },
        coords={
            "time": np.asarray([time64]),
            "lat": lat.astype(np.float32, copy=False),
            "lon": lon.astype(np.float32, copy=False),
        },
    )
    ds["t2m"].attrs.update({"units": "K", "long_name": "2 metre temperature"})
    ds["tcc"].attrs.update({"units": "(0 - 1)", "long_name": "Total cloud cover"})
    ds["precipitation_amount"].attrs.update(
        {
            "units": "m",
            "long_name": "precipitation amount over the previous interval",
        }
    )
    return DataCube.from_dataset(ds)


def _generate_tiles_for_time(
    *,
    cube: DataCube,
    tiles_dir: Path,
    valid_time: datetime,
    min_zoom: int,
    max_zoom: int,
) -> None:
    t0 = perf_counter()
    temp_result = TemperatureTileGenerator(cube).generate(
        tiles_dir,
        valid_time=valid_time,
        level="sfc",
        min_zoom=min_zoom,
        max_zoom=max_zoom,
        formats=("png",),
    )
    print(
        f"  temp tiles={temp_result.tiles_written} zoom={min_zoom}-{max_zoom} ({perf_counter() - t0:.1f}s)"
    )

    t0 = perf_counter()
    tcc_result = TccTileGenerator(cube).generate(
        tiles_dir,
        valid_time=valid_time,
        level="sfc",
        min_zoom=min_zoom,
        max_zoom=max_zoom,
        formats=("png",),
    )
    print(
        f"  tcc tiles={tcc_result.tiles_written} zoom={min_zoom}-{max_zoom} ({perf_counter() - t0:.1f}s)"
    )

    t0 = perf_counter()
    precip_result = PrecipAmountTileGenerator(cube).generate(
        tiles_dir,
        valid_time=valid_time,
        level="sfc",
        min_zoom=min_zoom,
        max_zoom=max_zoom,
        formats=("png",),
    )
    print(
        f"  precip tiles={precip_result.tiles_written} zoom={min_zoom}-{max_zoom} ({perf_counter() - t0:.1f}s)"
    )


def _write_wind_datacube(
    *,
    output_path: Path,
    times: list[datetime],
    lat: np.ndarray,
    lon: np.ndarray,
    u10: np.ndarray,
    v10: np.ndarray,
) -> Path:
    time_values = np.asarray(
        [np.datetime64(dt.strftime("%Y-%m-%dT%H:%M:%S")) for dt in times]
    )
    level = xr.DataArray(
        [0.0], dims=["level"], attrs={"long_name": "surface", "units": "1"}
    )

    ds = xr.Dataset(
        data_vars={
            "u10": (("time", "level", "lat", "lon"), u10[:, None, :, :]),
            "v10": (("time", "level", "lat", "lon"), v10[:, None, :, :]),
        },
        coords={
            "time": time_values,
            "level": level,
            "lat": lat.astype(np.float32, copy=False),
            "lon": lon.astype(np.float32, copy=False),
        },
        attrs={
            "datacube_schema_version": 1,
            "datacube_missing": "NaN",
        },
    )
    ds["u10"].attrs.update({"units": "m/s", "long_name": "10 metre U wind component"})
    ds["v10"].attrs.update({"units": "m/s", "long_name": "10 metre V wind component"})

    options = DataCubeWriteOptions(
        compression_level=4,
        chunk_time=1,
        chunk_level=1,
        chunk_lat=256,
        chunk_lon=256,
    )
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return write_datacube(ds, output_path, options=options)


def _upsert_wind_assets(
    engine,
    *,
    run_time: datetime,
    cube_path: Path,
    valid_times: list[datetime],
    level: str,
    status: str,
    version_policy: str,
) -> int:
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        run = session.execute(
            select(EcmwfRun).where(EcmwfRun.run_time == run_time)
        ).scalar_one_or_none()
        if run is None:
            raise RuntimeError(
                "ECMWF run not found in catalog DB. Run times seeding first."
            )

        data_root = (REPO_ROOT / "Data").resolve()
        try:
            rel_path = str(cube_path.resolve().relative_to(data_root))
        except ValueError:
            rel_path = str(cube_path.resolve())

        times = (
            session.execute(
                select(EcmwfTime).where(
                    EcmwfTime.run_id == run.id,
                    EcmwfTime.valid_time.in_(valid_times),
                )
            )
            .scalars()
            .all()
        )

        inserted = 0
        for time in times:
            existing_max = session.execute(
                select(func.max(EcmwfAsset.version)).where(
                    EcmwfAsset.run_id == run.id,
                    EcmwfAsset.time_id == time.id,
                    EcmwfAsset.variable == "wind",
                    EcmwfAsset.level == level,
                )
            ).scalar_one()
            max_version = int(existing_max or 0)
            if version_policy == "bump":
                version = max_version + 1
            elif version_policy == "overwrite" and max_version > 0:
                version = max_version
            else:
                version = 1 if max_version == 0 else max_version + 1

            if version_policy == "overwrite" and max_version > 0:
                asset = session.execute(
                    select(EcmwfAsset).where(
                        EcmwfAsset.run_id == run.id,
                        EcmwfAsset.time_id == time.id,
                        EcmwfAsset.variable == "wind",
                        EcmwfAsset.level == level,
                        EcmwfAsset.version == version,
                    )
                ).scalar_one_or_none()
                if asset is None:
                    asset = EcmwfAsset(
                        run_id=run.id,
                        time_id=time.id,
                        variable="wind",
                        level=level,
                        status=status,
                        version=version,
                        path=rel_path,
                    )
                    session.add(asset)
                    inserted += 1
                else:
                    asset.status = status
                    asset.path = rel_path
            else:
                session.add(
                    EcmwfAsset(
                        run_id=run.id,
                        time_id=time.id,
                        variable="wind",
                        level=level,
                        status=status,
                        version=version,
                        path=rel_path,
                    )
                )
                inserted += 1

        session.commit()
        return inserted


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate ECMWF forecast raster tiles (temp/tcc/precip) for zoom 0–6, "
            "build a wind (u10/v10) NetCDF DataCube, and write wind assets into the catalog DB."
        )
    )
    parser.add_argument(
        "--run",
        required=True,
        help="Run init time (ISO8601 or YYYYMMDDTHHMMSSZ), e.g. 2025-12-22T00:00:00Z",
    )
    parser.add_argument("--lead-start", type=int, default=0)
    parser.add_argument("--lead-end", type=int, default=240)
    parser.add_argument("--lead-step", type=int, default=3)

    parser.add_argument(
        "--tiles-dir",
        type=Path,
        default=Path("Data/tiles"),
        help="Tiles root directory (default: Data/tiles). ECMWF tiles are written under ecmwf/*",
    )
    parser.add_argument("--min-zoom", type=int, default=0)
    parser.add_argument("--max-zoom", type=int, default=6)

    parser.add_argument(
        "--wind-cube",
        type=Path,
        default=None,
        help="Output path for wind datacube (default: Data/cubes/ecmwf/wind/<run>.nc)",
    )

    parser.add_argument(
        "--database-url",
        default=None,
        help="SQLAlchemy database URL (default: sqlite+pysqlite:///Data/catalog.db)",
    )
    parser.add_argument(
        "--asset-level",
        default="sfc",
        help="Catalog level key for the wind asset (default: sfc)",
    )
    parser.add_argument(
        "--asset-status",
        default="complete",
        help="Catalog status for the wind asset (default: complete)",
    )
    parser.add_argument(
        "--asset-version-policy",
        choices=("bump", "overwrite"),
        default="bump",
        help="If bump, insert a new version each run; if overwrite, update latest version when present.",
    )
    parser.add_argument(
        "--skip-tiles",
        action="store_true",
        help="Skip raster tile generation (still builds wind cube + DB assets)",
    )
    parser.add_argument(
        "--skip-wind",
        action="store_true",
        help="Skip wind cube generation + DB assets (still builds raster tiles)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only resolve GRIB inputs and planned outputs; do not write tiles/cubes/DB",
    )
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    warnings.filterwarnings("ignore", category=FutureWarning, module="cfgrib")

    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    run_time = _parse_time(args.run)
    valid_times = _iter_valid_times(
        run_time=run_time,
        start_hour=int(args.lead_start),
        end_hour=int(args.lead_end),
        step_hour=int(args.lead_step),
    )
    if len(valid_times) == 0:
        raise ValueError("No valid times generated; check lead range args")

    run_key = _time_key(run_time)
    tiles_dir = Path(args.tiles_dir).resolve()
    wind_cube_path = (
        Path(args.wind_cube).resolve()
        if args.wind_cube is not None
        else (
            REPO_ROOT / "Data" / "cubes" / "ecmwf" / "wind" / f"{run_key}.nc"
        ).resolve()
    )

    db_url = str(args.database_url or _default_database_url(repo_root=REPO_ROOT))
    engine = create_engine(db_url)

    run_id, catalog_times = _ensure_catalog_times(
        engine, run_time=run_time, valid_times=valid_times
    )
    print(f"catalog_run_id={run_id} run={run_key} db={db_url}")
    print(
        f"catalog_times={len(catalog_times)} range={_time_key(catalog_times[0][1])}..{_time_key(catalog_times[-1][1])}"
    )

    data_source = LocalDataSource()
    resolved = _resolve_grib_files(
        data_source, run_time=run_time, valid_times=[dt for _id, dt in catalog_times]
    )

    if args.dry_run:
        print("dry_run=true")
        for dt in sorted(resolved):
            print(f"{_time_key(dt)} -> {resolved[dt]}")
        print(f"tiles_dir={tiles_dir}")
        print(f"wind_cube={wind_cube_path}")
        return 0

    time_sequence = [dt for _id, dt in catalog_times]

    prev_tp: Optional[np.ndarray] = None
    lat_ref: Optional[np.ndarray] = None
    lon_ref: Optional[np.ndarray] = None
    u10_cube: Optional[np.ndarray] = None
    v10_cube: Optional[np.ndarray] = None

    for idx, dt in enumerate(time_sequence):
        grib_path = resolved[dt]
        print(
            f"[{idx + 1}/{len(time_sequence)}] load {grib_path.name} time={_time_key(dt)}"
        )
        fields = _load_surface_fields(grib_path)

        if lat_ref is None:
            lat_ref = fields.lat
            lon_ref = fields.lon
            if not args.skip_wind:
                u10_cube = np.empty(
                    (len(time_sequence), lat_ref.size, lon_ref.size), dtype=np.float32
                )
                v10_cube = np.empty_like(u10_cube)
        else:
            if not np.array_equal(lat_ref, fields.lat) or not np.array_equal(
                lon_ref, fields.lon
            ):
                raise ValueError(
                    f"lat/lon grid mismatch at {_time_key(dt)} (file={grib_path.name})"
                )

        if not args.skip_wind:
            assert u10_cube is not None and v10_cube is not None
            u10_cube[idx] = fields.u10
            v10_cube[idx] = fields.v10

        tp = fields.tp_m
        if tp is None:
            tp = np.zeros_like(fields.t2m_k, dtype=np.float32)

        if prev_tp is None:
            precip_amount = np.zeros_like(tp, dtype=np.float32)
        else:
            precip_amount = (tp - prev_tp).astype(np.float32, copy=False)
            precip_amount = np.clip(precip_amount, 0.0, None)
        prev_tp = tp

        if args.skip_tiles:
            continue

        cube = _build_tile_cube(
            time_value=dt,
            lat=fields.lat,
            lon=fields.lon,
            t2m_k=fields.t2m_k,
            tcc=fields.tcc,
            precip_amount_m=precip_amount,
        )
        try:
            _generate_tiles_for_time(
                cube=cube,
                tiles_dir=tiles_dir,
                valid_time=dt,
                min_zoom=int(args.min_zoom),
                max_zoom=int(args.max_zoom),
            )
        finally:
            try:
                cube.dataset.close()
            except Exception:
                pass

    if args.skip_wind:
        print("skip_wind=true (no wind datacube/assets)")
        return 0

    assert lat_ref is not None and lon_ref is not None
    assert u10_cube is not None and v10_cube is not None
    written = _write_wind_datacube(
        output_path=wind_cube_path,
        times=time_sequence,
        lat=lat_ref,
        lon=lon_ref,
        u10=u10_cube,
        v10=v10_cube,
    )
    print(f"wind_datacube_written={written}")

    inserted = _upsert_wind_assets(
        engine,
        run_time=run_time,
        cube_path=written,
        valid_times=time_sequence,
        level=str(args.asset_level),
        status=str(args.asset_status),
        version_policy=str(args.asset_version_policy),
    )
    print(f"wind_assets_written={inserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
