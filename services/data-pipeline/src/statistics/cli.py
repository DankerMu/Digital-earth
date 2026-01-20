from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Final, Iterable, Sequence

import xarray as xr

from digital_earth_config.local_data import get_local_data_paths
from .batch import run_historical_statistics
from .config import get_statistics_config
from .sources import (
    ArchiveDatasetSource,
    CldasDirectorySource,
    SourceKind,
    StatisticsDataSource,
)
from .storage import StatisticsStore
from .tiles import StatisticsTileGenerator
from .time_windows import TimeWindow, TimeWindowKind, iter_time_windows


_SEGMENT_SAFE_RE: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9_]+")


def _safe_segment(value: str) -> str:
    cleaned = _SEGMENT_SAFE_RE.sub("_", str(value or "").strip())
    cleaned = cleaned.strip("_")
    return cleaned or "unknown"


def _parse_csv(values: Sequence[str]) -> list[str]:
    parts: list[str] = []
    for raw in values:
        if raw is None:
            continue
        text = str(raw).strip()
        if text == "":
            continue
        parts.extend([p.strip() for p in text.split(",") if p.strip()])
    return parts


def _parse_percentiles(values: Sequence[str]) -> list[float]:
    raw = _parse_csv(values)
    out: list[float] = []
    for item in raw:
        try:
            value = float(item)
        except ValueError as exc:
            raise ValueError(f"Invalid percentile value: {item!r}") from exc
        out.append(value)
    return out


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m statistics",
        description="Batch compute historical statistics grids and (optionally) generate tiles.",
    )

    parser.add_argument(
        "--source",
        choices=("cldas", "archive"),
        default="cldas",
        help="Input data source (default: cldas)",
    )
    parser.add_argument("--variable", required=True, help="Variable name (e.g., TMP)")

    parser.add_argument(
        "--start",
        required=True,
        help="Window start (UTC) ISO8601, aligned to window boundaries",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="Window end (UTC) ISO8601, aligned to window boundaries",
    )
    parser.add_argument(
        "--window-kind",
        choices=("monthly", "seasonal", "annual"),
        required=True,
        help="Time window kind: monthly/seasonal/annual",
    )

    parser.add_argument(
        "--cldas-root", default=None, help="Optional CLDAS root directory"
    )
    parser.add_argument(
        "--archive-dataset",
        default=None,
        help="Archive dataset path (NetCDF); required when --source=archive",
    )
    parser.add_argument(
        "--engine",
        default=None,
        help="Optional xarray engine for reading inputs (e.g., h5netcdf)",
    )

    parser.add_argument(
        "--output-dir", default=None, help="Statistics output root directory"
    )
    parser.add_argument(
        "--output-source-name",
        default=None,
        help="Output storage source segment (default: same as --source)",
    )
    parser.add_argument("--version", default=None, help="Output version tag (e.g., v1)")

    parser.add_argument(
        "--percentile",
        dest="percentiles",
        action="append",
        default=[],
        help="Percentile(s) in (0, 100). May be repeated or comma-separated.",
    )
    parser.add_argument(
        "--no-percentiles",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Disable percentile computation (default: false)",
    )
    parser.add_argument(
        "--exact-percentiles-max-samples",
        type=int,
        default=None,
        help="If window sample count is <= this threshold, compute percentiles exactly",
    )

    parser.add_argument(
        "--tiles",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Generate tiles from statistics output (default: disabled)",
    )
    parser.add_argument(
        "--tiles-output-dir", default=None, help="Tiles output root directory"
    )
    parser.add_argument(
        "--tile-var",
        dest="tile_vars",
        action="append",
        default=[],
        help="Dataset variable to tile (e.g., mean, p50). Use 'all' to tile all stats vars.",
    )
    parser.add_argument(
        "--layer-prefix", default=None, help="Tiles layer prefix (default: config)"
    )
    parser.add_argument(
        "--legend-filename",
        default=None,
        help="Legend JSON filename in config dir (default: config)",
    )
    parser.add_argument(
        "--legend-config-dir",
        default=None,
        help="Optional override for config dir containing legend JSON",
    )

    parser.add_argument("--min-zoom", type=int, default=None)
    parser.add_argument("--max-zoom", type=int, default=None)
    parser.add_argument("--tile-size", type=int, default=None)
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
        help="Print planned windows without running computation (default: false)",
    )

    return parser


def _resolve_windows(args: argparse.Namespace) -> list[TimeWindow]:
    kind: TimeWindowKind = str(args.window_kind)  # type: ignore[assignment]
    return list(iter_time_windows(kind=kind, start=args.start, end=args.end))


def _resolve_source(
    args: argparse.Namespace, *, cfg
) -> tuple[SourceKind, StatisticsDataSource]:
    source_kind: SourceKind = str(args.source)  # type: ignore[assignment]
    engine = str(args.engine).strip() if args.engine else None

    if source_kind == "cldas":
        root_dir: Path
        if args.cldas_root:
            root_dir = Path(args.cldas_root)
        elif cfg.sources.cldas.root_dir is not None:
            root_dir = cfg.sources.cldas.root_dir
        else:
            root_dir = get_local_data_paths().cldas_dir
        return source_kind, CldasDirectorySource(
            root_dir, engine=engine or cfg.sources.cldas.engine
        )

    if source_kind == "archive":
        path = args.archive_dataset or cfg.sources.archive.dataset_path
        if path is None:
            raise ValueError("--archive-dataset is required when --source=archive")
        return source_kind, ArchiveDatasetSource(
            path, engine=engine or cfg.sources.archive.engine
        )

    raise ValueError(f"Unsupported source: {source_kind}")


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    cfg = get_statistics_config()

    windows = _resolve_windows(args)
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

    source_kind, source = _resolve_source(args, cfg=cfg)

    output_dir = Path(args.output_dir) if args.output_dir else cfg.output.root_dir
    store = StatisticsStore(output_dir)

    version = str(args.version or cfg.output.version).strip() or "v1"
    output_source_name = (
        str(args.output_source_name or source_kind).strip() or source_kind
    )

    percentiles: list[float]
    if bool(args.no_percentiles):
        percentiles = []
    else:
        percentiles = _parse_percentiles(tuple(args.percentiles)) or list(
            cfg.statistics.percentiles
        )

    exact_limit = (
        int(args.exact_percentiles_max_samples)
        if args.exact_percentiles_max_samples is not None
        else int(cfg.statistics.exact_percentiles_max_samples)
    )

    results = run_historical_statistics(
        source=source,
        variable=str(args.variable),
        windows=windows,
        store=store,
        output_source_name=output_source_name,
        version=version,
        percentiles=percentiles,
        exact_percentiles_max_samples=exact_limit,
    )

    tile_results: list[object] = []
    if bool(args.tiles):
        tiles_output_dir = (
            Path(args.tiles_output_dir) if args.tiles_output_dir else cfg.tiles.root_dir
        )
        layer_prefix = (
            str(args.layer_prefix or cfg.tiles.layer_prefix).strip() or "statistics"
        )
        formats = _parse_csv(tuple(args.formats)) or list(cfg.tiles.formats)

        legend_filename = str(args.legend_filename or cfg.tiles.legend_filename).strip()
        legend_config_dir = args.legend_config_dir

        requested_tile_vars = _parse_csv(tuple(args.tile_vars)) or ["mean"]

        for item in results:
            with xr.open_dataset(item.artifact.dataset_path, engine="h5netcdf") as ds:
                ds.load()
                available = list(ds.data_vars)

                if (
                    len(requested_tile_vars) == 1
                    and requested_tile_vars[0].lower() == "all"
                ):
                    tile_vars = [name for name in available if name != "count"]
                else:
                    tile_vars = requested_tile_vars

                for var_name in tile_vars:
                    if var_name not in ds.data_vars:
                        raise ValueError(
                            f"Requested tile var {var_name!r} not found; available={available}"
                        )

                    layer = "/".join(
                        [
                            _safe_segment(layer_prefix),
                            _safe_segment(source_kind),
                            _safe_segment(str(args.variable).lower()),
                            _safe_segment(var_name),
                        ]
                    )
                    generator = StatisticsTileGenerator(
                        ds, variable=var_name, layer=layer
                    )
                    tile_results.append(
                        generator.generate(
                            tiles_output_dir,
                            version=version,
                            window_key=item.window.key,
                            min_zoom=args.min_zoom,
                            max_zoom=args.max_zoom,
                            tile_size=args.tile_size,
                            formats=formats,
                            legend_config_dir=legend_config_dir,
                            legend_filename=legend_filename,
                        )
                    )

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
    for tile in tile_results:
        print(json.dumps(tile.__dict__, ensure_ascii=False, default=str))
    return 0
