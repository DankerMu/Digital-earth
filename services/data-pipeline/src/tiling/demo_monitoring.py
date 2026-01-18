from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Iterable, Sequence

import numpy as np
import xarray as xr

from tiling.cldas_tiles import CLDASTileGenerator, TileGenerationResult

DEFAULT_DEMO_SEED: Final[int] = 870056
DEFAULT_TIME_ISO: Final[str] = "2026-01-01T00:00:00Z"


@dataclass(frozen=True)
class DemoBounds:
    west: float = 110.0
    south: float = 30.0
    east: float = 115.0
    north: float = 35.0

    def validate(self) -> "DemoBounds":
        if not np.isfinite(self.west) or not np.isfinite(self.east):
            raise ValueError("Bounds west/east must be finite")
        if not np.isfinite(self.south) or not np.isfinite(self.north):
            raise ValueError("Bounds south/north must be finite")
        if self.east <= self.west:
            raise ValueError("Bounds east must be > west")
        if self.north <= self.south:
            raise ValueError("Bounds north must be > south")
        return self


def _time_coord_from_iso(time_iso: str) -> np.ndarray:
    normalized = (time_iso or "").strip()
    if normalized == "":
        raise ValueError("time_iso must not be empty")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized).astimezone(timezone.utc)
    return np.array([parsed.strftime("%Y-%m-%dT%H:%M:%S")], dtype="datetime64[s]")


def _axis(start: float, stop: float, step: float) -> np.ndarray:
    if step <= 0:
        raise ValueError("resolution_deg must be > 0")
    values = np.arange(start, stop + step * 0.5, step, dtype=np.float64)
    eps = abs(step) * 1e-6
    return values[values <= stop + eps]


def create_demo_monitoring_dataset(
    *,
    seed: int = DEFAULT_DEMO_SEED,
    time_iso: str = DEFAULT_TIME_ISO,
    bounds: DemoBounds = DemoBounds(),
    resolution_deg: float = 0.05,
) -> xr.Dataset:
    bounds = bounds.validate()
    rng = np.random.default_rng(int(seed))

    lat = _axis(bounds.south, bounds.north, float(resolution_deg))
    lon = _axis(bounds.west, bounds.east, float(resolution_deg))
    lat_grid, lon_grid = np.meshgrid(lat, lon, indexing="ij")

    center_lat = (bounds.south + bounds.north) / 2.0
    center_lon = (bounds.west + bounds.east) / 2.0
    span_lat = bounds.north - bounds.south
    span_lon = bounds.east - bounds.west

    snow_sigma_lat = span_lat / 4.0
    snow_sigma_lon = span_lon / 4.0
    snow_core = np.exp(
        -(
            ((lat_grid - center_lat) ** 2) / (2.0 * snow_sigma_lat**2)
            + ((lon_grid - center_lon) ** 2) / (2.0 * snow_sigma_lon**2)
        )
    )
    snow_noise = rng.normal(0.0, 0.08, size=snow_core.shape)
    snow_cm = 85.0 * snow_core + 12.0 * snow_noise
    snow_cm = np.clip(snow_cm, 0.0, 120.0).astype(np.float32, copy=False)
    snow_cm = np.where(snow_cm < 0.5, np.nan, snow_cm).astype(np.float32, copy=False)

    wave_x = np.sin((lon_grid - bounds.west) / span_lon * np.pi * 2.0)
    wave_y = np.cos((lat_grid - bounds.south) / span_lat * np.pi)
    precip_band = np.exp(-(((lat_grid - center_lat) / (span_lat / 5.0)) ** 2))
    precip_base = (0.55 + 0.45 * wave_x) * (0.6 + 0.4 * wave_y) * precip_band
    precip_mm = 95.0 * precip_base + 6.0 * rng.random(size=precip_base.shape)
    precip_mm = np.clip(precip_mm, 0.0, 120.0).astype(np.float32, copy=False)
    precip_mm = np.where(precip_mm < 0.5, np.nan, precip_mm).astype(
        np.float32, copy=False
    )

    time = _time_coord_from_iso(time_iso)
    ds = xr.Dataset(
        data_vars={
            "SD": xr.DataArray(snow_cm[None, ...], dims=["time", "lat", "lon"]),
            "PRE": xr.DataArray(precip_mm[None, ...], dims=["time", "lat", "lon"]),
        },
        coords={"time": time, "lat": lat, "lon": lon},
    )
    ds.attrs["time"] = DEFAULT_TIME_ISO if time_iso.strip() == "" else time_iso
    ds.attrs["demo_seed"] = int(seed)
    ds.attrs["demo_bounds"] = {
        "west": bounds.west,
        "south": bounds.south,
        "east": bounds.east,
        "north": bounds.north,
        "resolution_deg": float(resolution_deg),
    }
    return ds


def generate_demo_monitoring_tiles(
    output_dir: str | Path,
    *,
    seed: int = DEFAULT_DEMO_SEED,
    time_iso: str = DEFAULT_TIME_ISO,
    bounds: DemoBounds = DemoBounds(),
    resolution_deg: float = 0.05,
    min_zoom: int = 6,
    max_zoom: int = 8,
    tile_size: int = 256,
    time_key: str | None = None,
) -> list[TileGenerationResult]:
    ds = create_demo_monitoring_dataset(
        seed=seed, time_iso=time_iso, bounds=bounds, resolution_deg=resolution_deg
    )
    try:
        layers: Sequence[tuple[str, str]] = (
            ("SD", "cldas/sd"),
            ("PRE", "cldas/pre"),
        )
        results: list[TileGenerationResult] = []
        for variable, layer in layers:
            generator = CLDASTileGenerator(ds, variable=variable, layer=layer)
            results.append(
                generator.generate(
                    output_dir,
                    min_zoom=min_zoom,
                    max_zoom=max_zoom,
                    tile_size=tile_size,
                    time_key=time_key,
                )
            )
        return results
    finally:
        ds.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tiling.demo_monitoring",
        description="Generate deterministic demo monitoring tiles (snow depth / precipitation).",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_DEMO_SEED)
    parser.add_argument("--time-iso", default=DEFAULT_TIME_ISO)

    parser.add_argument("--west", type=float, default=DemoBounds.west)
    parser.add_argument("--south", type=float, default=DemoBounds.south)
    parser.add_argument("--east", type=float, default=DemoBounds.east)
    parser.add_argument("--north", type=float, default=DemoBounds.north)
    parser.add_argument("--resolution-deg", type=float, default=0.05)

    parser.add_argument("--min-zoom", type=int, default=6)
    parser.add_argument("--max-zoom", type=int, default=8)
    parser.add_argument("--tile-size", type=int, default=256)
    parser.add_argument("--time-key", default=None)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    bounds = DemoBounds(
        west=float(args.west),
        south=float(args.south),
        east=float(args.east),
        north=float(args.north),
    )
    results = generate_demo_monitoring_tiles(
        Path(args.output_dir),
        seed=int(args.seed),
        time_iso=str(args.time_iso),
        bounds=bounds,
        resolution_deg=float(args.resolution_deg),
        min_zoom=int(args.min_zoom),
        max_zoom=int(args.max_zoom),
        tile_size=int(args.tile_size),
        time_key=str(args.time_key) if args.time_key is not None else None,
    )
    for result in results:
        print(
            json.dumps(
                {
                    "layer": result.layer,
                    "variable": result.variable,
                    "time": result.time,
                    "output_dir": str(result.output_dir),
                    "min_zoom": result.min_zoom,
                    "max_zoom": result.max_zoom,
                    "tiles_written": result.tiles_written,
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
