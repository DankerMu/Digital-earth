from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Final, Iterable, Sequence

import numpy as np
import xarray as xr

from datacube.core import DataCube
from tiles.wind_speed_tiles import DEFAULT_WIND_SPEED_OPACITY, WindSpeedTileGenerator
from tiling.bias_tiles import (
    DEFAULT_BIAS_FORECAST_VARIABLE,
    DEFAULT_BIAS_LAYER,
    DEFAULT_BIAS_LEGEND_FILENAME,
    DEFAULT_BIAS_OBSERVATION_VARIABLE,
    BiasTileGenerator,
)
from tiling.precip_amount_tiles import PrecipAmountTileGenerator
from tiling.tcc_tiles import TccTileGenerator
from tiling.temperature_tiles import TemperatureTileGenerator


DEFAULT_TILE_FORMATS: Final[tuple[str, ...]] = ("png", "webp")


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


def _default_valid_time(cube: DataCube) -> object:
    ds = cube.dataset
    if "time" not in ds.coords:
        raise ValueError("datacube missing required coordinate: time")
    values = np.asarray(ds["time"].values)
    if values.size == 0:
        raise ValueError("datacube time coordinate is empty")
    return values[0]


def _load_observation_dataset(
    path: str | Path, *, engine: str | None = None
) -> xr.Dataset:
    src = Path(path)
    try:
        with xr.open_dataset(
            src,
            engine=engine,
            decode_cf=True,
            mask_and_scale=True,
        ) as ds:
            ds.load()
            return ds
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Observation dataset not found: {src}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Failed to open observation dataset: {src}") from exc


def generate_ecmwf_raster_tiles(
    cube: DataCube,
    output_dir: str | Path,
    *,
    valid_time: object | None = None,
    level: object = "sfc",
    temperature: bool = True,
    cloud: bool = True,
    precipitation: bool = True,
    wind_speed: bool = False,
    wind_speed_opacity: float = DEFAULT_WIND_SPEED_OPACITY,
    min_zoom: int | None = None,
    max_zoom: int | None = None,
    tile_size: int | None = None,
    formats: Sequence[str] = DEFAULT_TILE_FORMATS,
) -> list[object]:
    resolved_valid_time = (
        _default_valid_time(cube) if valid_time is None else valid_time
    )
    resolved_formats = _parse_formats(formats)
    if not resolved_formats:
        raise ValueError("At least one tile format must be specified")

    results: list[object] = []
    output_dir = Path(output_dir)

    if temperature:
        results.append(
            TemperatureTileGenerator(cube).generate(
                output_dir,
                valid_time=resolved_valid_time,
                level=level,
                min_zoom=min_zoom,
                max_zoom=max_zoom,
                tile_size=tile_size,
                formats=resolved_formats,
            )
        )

    if cloud:
        results.append(
            TccTileGenerator(cube).generate(
                output_dir,
                valid_time=resolved_valid_time,
                level="sfc",
                min_zoom=min_zoom,
                max_zoom=max_zoom,
                tile_size=tile_size,
                formats=resolved_formats,
            )
        )

    if precipitation:
        results.append(
            PrecipAmountTileGenerator(cube).generate(
                output_dir,
                valid_time=resolved_valid_time,
                level=level,
                min_zoom=min_zoom,
                max_zoom=max_zoom,
                tile_size=tile_size,
                formats=resolved_formats,
            )
        )

    if wind_speed:
        results.append(
            WindSpeedTileGenerator(cube, opacity=wind_speed_opacity).generate(
                output_dir,
                valid_time=resolved_valid_time,
                level=level,
                min_zoom=min_zoom,
                max_zoom=max_zoom,
                tile_size=tile_size,
                formats=resolved_formats,
            )
        )

    if not results:
        raise ValueError("No tile layers selected")
    return results


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tiles",
        description=(
            "Generate ECMWF raster tiles (temperature/cloud/precipitation, optional wind speed) "
            "and optional observation-vs-forecast bias tiles."
        ),
    )
    parser.add_argument(
        "--datacube", required=True, help="Path to a NetCDF/Zarr DataCube"
    )
    parser.add_argument(
        "--output-dir", required=True, help="Directory to write tiles into"
    )

    parser.add_argument(
        "--valid-time", default=None, help="ISO8601 timestamp (defaults to first time)"
    )
    parser.add_argument(
        "--level", default="sfc", help="Pressure level or 'sfc' (default: sfc)"
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
        "--temperature",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate temperature tiles (default: enabled)",
    )
    parser.add_argument(
        "--cloud",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate total cloud cover tiles (default: enabled)",
    )
    parser.add_argument(
        "--precipitation",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate precipitation amount tiles (default: enabled)",
    )
    parser.add_argument(
        "--wind-speed",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Generate optional wind speed background tiles (default: disabled)",
    )
    parser.add_argument(
        "--wind-speed-opacity",
        type=float,
        default=DEFAULT_WIND_SPEED_OPACITY,
        help="Wind speed tile opacity in [0, 1] (default: 0.35)",
    )

    parser.add_argument(
        "--bias",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Generate observation-vs-forecast bias tiles (default: disabled)",
    )
    parser.add_argument(
        "--bias-observation",
        default=None,
        help="Path to an observation NetCDF dataset (required when --bias)",
    )
    parser.add_argument(
        "--bias-mode",
        choices=("difference", "relative_error"),
        default="difference",
        help="Bias mode: difference (forecast-observation) or relative_error (%%) (default: difference)",
    )
    parser.add_argument(
        "--bias-layer",
        default=DEFAULT_BIAS_LAYER,
        help=f"Output layer name for bias tiles (default: {DEFAULT_BIAS_LAYER})",
    )
    parser.add_argument(
        "--bias-forecast-variable",
        default=DEFAULT_BIAS_FORECAST_VARIABLE,
        help=f"Forecast variable name for bias computation (default: {DEFAULT_BIAS_FORECAST_VARIABLE})",
    )
    parser.add_argument(
        "--bias-observation-variable",
        default=DEFAULT_BIAS_OBSERVATION_VARIABLE,
        help=f"Observation variable name for bias computation (default: {DEFAULT_BIAS_OBSERVATION_VARIABLE})",
    )
    parser.add_argument(
        "--bias-legend",
        default=DEFAULT_BIAS_LEGEND_FILENAME,
        help=f"Bias legend filename inside config dir (default: {DEFAULT_BIAS_LEGEND_FILENAME})",
    )
    parser.add_argument(
        "--bias-engine",
        default=None,
        help="Optional xarray engine for opening the observation dataset (e.g., netcdf4, h5netcdf)",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    cube = DataCube.open(Path(args.datacube))
    try:
        formats = _parse_formats(tuple(args.formats)) or DEFAULT_TILE_FORMATS
        resolved_valid_time = (
            _default_valid_time(cube) if args.valid_time is None else args.valid_time
        )

        results: list[object] = []

        wants_ecmwf_layers = any(
            (
                bool(args.temperature),
                bool(args.cloud),
                bool(args.precipitation),
                bool(args.wind_speed),
            )
        )
        if wants_ecmwf_layers:
            results.extend(
                generate_ecmwf_raster_tiles(
                    cube,
                    Path(args.output_dir),
                    valid_time=resolved_valid_time,
                    level=args.level,
                    temperature=bool(args.temperature),
                    cloud=bool(args.cloud),
                    precipitation=bool(args.precipitation),
                    wind_speed=bool(args.wind_speed),
                    wind_speed_opacity=float(args.wind_speed_opacity),
                    min_zoom=int(args.min_zoom) if args.min_zoom is not None else None,
                    max_zoom=int(args.max_zoom) if args.max_zoom is not None else None,
                    tile_size=int(args.tile_size)
                    if args.tile_size is not None
                    else None,
                    formats=formats,
                )
            )

        if bool(args.bias):
            if (
                args.bias_observation is None
                or str(args.bias_observation).strip() == ""
            ):
                raise ValueError(
                    "--bias-observation is required when --bias is enabled"
                )

            obs_ds = _load_observation_dataset(
                args.bias_observation, engine=args.bias_engine
            )
            try:
                results.append(
                    BiasTileGenerator(
                        cube,
                        obs_ds,
                        mode=str(args.bias_mode),
                        forecast_variable=str(args.bias_forecast_variable),
                        observation_variable=str(args.bias_observation_variable),
                        layer=str(args.bias_layer),
                        legend_filename=str(args.bias_legend),
                    ).generate(
                        Path(args.output_dir),
                        valid_time=resolved_valid_time,
                        level=args.level,
                        min_zoom=int(args.min_zoom)
                        if args.min_zoom is not None
                        else None,
                        max_zoom=int(args.max_zoom)
                        if args.max_zoom is not None
                        else None,
                        tile_size=int(args.tile_size)
                        if args.tile_size is not None
                        else None,
                        formats=formats,
                    )
                )
            finally:
                obs_ds.close()

        if not results:
            raise ValueError("No tile layers selected")
    finally:
        cube.dataset.close()

    for result in results:
        print(json.dumps(result.__dict__, ensure_ascii=False, default=str))
    return 0
