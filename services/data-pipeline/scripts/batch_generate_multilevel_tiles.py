from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_SRC = Path(__file__).resolve().parents[1] / "src"
CONFIG_SRC = REPO_ROOT / "packages" / "config" / "src"
SHARED_SRC = REPO_ROOT / "packages" / "shared" / "src"

for src in (PIPELINE_SRC, SHARED_SRC, CONFIG_SRC):
    sys.path.insert(0, str(src))

from datacube.decoder import decode_grib  # noqa: E402
from datacube.errors import DataCubeDecodeError  # noqa: E402
from tiles.generate import DEFAULT_TILE_FORMATS, generate_ecmwf_raster_tiles  # noqa: E402
from tiling.humidity_tiles import HumidityTileGenerator, HumidityTilingError  # noqa: E402


DEFAULT_INPUT_GLOB = "Data/EC-forecast/EC预报/W_NAFP_C_ECMF_*.grib"
DEFAULT_LEVELS = ("sfc", "850", "700", "500", "300")


def _parse_formats(values: Sequence[str]) -> tuple[str, ...]:
    formats: list[str] = []
    for raw in values:
        if raw is None:
            continue
        text = str(raw).strip()
        if text == "":
            continue
        parts = [part.strip() for part in text.split(",") if part.strip()]
        formats.extend(parts)
    deduped: list[str] = []
    for fmt in formats:
        lowered = fmt.lower()
        if lowered not in deduped:
            deduped.append(lowered)
    return tuple(deduped)


def _parse_levels(values: Sequence[str]) -> tuple[str, ...]:
    """Parse one or more --levels values.

    Accepts comma-separated values and de-duplicates while preserving order.
    """

    levels: list[str] = []
    for raw in values:
        if raw is None:
            continue
        text = str(raw).strip()
        if text == "":
            continue
        parts = [part.strip() for part in text.split(",") if part.strip()]
        levels.extend(parts)

    deduped: list[str] = []
    seen: set[str] = set()
    for level in levels:
        normalized = str(level).strip()
        if normalized == "":
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return tuple(deduped)


def _is_surface_level(level: str) -> bool:
    normalized = (level or "").strip().lower()
    return normalized in {"sfc", "surface"}


def _message_valid_time(message) -> datetime:
    date = message.get("validityDate")
    time = message.get("validityTime")
    if date is None or time is None:
        raise ValueError("Missing GRIB validityDate/validityTime")

    date_int = int(date)
    time_int = int(time)
    hh = time_int // 100
    mm = time_int % 100
    dt = datetime.strptime(str(date_int), "%Y%m%d").replace(tzinfo=timezone.utc)
    return dt.replace(hour=int(hh), minute=int(mm))


@dataclass(frozen=True)
class _GribCandidate:
    path: Path
    valid_time: datetime
    score: tuple[int, ...]
    size: int
    mtime_ns: int

    def sort_key(self) -> tuple[int, ...]:
        return (*self.score, int(self.size), int(self.mtime_ns))


def _probe_grib_candidate(path: Path) -> _GribCandidate:
    try:
        from cfgrib.messages import FileStream
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "This script requires the optional dependency `cfgrib` "
            "(and the `eccodes` system library)."
        ) from exc

    fs = FileStream(str(path), errors="ignore")

    valid_time: datetime | None = None
    short_names: set[str] = set()
    combos: set[tuple[str, str]] = set()

    for _offset, msg in fs.items():
        if valid_time is None:
            valid_time = _message_valid_time(msg)
        short = msg.get("shortName")
        if short:
            short_names.add(str(short))
        level_type = msg.get("typeOfLevel")
        if short and level_type:
            combos.add((str(short), str(level_type)))

    if valid_time is None:
        raise ValueError(f"Empty GRIB file: {path}")

    has_t2m = "2t" in short_names or "t2m" in short_names
    has_tcc = "tcc" in short_names
    has_u10 = "10u" in short_names
    has_v10 = "10v" in short_names
    has_t_pl = ("t", "isobaricInhPa") in combos
    has_u_pl = ("u", "isobaricInhPa") in combos
    has_v_pl = ("v", "isobaricInhPa") in combos
    has_r_pl = ("r", "isobaricInhPa") in combos

    score = (
        int(has_t2m),
        int(has_tcc),
        int(has_u10),
        int(has_v10),
        int(has_t_pl),
        int(has_u_pl),
        int(has_v_pl),
        int(has_r_pl),
    )

    try:
        stat = path.stat()
        size = int(stat.st_size)
        mtime_ns = int(stat.st_mtime_ns)
    except OSError:
        size = 0
        mtime_ns = 0

    return _GribCandidate(
        path=path,
        valid_time=valid_time,
        score=score,
        size=size,
        mtime_ns=mtime_ns,
    )


def _dedupe_by_valid_time(paths: Sequence[Path]) -> list[_GribCandidate]:
    candidates = [_probe_grib_candidate(path) for path in paths]
    by_time: dict[datetime, list[_GribCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_time[candidate.valid_time].append(candidate)

    deduped: dict[datetime, _GribCandidate] = {}
    for valid_time, items in by_time.items():
        deduped[valid_time] = max(items, key=lambda c: c.sort_key())

    return sorted(deduped.values(), key=lambda c: c.valid_time)


def _select_standard_ecmwf_times(paths: Sequence[Path]) -> list[_GribCandidate]:
    deduped = _dedupe_by_valid_time(paths)
    if not deduped:
        return []

    run_time = min(candidate.valid_time for candidate in deduped)
    selected: list[_GribCandidate] = []
    for candidate in deduped:
        lead_hours = int((candidate.valid_time - run_time).total_seconds() // 3600)
        if lead_hours < 0 or lead_hours > 240:
            continue
        if lead_hours <= 72:
            if lead_hours % 3 != 0:
                continue
        else:
            if lead_hours % 6 != 0:
                continue
        selected.append(candidate)

    return selected


def _expand_inputs(values: Sequence[str]) -> list[Path]:
    patterns = list(values) if values else [DEFAULT_INPUT_GLOB]
    candidates: list[Path] = []
    for raw in patterns:
        matches = glob.glob(raw)
        if matches:
            candidates.extend(Path(match) for match in matches)
            continue
        candidates.append(Path(raw))

    resolved: dict[str, Path] = {}
    for path in candidates:
        resolved[str(path.resolve())] = path
    return sorted(resolved.values(), key=lambda p: str(p))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python services/data-pipeline/scripts/batch_generate_multilevel_tiles.py",
        description=(
            "Batch-generate ECMWF temperature + wind speed + cloud/humidity tiles for multiple levels "
            "(surface + pressure levels) from local GRIB files."
        ),
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help=(
            "GRIB file paths or glob patterns. "
            f"Defaults to {DEFAULT_INPUT_GLOB!r} when omitted."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("Data/tiles"),
        help=(
            "Tiles root directory (default: Data/tiles). Output is written under "
            "ecmwf/temp/<time>/<level>/..., ecmwf/wind_speed/<time>/<level>/..., "
            "ecmwf/tcc/<time>/sfc/... and ecmwf/humidity/<time>/<level>/..."
        ),
    )
    parser.add_argument(
        "--valid-time",
        default=None,
        help="Optional ISO8601 timestamp; defaults to the valid_time in each GRIB.",
    )
    parser.add_argument(
        "--levels",
        action="append",
        default=[",".join(DEFAULT_LEVELS)],
        help=(
            "Comma-separated list of levels to generate (e.g. sfc,850,700,500,300). "
            f"Defaults to {','.join(DEFAULT_LEVELS)}. May be repeated."
        ),
    )
    parser.add_argument(
        "--standard-cadence",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Filter inputs to ECMWF's standard 53-step cadence "
            "(0–72h every 3h, 72–240h every 6h), deduplicated by valid_time. "
            "Disable to process every GRIB file."
        ),
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
        "--wind-speed-opacity",
        type=float,
        default=0.35,
        help="Wind speed tile opacity in [0, 1] (default: 0.35).",
    )
    parser.add_argument(
        "--cloud",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate surface cloud tiles (tcc) (default: true).",
    )
    parser.add_argument(
        "--humidity",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate isobaric humidity tiles (r) (default: true).",
    )
    parser.add_argument(
        "--humidity-opacity",
        type=float,
        default=1.0,
        help="Humidity tile opacity in [0, 1] (default: 1.0).",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop at the first file that fails.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    paths = _expand_inputs(tuple(args.inputs))
    if not paths:
        raise SystemExit("No GRIB files matched the provided inputs.")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    resolved_formats = _parse_formats(tuple(args.formats)) or DEFAULT_TILE_FORMATS
    resolved_levels = _parse_levels(tuple(args.levels))
    surface_levels = tuple(level for level in resolved_levels if _is_surface_level(level))
    isobaric_levels = tuple(
        level for level in resolved_levels if not _is_surface_level(level)
    )
    wants_surface = bool(surface_levels)
    wants_isobaric = bool(isobaric_levels)

    selected: list[_GribCandidate]
    if bool(args.standard_cadence):
        selected = _select_standard_ecmwf_times(paths)
        print(
            f"Selected {len(selected)} ECMWF valid_time(s) (standard cadence) "
            f"from {len(paths)} file(s).",
            file=sys.stderr,
        )
    else:
        selected = _dedupe_by_valid_time(paths)
        print(
            f"Selected {len(selected)} unique valid_time(s) from {len(paths)} file(s).",
            file=sys.stderr,
        )

    if not selected:
        raise SystemExit("No GRIB files matched the requested cadence/lead-time range.")

    failures = 0
    skipped_surface_decode = 0
    skipped_isobaric_decode = 0
    skipped_humidity_decode = 0

    for idx, candidate in enumerate(selected, start=1):
        path = candidate.path
        print(f"[{idx}/{len(selected)}] {path}")
        cube_surface = None
        cube_isobaric = None
        cube_humidity = None
        try:
            if wants_surface:
                try:
                    cube_surface = decode_grib(path, subset="surface")
                except DataCubeDecodeError as exc:
                    skipped_surface_decode += 1
                    print(
                        f"  WARNING: failed to decode surface subset: {exc}",
                        file=sys.stderr,
                    )
                    if args.fail_fast:
                        raise

            if wants_isobaric:
                try:
                    cube_isobaric = decode_grib(path, subset="isobaric")
                except DataCubeDecodeError as exc:
                    skipped_isobaric_decode += 1
                    print(
                        f"  WARNING: failed to decode isobaric subset: {exc}",
                        file=sys.stderr,
                    )
                    if args.fail_fast:
                        raise

                if bool(args.humidity):
                    try:
                        cube_humidity = decode_grib(path, subset="humidity")
                    except DataCubeDecodeError as exc:
                        skipped_humidity_decode += 1
                        print(
                            f"  WARNING: failed to decode humidity subset: {exc}",
                            file=sys.stderr,
                        )
                        if args.fail_fast:
                            raise

            resolved_valid_time = (
                args.valid_time if args.valid_time is not None else candidate.valid_time
            )

            if wants_surface and cube_surface is not None:
                results = generate_ecmwf_raster_tiles(
                    cube_surface,
                    output_dir,
                    valid_time=resolved_valid_time,
                    level="sfc",
                    temperature=True,
                    cloud=bool(args.cloud),
                    precipitation=False,
                    wind_speed=True,
                    wind_speed_opacity=float(args.wind_speed_opacity),
                    min_zoom=int(args.min_zoom) if args.min_zoom is not None else None,
                    max_zoom=int(args.max_zoom) if args.max_zoom is not None else None,
                    tile_size=int(args.tile_size)
                    if args.tile_size is not None
                    else None,
                    formats=resolved_formats,
                )
                for result in results:
                    print(
                        " ",
                        json.dumps(result.__dict__, ensure_ascii=False, default=str),
                    )

            if wants_isobaric and cube_isobaric is not None:
                for level in isobaric_levels:
                    results = generate_ecmwf_raster_tiles(
                        cube_isobaric,
                        output_dir,
                        valid_time=resolved_valid_time,
                        level=level,
                        temperature_variable="t",
                        temperature=True,
                        cloud=False,
                        precipitation=False,
                        wind_speed=True,
                        wind_speed_opacity=float(args.wind_speed_opacity),
                        min_zoom=int(args.min_zoom) if args.min_zoom is not None else None,
                        max_zoom=int(args.max_zoom) if args.max_zoom is not None else None,
                        tile_size=int(args.tile_size)
                        if args.tile_size is not None
                        else None,
                        formats=resolved_formats,
                    )
                    for result in results:
                        print(
                            " ",
                            json.dumps(result.__dict__, ensure_ascii=False, default=str),
                        )

            if (
                wants_isobaric
                and bool(args.humidity)
                and cube_humidity is not None
                and isobaric_levels
            ):
                generator = HumidityTileGenerator(cube_humidity)
                for level in isobaric_levels:
                    try:
                        result = generator.generate(
                            output_dir,
                            valid_time=resolved_valid_time,
                            level=level,
                            opacity=float(args.humidity_opacity),
                            min_zoom=int(args.min_zoom)
                            if args.min_zoom is not None
                            else None,
                            max_zoom=int(args.max_zoom)
                            if args.max_zoom is not None
                            else None,
                            tile_size=int(args.tile_size)
                            if args.tile_size is not None
                            else None,
                            formats=resolved_formats,
                        )
                        print(
                            " ",
                            json.dumps(result.__dict__, ensure_ascii=False, default=str),
                        )
                    except HumidityTilingError as exc:
                        print(
                            f"  WARNING: failed to generate humidity tiles for level={level!r}: {exc}",
                            file=sys.stderr,
                        )
                        if args.fail_fast:
                            raise
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  ERROR: {exc}", file=sys.stderr)
            if args.fail_fast:
                raise
        finally:
            if cube_surface is not None:
                cube_surface.dataset.close()
            if cube_isobaric is not None:
                cube_isobaric.dataset.close()
            if cube_humidity is not None:
                cube_humidity.dataset.close()

    if skipped_surface_decode:
        print(
            f"Skipped surface subset for {skipped_surface_decode} file(s).",
            file=sys.stderr,
        )
    if skipped_isobaric_decode:
        print(
            f"Skipped isobaric subset for {skipped_isobaric_decode} file(s).",
            file=sys.stderr,
        )
    if skipped_humidity_decode:
        print(
            f"Skipped humidity subset for {skipped_humidity_decode} file(s).",
            file=sys.stderr,
        )

    if failures:
        print(f"Completed with {failures} failure(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
