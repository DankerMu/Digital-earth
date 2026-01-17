from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

WEB_MERCATOR_MAX_LAT: Final[float] = 85.05112878


def clamp_lat(lat: float) -> float:
    return max(-WEB_MERCATOR_MAX_LAT, min(WEB_MERCATOR_MAX_LAT, lat))


def lon_to_tile_x(lon: float, zoom: int) -> int:
    n = 2**zoom
    x = int(math.floor((lon + 180.0) / 360.0 * n))
    return max(0, min(n - 1, x))


def lat_to_tile_y(lat: float, zoom: int) -> int:
    n = 2**zoom
    lat = clamp_lat(lat)
    lat_rad = math.radians(lat)
    y = int(math.floor((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n))
    return max(0, min(n - 1, y))


def tile_x_to_lon(x: float, zoom: int) -> float:
    n = 2**zoom
    return x / n * 360.0 - 180.0


def tile_y_to_lat(y: float, zoom: int) -> float:
    n = 2**zoom
    lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n)))
    return math.degrees(lat_rad)


@dataclass(frozen=True)
class TileBounds:
    west: float
    south: float
    east: float
    north: float


def tile_bounds(zoom: int, x: int, y: int) -> TileBounds:
    west = tile_x_to_lon(x, zoom)
    east = tile_x_to_lon(x + 1, zoom)
    north = tile_y_to_lat(y, zoom)
    south = tile_y_to_lat(y + 1, zoom)
    return TileBounds(west=west, south=south, east=east, north=north)
