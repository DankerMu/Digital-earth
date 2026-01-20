from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .dem_downloader import DemMosaic
from .mesh_generator import QuantizedMeshOptions, encode_quantized_mesh
from .tile_pyramid import (
    GeoRect,
    available_ranges,
    tile_bounds_deg,
    tiles_for_rectangle,
)


@dataclass(frozen=True)
class TilesetStats:
    tile_count: int
    total_bytes: int
    elapsed_s: float

    @property
    def avg_bytes_per_tile(self) -> float:
        return self.total_bytes / max(1, self.tile_count)

    @property
    def avg_tiles_per_s(self) -> float:
        return self.tile_count / max(1e-9, self.elapsed_s)


def build_layer_json(
    *,
    rect: GeoRect,
    min_zoom: int,
    max_zoom: int,
    dataset: str,
    gzip_payload: bool,
    tiles_template: str = "{z}/{x}/{y}.terrain",
) -> dict[str, Any]:
    attribution = (
        "Copernicus DEM (non-commercial PoC). "
        "Includes material provided under COPERNICUS by the European Union and ESA; all rights reserved."
    )
    return {
        "tilejson": "2.1.0",
        "format": "quantized-mesh-1.0",
        "version": "1.0.0",
        "scheme": "tms",
        "projection": "EPSG:4326",
        "minzoom": int(min_zoom),
        "maxzoom": int(max_zoom),
        "bounds": [rect.west, rect.south, rect.east, rect.north],
        "tiles": [tiles_template],
        "attribution": attribution,
        "available": available_ranges(rect, min_zoom=min_zoom, max_zoom=max_zoom),
        "extensions": [],
        "metadata": {
            "dataset": dataset,
            "gzip_payload": bool(gzip_payload),
        },
    }


def write_layer_json(path: Path, *, layer: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(layer, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def generate_tileset(
    *,
    dem: DemMosaic,
    rect: GeoRect,
    out_dir: Path,
    min_zoom: int,
    max_zoom: int,
    grid_size: int,
    gzip_payload: bool,
) -> TilesetStats:
    if min_zoom < 0 or max_zoom < 0:
        raise ValueError("min_zoom/max_zoom must be >= 0")
    if min_zoom > max_zoom:
        raise ValueError("min_zoom must be <= max_zoom")
    if grid_size < 2:
        raise ValueError("grid_size must be >= 2")

    out_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    options = QuantizedMeshOptions(gzip=bool(gzip_payload))

    total_bytes = 0
    tile_count = 0
    for z in range(min_zoom, max_zoom + 1):
        for tile in tiles_for_rectangle(rect, z):
            tile_rect = tile_bounds_deg(tile)
            heights = dem.sample_grid(tile_rect, grid_size=grid_size, fill_value=0.0)
            payload = encode_quantized_mesh(tile_rect, heights, options=options)

            path = out_dir / str(tile.z) / str(tile.x) / f"{tile.y}.terrain"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)

            total_bytes += len(payload)
            tile_count += 1

    elapsed_s = time.perf_counter() - started
    return TilesetStats(
        tile_count=tile_count, total_bytes=total_bytes, elapsed_s=elapsed_s
    )
