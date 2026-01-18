from __future__ import annotations

from dataclasses import dataclass
from typing import Final

LON_MIN: Final[float] = -180.0
LON_MAX: Final[float] = 180.0
LAT_MIN: Final[float] = -90.0
LAT_MAX: Final[float] = 90.0


def clamp_lon(lon: float) -> float:
    return max(LON_MIN, min(LON_MAX, lon))


def clamp_lat(lat: float) -> float:
    return max(LAT_MIN, min(LAT_MAX, lat))


def lon_to_tile_x(lon: float, zoom: int) -> int:
    n = 2**zoom
    lon = clamp_lon(lon)
    x = int(((lon - LON_MIN) / (LON_MAX - LON_MIN)) * n)
    return max(0, min(n - 1, x))


def lat_to_tile_y(lat: float, zoom: int) -> int:
    n = 2**zoom
    lat = clamp_lat(lat)
    y = int(((LAT_MAX - lat) / (LAT_MAX - LAT_MIN)) * n)
    return max(0, min(n - 1, y))


def tile_x_to_lon(x: float, zoom: int) -> float:
    n = 2**zoom
    return LON_MIN + (x / n) * (LON_MAX - LON_MIN)


def tile_y_to_lat(y: float, zoom: int) -> float:
    n = 2**zoom
    return LAT_MAX - (y / n) * (LAT_MAX - LAT_MIN)


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
