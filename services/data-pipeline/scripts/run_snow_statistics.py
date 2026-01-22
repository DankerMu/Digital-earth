from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence


PIPELINE_SRC = Path(__file__).resolve().parents[1] / "src"
REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_SRC = REPO_ROOT / "packages" / "config" / "src"

sys.path.insert(0, str(CONFIG_SRC))
sys.path.insert(0, str(PIPELINE_SRC))


def _utc_now_hour() -> datetime:
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _parse_csv_ints(values: Sequence[str]) -> list[int]:
    items: list[int] = []
    for raw in values:
        parts = [part.strip() for part in str(raw or "").split(",") if part.strip()]
        for part in parts:
            items.append(int(part))
    return items


def _load_default_days_from_config() -> list[int] | None:
    cfg_path = REPO_ROOT / "config" / "snow-statistics.yaml"
    if not cfg_path.is_file():
        return None
    try:
        import yaml  # type: ignore[import-not-found]
    except Exception:
        return None

    try:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    windows = raw.get("windows")
    if not isinstance(windows, dict):
        return None
    rolling = windows.get("rolling_days")
    if not isinstance(rolling, list):
        return None
    out: list[int] = []
    for value in rolling:
        try:
            days = int(value)
        except (TypeError, ValueError):
            continue
        if days > 0 and days not in out:
            out.append(days)
    return out or None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Batch compute snow historical statistics (snowfall sum + snow depth mean) "
            "for rolling day windows and optionally generate tiles."
        )
    )
    parser.add_argument(
        "--source",
        choices=("cldas", "archive"),
        default="cldas",
        help="Input source (default: cldas)",
    )
    parser.add_argument(
        "--snowfall-variable",
        required=True,
        help="Dataset variable name for snowfall amount (e.g., SNOWFALL, PRE)",
    )
    parser.add_argument(
        "--snow-depth-variable",
        required=True,
        help="Dataset variable name for snow depth (e.g., SD, SNOWH)",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="Window end time (UTC) ISO8601; defaults to current UTC hour",
    )
    parser.add_argument(
        "--days",
        action="append",
        default=[],
        help="Rolling window sizes in days; may be repeated or comma-separated",
    )
    parser.add_argument("--engine", default=None, help="Optional xarray engine")

    parser.add_argument("--cldas-root", default=None, help="Optional CLDAS root dir")
    parser.add_argument(
        "--archive-dataset",
        default=None,
        help="Archive dataset path (required when --source=archive)",
    )

    parser.add_argument("--output-dir", default=None, help="Statistics output root")
    parser.add_argument("--tiles-output-dir", default=None, help="Tiles output root")
    parser.add_argument("--version", default=None, help="Output version tag")

    parser.add_argument(
        "--tiles",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate tiles (default: enabled)",
    )
    parser.add_argument(
        "--format",
        dest="formats",
        action="append",
        default=[],
        help="Tile format(s): png, webp. May be repeated or comma-separated.",
    )
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Print planned windows without running computation",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)

    from digital_earth_config.local_data import get_local_data_paths
    from statistics.batch import run_historical_statistics
    from statistics.config import get_statistics_config
    from statistics.sources import ArchiveDatasetSource, CldasDirectorySource
    from statistics.storage import StatisticsStore
    from statistics.tiles import StatisticsTileGenerator
    from statistics.time_windows import TimeWindow, parse_time

    import xarray as xr

    cfg = get_statistics_config()

    end = _utc_now_hour() if args.end is None else parse_time(args.end)
    end = end.astimezone(timezone.utc)

    days = _parse_csv_ints(tuple(args.days))
    if not days:
        days = _load_default_days_from_config() or [7, 30, 90]
    days = sorted({int(d) for d in days if int(d) > 0})

    windows = [
        TimeWindow(kind="rolling_days", start=end - timedelta(days=day), end=end)
        for day in days
    ]

    if args.dry_run:
        for window in windows:
            print(
                json.dumps(
                    {
                        "kind": window.kind,
                        "key": window.key,
                        "start": window.start_iso,
                        "end": window.end_iso,
                    },
                    ensure_ascii=False,
                )
            )
        return 0

    engine = str(args.engine).strip() if args.engine else None

    if args.source == "cldas":
        if args.cldas_root:
            cldas_root = Path(args.cldas_root)
        elif cfg.sources.cldas.root_dir is not None:
            cldas_root = cfg.sources.cldas.root_dir
        else:
            cldas_root = get_local_data_paths().cldas_dir
        source = CldasDirectorySource(cldas_root, engine=engine or cfg.sources.cldas.engine)
        source_name = "cldas"
    else:
        dataset_path = args.archive_dataset or cfg.sources.archive.dataset_path
        if dataset_path is None:
            raise ValueError("--archive-dataset is required when --source=archive")
        source = ArchiveDatasetSource(dataset_path, engine=engine or cfg.sources.archive.engine)
        source_name = "archive"

    version = str(args.version or cfg.output.version).strip() or "v1"
    output_dir = Path(args.output_dir) if args.output_dir else cfg.output.root_dir
    tiles_dir = Path(args.tiles_output_dir) if args.tiles_output_dir else cfg.tiles.root_dir

    store = StatisticsStore(output_dir)

    results = []
    for variable in (str(args.snowfall_variable), str(args.snow_depth_variable)):
        results.extend(
            run_historical_statistics(
                source=source,
                variable=variable,
                windows=windows,
                store=store,
                output_source_name=source_name,
                version=version,
                percentiles=[],
                exact_percentiles_max_samples=0,
            )
        )

    if not bool(args.tiles):
        for item in results:
            print(
                json.dumps(
                    {
                        "dataset_path": str(item.artifact.dataset_path),
                        "metadata_path": str(item.artifact.metadata_path),
                        "window_key": item.window.key,
                        "version": version,
                        "samples": item.samples,
                    },
                    ensure_ascii=False,
                )
            )
        return 0

    formats_raw: list[str] = []
    for raw in args.formats:
        formats_raw.extend([p.strip() for p in str(raw or "").split(",") if p.strip()])
    formats = formats_raw or list(cfg.tiles.formats)

    for item in results:
        var_lower = item.artifact.dataset_path.parents[3].name.lower()
        with xr.open_dataset(item.artifact.dataset_path, engine="h5netcdf") as ds:
            ds.load()

            tile_var = (
                "sum"
                if var_lower == str(args.snowfall_variable).strip().lower()
                else "mean"
            )
            layer = "/".join(
                [
                    str(cfg.tiles.layer_prefix or "statistics").strip() or "statistics",
                    source_name,
                    str(var_lower),
                    tile_var,
                ]
            )
            generator = StatisticsTileGenerator(ds, variable=tile_var, layer=layer)
            result = generator.generate(
                tiles_dir,
                version=version,
                window_key=item.window.key,
                formats=formats,
                legend_filename=str(cfg.tiles.legend_filename or "legend.json"),
            )
            print(json.dumps(result.__dict__, ensure_ascii=False, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
