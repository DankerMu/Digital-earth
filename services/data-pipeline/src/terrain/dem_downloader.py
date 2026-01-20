from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Literal, Optional

import httpx
import numpy as np

from .tile_pyramid import GeoRect

CopernicusDemDataset = Literal["glo30", "glo90"]


@dataclass(frozen=True)
class CopernicusDemTile:
    """Copernicus DEM 1x1-degree tile anchored at integer (lat, lon)."""

    lat_deg: int
    lon_deg: int

    def __post_init__(self) -> None:
        if not (-90 <= int(self.lat_deg) <= 89):
            raise ValueError(f"Invalid tile lat_deg: {self.lat_deg}")
        if not (-180 <= int(self.lon_deg) <= 179):
            raise ValueError(f"Invalid tile lon_deg: {self.lon_deg}")


def _copernicus_item_id(tile: CopernicusDemTile, *, dataset: CopernicusDemDataset) -> str:
    cog_tag = {"glo30": "10", "glo90": "30"}[dataset]

    lat_prefix = "N" if tile.lat_deg >= 0 else "S"
    lon_prefix = "E" if tile.lon_deg >= 0 else "W"
    lat_abs = abs(int(tile.lat_deg))
    lon_abs = abs(int(tile.lon_deg))
    return (
        f"Copernicus_DSM_COG_{cog_tag}_"
        f"{lat_prefix}{lat_abs:02d}_00_"
        f"{lon_prefix}{lon_abs:03d}_00"
    )


def iter_copernicus_tiles_for_rectangle(rect: GeoRect) -> Iterator[CopernicusDemTile]:
    """Yield 1°x1° Copernicus DEM tiles intersecting a rectangle."""

    west = float(rect.west)
    south = float(rect.south)
    east = math.nextafter(float(rect.east), -math.inf)
    north = math.nextafter(float(rect.north), -math.inf)

    lon_min = math.floor(west)
    lon_max = math.floor(east)
    lat_min = math.floor(south)
    lat_max = math.floor(north)

    for lat in range(int(lat_min), int(lat_max) + 1):
        for lon in range(int(lon_min), int(lon_max) + 1):
            yield CopernicusDemTile(lat_deg=lat, lon_deg=lon)


@dataclass(frozen=True)
class CopernicusStacClient:
    dataset: CopernicusDemDataset
    timeout_s: float = 60.0

    def _stac_base_url(self) -> str:
        return {
            "glo30": "https://copernicus-dem-30m-stac.s3.amazonaws.com",
            "glo90": "https://copernicus-dem-90m-stac.s3.amazonaws.com",
        }[self.dataset]

    def item_url(self, tile: CopernicusDemTile) -> str:
        item_id = _copernicus_item_id(tile, dataset=self.dataset)
        return f"{self._stac_base_url()}/items/{item_id}.json"

    def fetch_item(self, tile: CopernicusDemTile) -> dict:
        url = self.item_url(tile)
        with httpx.Client(timeout=self.timeout_s, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()

    def elevation_asset_url(self, tile: CopernicusDemTile) -> str:
        item = self.fetch_item(tile)
        assets = item.get("assets")
        if not isinstance(assets, dict) or "elevation" not in assets:
            raise ValueError(f"Missing elevation asset in STAC item: {tile}")
        elevation = assets["elevation"]
        if not isinstance(elevation, dict) or not isinstance(elevation.get("href"), str):
            raise ValueError(f"Invalid elevation asset in STAC item: {tile}")
        return str(elevation["href"])

    def download_elevation_geotiff(self, tile: CopernicusDemTile, *, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        item_id = _copernicus_item_id(tile, dataset=self.dataset)
        dest = out_dir / f"{item_id}_DEM.tif"
        if dest.exists() and dest.stat().st_size > 0:
            return dest

        url = self.elevation_asset_url(tile)
        with httpx.Client(timeout=self.timeout_s, follow_redirects=True) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with dest.open("wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
        return dest


@dataclass(frozen=True)
class DemGrid:
    """A regularly-spaced DEM grid in EPSG:4326 degrees.

    Heights are stored as meters in a (ny, nx) array with:
    - axis 0: south -> north (increasing latitude)
    - axis 1: west -> east (increasing longitude)
    """

    west: float
    south: float
    east: float
    north: float
    heights_m: np.ndarray
    nodata: Optional[float] = None

    def __post_init__(self) -> None:
        if self.heights_m.ndim != 2:
            raise ValueError("heights_m must be a 2D array")
        if not (self.west < self.east and self.south < self.north):
            raise ValueError("Invalid bounds for DemGrid")
        if self.heights_m.shape[0] < 2 or self.heights_m.shape[1] < 2:
            raise ValueError("heights_m must be at least 2x2")

    @property
    def shape(self) -> tuple[int, int]:
        return int(self.heights_m.shape[0]), int(self.heights_m.shape[1])

    def contains(self, lon: float, lat: float) -> bool:
        return (self.west <= lon <= self.east) and (self.south <= lat <= self.north)

    def sample(
        self, lon: float, lat: float, *, method: Literal["nearest", "bilinear"] = "bilinear", fill_value: float = 0.0
    ) -> float:
        if not self.contains(lon, lat):
            return float(fill_value)

        ny, nx = self.shape
        x = (float(lon) - self.west) / (self.east - self.west) * (nx - 1)
        y = (float(lat) - self.south) / (self.north - self.south) * (ny - 1)

        if method == "nearest":
            xi = int(round(x))
            yi = int(round(y))
            xi = max(0, min(nx - 1, xi))
            yi = max(0, min(ny - 1, yi))
            value = float(self.heights_m[yi, xi])
            if not np.isfinite(value):
                return float(fill_value)
            return value

        if method != "bilinear":
            raise ValueError(f"Unknown sampling method: {method}")

        x0 = int(math.floor(x))
        x1 = min(x0 + 1, nx - 1)
        y0 = int(math.floor(y))
        y1 = min(y0 + 1, ny - 1)

        dx = x - x0
        dy = y - y0

        q00 = float(self.heights_m[y0, x0])
        q10 = float(self.heights_m[y0, x1])
        q01 = float(self.heights_m[y1, x0])
        q11 = float(self.heights_m[y1, x1])

        if not all(np.isfinite(v) for v in (q00, q10, q01, q11)):
            return float(fill_value)

        v0 = q00 * (1.0 - dx) + q10 * dx
        v1 = q01 * (1.0 - dx) + q11 * dx
        return v0 * (1.0 - dy) + v1 * dy

    def sample_grid(
        self, rect: GeoRect, *, grid_size: int, method: Literal["nearest", "bilinear"] = "bilinear", fill_value: float = 0.0
    ) -> np.ndarray:
        if grid_size < 2:
            raise ValueError("grid_size must be >= 2")
        lons = np.linspace(rect.west, rect.east, grid_size, dtype=np.float64)
        lats = np.linspace(rect.south, rect.north, grid_size, dtype=np.float64)
        out = np.full((grid_size, grid_size), float(fill_value), dtype=np.float32)
        for j, lat in enumerate(lats):
            for i, lon in enumerate(lons):
                out[j, i] = float(self.sample(float(lon), float(lat), method=method, fill_value=fill_value))
        return out

    @staticmethod
    def from_geotiff(path: Path) -> "DemGrid":
        """Load a GeoTIFF using rasterio (optional dependency)."""

        try:
            import rasterio  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "rasterio is required to load GeoTIFF DEMs. Install it in the data-pipeline env."
            ) from exc

        with rasterio.open(path) as ds:
            if ds.count < 1:
                raise ValueError(f"No raster bands found: {path}")
            if ds.crs is None or ds.crs.to_epsg() != 4326:
                raise ValueError(f"Expected EPSG:4326 DEM, got {ds.crs}: {path}")
            arr = ds.read(1).astype(np.float32)
            nodata = ds.nodata
            if nodata is not None:
                arr = np.where(arr == float(nodata), np.nan, arr)

            # rasterio arrays are north->south; flip to south->north.
            if ds.transform.e < 0:
                arr = np.flipud(arr)

            bounds = ds.bounds
            return DemGrid(
                west=float(bounds.left),
                south=float(bounds.bottom),
                east=float(bounds.right),
                north=float(bounds.top),
                heights_m=arr,
                nodata=float(nodata) if nodata is not None else None,
            )


@dataclass(frozen=True)
class DemMosaic:
    """A simple DEM mosaic that dispatches samples to underlying 1° tiles."""

    tiles: dict[tuple[int, int], DemGrid]

    def sample(self, lon: float, lat: float, *, fill_value: float = 0.0) -> float:
        lon_f = float(lon)
        lat_f = float(lat)

        lon_key = int(math.floor(lon_f))
        lat_key = int(math.floor(lat_f))

        # Fast path: point falls within the expected 1° tile.
        candidate = self.tiles.get((lat_key, lon_key))
        if candidate is not None and candidate.contains(lon_f, lat_f):
            return candidate.sample(lon_f, lat_f, fill_value=fill_value)

        # Boundary fallback: try immediate west/south neighbors (handles exact-degree edges).
        for dy, dx in ((0, -1), (-1, 0), (-1, -1)):
            neighbor = self.tiles.get((lat_key + dy, lon_key + dx))
            if neighbor is not None and neighbor.contains(lon_f, lat_f):
                return neighbor.sample(lon_f, lat_f, fill_value=fill_value)

        # Conservative fallback: scan all tiles (mosaic sizes are small in this PoC).
        for grid in self.tiles.values():
            if grid.contains(lon_f, lat_f):
                return grid.sample(lon_f, lat_f, fill_value=fill_value)

        return float(fill_value)

    def sample_grid(self, rect: GeoRect, *, grid_size: int, fill_value: float = 0.0) -> np.ndarray:
        if grid_size < 2:
            raise ValueError("grid_size must be >= 2")
        lons = np.linspace(rect.west, rect.east, grid_size, dtype=np.float64)
        lats = np.linspace(rect.south, rect.north, grid_size, dtype=np.float64)
        out = np.full((grid_size, grid_size), float(fill_value), dtype=np.float32)
        for j, lat in enumerate(lats):
            for i, lon in enumerate(lons):
                out[j, i] = float(self.sample(float(lon), float(lat), fill_value=fill_value))
        return out

    @staticmethod
    def from_geotiffs(paths: Iterable[Path]) -> "DemMosaic":
        tiles: dict[tuple[int, int], DemGrid] = {}
        for path in paths:
            grid = DemGrid.from_geotiff(path)
            # Anchor to integer degrees (tile SW corner).
            lat_key = int(math.floor(grid.south))
            lon_key = int(math.floor(grid.west))
            tiles[(lat_key, lon_key)] = grid
        return DemMosaic(tiles=tiles)
