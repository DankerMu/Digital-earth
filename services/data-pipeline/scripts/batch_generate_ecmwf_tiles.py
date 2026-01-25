from __future__ import annotations

import argparse
import glob
import json
import sys
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


DEFAULT_INPUT_GLOB = "Data/EC-forecast/EC预报/W_NAFP_C_ECMF_*.grib"


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
        prog="python services/data-pipeline/scripts/batch_generate_ecmwf_tiles.py",
        description="Batch-generate ECMWF raster tiles from local GRIB files.",
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
        required=True,
        help="Directory to write tiles into.",
    )
    parser.add_argument(
        "--valid-time",
        default=None,
        help="Optional ISO8601 timestamp; defaults to the first time in each GRIB.",
    )
    parser.add_argument("--level", default="sfc", help="Pressure level or 'sfc'.")
    parser.add_argument("--min-zoom", type=int, default=0)
    parser.add_argument("--max-zoom", type=int, default=0)
    parser.add_argument("--tile-size", type=int, default=None)
    parser.add_argument(
        "--format",
        dest="formats",
        action="append",
        default=[],
        help="Tile format(s): png, webp. May be repeated or comma-separated.",
    )
    parser.add_argument(
        "--temperature",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate temperature tiles (default: enabled).",
    )
    parser.add_argument(
        "--cloud",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate total cloud cover tiles (default: enabled).",
    )
    parser.add_argument(
        "--precipitation",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate precipitation amount tiles (default: enabled).",
    )
    parser.add_argument(
        "--wind-speed",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Generate optional wind speed background tiles (default: disabled).",
    )
    parser.add_argument(
        "--wind-speed-opacity",
        type=float,
        default=0.35,
        help="Wind speed tile opacity in [0, 1] (default: 0.35).",
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

    failures = 0
    skipped_decode = 0
    for idx, path in enumerate(paths, start=1):
        print(f"[{idx}/{len(paths)}] {path}")
        cube = None
        try:
            try:
                cube = decode_grib(path)
            except DataCubeDecodeError as exc:
                skipped_decode += 1
                print(f"  WARNING: {exc}", file=sys.stderr)
                if args.fail_fast:
                    raise
                continue

            results = generate_ecmwf_raster_tiles(
                cube,
                output_dir,
                valid_time=args.valid_time,
                level=args.level,
                temperature=bool(args.temperature),
                cloud=bool(args.cloud),
                precipitation=bool(args.precipitation),
                wind_speed=bool(args.wind_speed),
                wind_speed_opacity=float(args.wind_speed_opacity),
                min_zoom=int(args.min_zoom),
                max_zoom=int(args.max_zoom),
                tile_size=int(args.tile_size) if args.tile_size is not None else None,
                formats=resolved_formats,
            )
            for result in results:
                print(" ", json.dumps(result.__dict__, ensure_ascii=False, default=str))
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  ERROR: {exc}", file=sys.stderr)
            if args.fail_fast:
                raise
        finally:
            if cube is not None:
                cube.dataset.close()

    if skipped_decode:
        print(
            f"Skipped {skipped_decode} file(s) that could not be decoded.",
            file=sys.stderr,
        )

    if failures:
        print(f"Completed with {failures} failure(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
