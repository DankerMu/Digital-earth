from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Iterator


@dataclass(frozen=True)
class GeoRect:
    """A geographic rectangle in degrees in EPSG:4326."""

    west: float
    south: float
    east: float
    north: float

    def __post_init__(self) -> None:
        if not (-180.0 <= float(self.west) <= 180.0):
            raise ValueError(f"west out of range: {self.west}")
        if not (-180.0 <= float(self.east) <= 180.0):
            raise ValueError(f"east out of range: {self.east}")
        if not (-90.0 <= float(self.south) <= 90.0):
            raise ValueError(f"south out of range: {self.south}")
        if not (-90.0 <= float(self.north) <= 90.0):
            raise ValueError(f"north out of range: {self.north}")
        if not (self.west < self.east):
            raise ValueError(f"Expected west < east, got {self.west} >= {self.east}")
        if not (self.south < self.north):
            raise ValueError(
                f"Expected south < north, got {self.south} >= {self.north}"
            )


@dataclass(frozen=True)
class TileID:
    """Cesium quantized-mesh tile coordinates (EPSG:4326, TMS scheme)."""

    z: int
    x: int
    y: int

    def __post_init__(self) -> None:
        if self.z < 0:
            raise ValueError(f"Invalid zoom: {self.z}")
        max_x = num_tiles_x(self.z) - 1
        max_y = num_tiles_y(self.z) - 1
        if not (0 <= self.x <= max_x):
            raise ValueError(f"x out of range at z={self.z}: {self.x}")
        if not (0 <= self.y <= max_y):
            raise ValueError(f"y out of range at z={self.z}: {self.y}")


def num_tiles_x(z: int) -> int:
    """Number of tiles in X at zoom z for EPSG:4326 quantized-mesh."""

    if z < 0:
        raise ValueError(f"Invalid zoom: {z}")
    # Quantized-mesh EPSG:4326 uses 2 tiles at level 0 in X.
    return 1 << (z + 1)


def num_tiles_y(z: int) -> int:
    """Number of tiles in Y at zoom z for EPSG:4326 quantized-mesh."""

    if z < 0:
        raise ValueError(f"Invalid zoom: {z}")
    return 1 << z


def tile_bounds_deg(tile: TileID) -> GeoRect:
    """Return the (west, south, east, north) bounds in degrees for a TileID."""

    nx = num_tiles_x(tile.z)
    ny = num_tiles_y(tile.z)

    tile_width = 360.0 / nx
    tile_height = 180.0 / ny

    west = -180.0 + tile.x * tile_width
    east = west + tile_width
    south = -90.0 + tile.y * tile_height
    north = south + tile_height
    return GeoRect(west=west, south=south, east=east, north=north)


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def tile_range_for_rectangle(rect: GeoRect, z: int) -> tuple[int, int, int, int]:
    """Return (x_min, x_max, y_min, y_max) tile range covering rect at zoom z.

    Rectangle bounds are treated as [west, east) and [south, north) to avoid
    double-counting when the rectangle aligns with tile boundaries.
    """

    if z < 0:
        raise ValueError(f"Invalid zoom: {z}")

    nx = num_tiles_x(z)
    ny = num_tiles_y(z)

    west = float(rect.west)
    south = float(rect.south)
    east = float(rect.east)
    north = float(rect.north)

    x_min = math.floor(((west + 180.0) / 360.0) * nx)
    # Treat east/north as exclusive bounds in a numerically robust way.
    x_max = math.ceil(((east + 180.0) / 360.0) * nx) - 1
    y_min = math.floor(((south + 90.0) / 180.0) * ny)
    y_max = math.ceil(((north + 90.0) / 180.0) * ny) - 1

    x_min = _clamp_int(x_min, 0, nx - 1)
    x_max = _clamp_int(x_max, 0, nx - 1)
    y_min = _clamp_int(y_min, 0, ny - 1)
    y_max = _clamp_int(y_max, 0, ny - 1)

    if x_min > x_max or y_min > y_max:
        raise ValueError(f"Rectangle does not intersect tiling scheme at z={z}: {rect}")

    return x_min, x_max, y_min, y_max


def tiles_for_rectangle(rect: GeoRect, z: int) -> Iterator[TileID]:
    """Iterate tiles covering rect at zoom z (TMS y origin at south)."""

    x_min, x_max, y_min, y_max = tile_range_for_rectangle(rect, z)
    for x in range(x_min, x_max + 1):
        for y in range(y_min, y_max + 1):
            yield TileID(z=z, x=x, y=y)


def iter_tile_pyramid(
    rect: GeoRect, *, min_zoom: int, max_zoom: int
) -> Iterator[TileID]:
    """Iterate all tiles in a zoom range that intersect a rectangle."""

    if min_zoom < 0 or max_zoom < 0:
        raise ValueError("Zoom levels must be >= 0")
    if min_zoom > max_zoom:
        raise ValueError(f"Expected min_zoom <= max_zoom, got {min_zoom} > {max_zoom}")

    for z in range(min_zoom, max_zoom + 1):
        yield from tiles_for_rectangle(rect, z)


def available_ranges(
    rect: GeoRect, *, min_zoom: int, max_zoom: int
) -> list[list[dict[str, int]]]:
    """Build Cesium `layer.json` availability ranges for a rectangle.

    Output format matches Cesium's `available` metadata:
    `available[z] = [{startX, startY, endX, endY}, ...]`
    """

    levels: list[list[dict[str, int]]] = []
    for z in range(0, max_zoom + 1):
        if z < min_zoom:
            levels.append([])
            continue
        x_min, x_max, y_min, y_max = tile_range_for_rectangle(rect, z)
        levels.append(
            [
                {
                    "startX": x_min,
                    "startY": y_min,
                    "endX": x_max,
                    "endY": y_max,
                }
            ]
        )
    return levels


def iter_tiles_in_ranges(
    ranges: Iterable[tuple[int, int, int, int]], z: int
) -> Iterator[TileID]:
    """Iterate tiles for precomputed ranges (x_min, x_max, y_min, y_max)."""

    for x_min, x_max, y_min, y_max in ranges:
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                yield TileID(z=z, x=x, y=y)
