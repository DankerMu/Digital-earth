from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Optional

import numpy as np
import xarray as xr
from PIL import Image

from legend import load_legend
from digital_earth_config import Settings
from local.cldas_loader import load_cldas_dataset
from tiling.config import TilingConfig, get_tiling_config
from tiling.storage import S3UploadConfig, upload_directory_to_s3
from tiling.epsg4326 import TileBounds, lat_to_tile_y, lon_to_tile_x, tile_bounds


class CldasTilingError(RuntimeError):
    pass


_TMP_BLUE: Final[tuple[int, int, int]] = (0x3B, 0x82, 0xF6)
_TMP_WHITE: Final[tuple[int, int, int]] = (0xFF, 0xFF, 0xFF)
_TMP_RED: Final[tuple[int, int, int]] = (0xEF, 0x44, 0x44)

_LAYER_SEGMENT_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_]+$")
_TIME_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9TZ-]+$")


def _validate_layer(value: str) -> str:
    normalized = (value or "").strip().strip("/")
    if normalized == "":
        raise ValueError("layer must not be empty")

    segments = normalized.split("/")
    invalid_segments = [
        segment
        for segment in segments
        if not segment or _LAYER_SEGMENT_RE.fullmatch(segment) is None
    ]
    if invalid_segments:
        raise ValueError("layer contains unsafe characters")
    return "/".join(segments)


def _validate_time_key(value: str) -> str:
    normalized = (value or "").strip()
    if normalized == "":
        raise ValueError("time_key must not be empty")
    if _TIME_KEY_RE.fullmatch(normalized) is None:
        raise ValueError("time_key contains unsafe characters")
    return normalized


def _ensure_relative_to_base(*, base_dir: Path, path: Path, label: str) -> None:
    if not path.is_relative_to(base_dir):
        raise ValueError(f"{label} escapes output_dir")


def _normalize_time_key(time_iso: str) -> str:
    normalized = time_iso.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return time_iso.replace("-", "").replace(":", "")
    parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y%m%dT%H%M%SZ")


def _ensure_ascending_axis(
    coord: np.ndarray, values: np.ndarray, *, axis: int
) -> tuple[np.ndarray, np.ndarray]:
    if coord.ndim != 1:
        raise CldasTilingError("Only 1D coordinates are supported for tiling")
    if coord.size == 0:
        raise CldasTilingError("Coordinate axis must not be empty")

    diffs = np.diff(coord.astype(np.float64, copy=False))
    if np.all(diffs > 0):
        return coord, values
    if np.all(diffs < 0):
        flipped = np.flip(coord, axis=0)
        flipped_values = np.flip(values, axis=axis)
        return flipped, flipped_values

    order = np.argsort(coord)
    sorted_coord = coord[order]
    sorted_values = np.take(values, order, axis=axis)
    return sorted_coord, sorted_values


def _normalize_longitudes(
    lon: np.ndarray, values: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    lon_f = lon.astype(np.float64, copy=False)
    if lon_f.size and np.nanmin(lon_f) >= 0.0 and np.nanmax(lon_f) > 180.0:
        wrapped = ((lon_f + 180.0) % 360.0) - 180.0
        order = np.argsort(wrapped)
        return wrapped[order].astype(lon.dtype, copy=False), values[:, order]
    return lon, values


def _interp_1d_indices(
    coord: np.ndarray, query: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    coord_f = coord.astype(np.float64, copy=False)
    query_f = query.astype(np.float64, copy=False)
    count = int(coord_f.size)
    right = np.searchsorted(coord_f, query_f, side="right").astype(np.int64)
    left = right - 1
    valid = (left >= 0) & (right < count)

    left = np.clip(left, 0, count - 1)
    right = np.clip(right, 0, count - 1)

    denom = coord_f[right] - coord_f[left]
    denom_safe = np.where(denom == 0, 1.0, denom)
    frac = (query_f - coord_f[left]) / denom_safe
    frac = np.clip(frac, 0.0, 1.0)
    frac = np.where(denom == 0, 0.0, frac)
    return left, right, frac, valid


def _bilinear_sample(
    lat: np.ndarray,
    lon: np.ndarray,
    grid: np.ndarray,
    *,
    lat_query: np.ndarray,
    lon_query: np.ndarray,
) -> np.ndarray:
    lat0, lat1, latf, lat_ok = _interp_1d_indices(lat, lat_query)
    lon0, lon1, lonf, lon_ok = _interp_1d_indices(lon, lon_query)

    v00 = grid[np.ix_(lat0, lon0)]
    v01 = grid[np.ix_(lat0, lon1)]
    v10 = grid[np.ix_(lat1, lon0)]
    v11 = grid[np.ix_(lat1, lon1)]

    wy = latf[:, None]
    wx = lonf[None, :]
    out = (
        (1.0 - wy) * (1.0 - wx) * v00
        + (1.0 - wy) * wx * v01
        + wy * (1.0 - wx) * v10
        + wy * wx * v11
    ).astype(np.float32, copy=False)

    mask = lat_ok[:, None] & lon_ok[None, :]
    out = np.where(mask, out, np.nan)
    return out


def temperature_rgba(values: np.ndarray) -> np.ndarray:
    values_f = values.astype(np.float32, copy=False)
    mask = np.isfinite(values_f)
    clipped = np.clip(values_f, -20.0, 40.0)

    rgb = np.zeros((*values_f.shape, 3), dtype=np.float32)
    alpha = np.zeros(values_f.shape, dtype=np.uint8)

    below = clipped <= 0.0
    above = ~below

    t1 = (clipped + 20.0) / 20.0
    t1 = np.clip(t1, 0.0, 1.0)
    t2 = clipped / 40.0
    t2 = np.clip(t2, 0.0, 1.0)

    blue = np.array(_TMP_BLUE, dtype=np.float32)
    white = np.array(_TMP_WHITE, dtype=np.float32)
    red = np.array(_TMP_RED, dtype=np.float32)

    rgb[below] = blue * (1.0 - t1[below, None]) + white * t1[below, None]
    rgb[above] = white * (1.0 - t2[above, None]) + red * t2[above, None]

    alpha[mask] = 255
    rgba = np.zeros((*values_f.shape, 4), dtype=np.uint8)
    rgb = np.where(mask[..., None], rgb, 0.0)
    rgba[..., :3] = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
    rgba[..., 3] = alpha
    return rgba


def _parse_hex_rgb(value: str) -> tuple[int, int, int]:
    normalized = (value or "").strip()
    if not normalized.startswith("#") or len(normalized) != 7:
        raise ValueError(f"Invalid hex color: {value!r}")
    try:
        r = int(normalized[1:3], 16)
        g = int(normalized[3:5], 16)
        b = int(normalized[5:7], 16)
    except ValueError as exc:
        raise ValueError(f"Invalid hex color: {value!r}") from exc
    return r, g, b


def gradient_rgba_from_legend(
    values: np.ndarray, *, legend: dict[str, Any]
) -> np.ndarray:
    if legend.get("type") != "gradient":
        raise ValueError("Only gradient legends are supported for raster tiling")

    stops = legend.get("stops")
    if not isinstance(stops, list) or len(stops) < 2:
        raise ValueError("legend.stops must be a list with at least 2 stops")

    stop_values: list[float] = []
    stop_colors: list[tuple[int, int, int]] = []
    for stop in stops:
        if not isinstance(stop, dict):
            raise ValueError("legend.stops entries must be objects")
        raw_value = stop.get("value")
        raw_color = stop.get("color")
        if not isinstance(raw_value, (int, float)) or not np.isfinite(float(raw_value)):
            raise ValueError("legend stop value must be a finite number")
        if not isinstance(raw_color, str):
            raise ValueError("legend stop color must be a string")
        stop_values.append(float(raw_value))
        stop_colors.append(_parse_hex_rgb(raw_color))

    order = np.argsort(np.asarray(stop_values, dtype=np.float64))
    stop_values_np = np.asarray(stop_values, dtype=np.float32)[order]
    stop_colors_np = np.asarray(stop_colors, dtype=np.float32)[order]
    diffs = np.diff(stop_values_np.astype(np.float64, copy=False))
    if not np.all(diffs > 0):
        raise ValueError("legend stop values must be strictly increasing")

    values_f = values.astype(np.float32, copy=False)
    mask = np.isfinite(values_f)
    clipped = np.clip(values_f, float(stop_values_np[0]), float(stop_values_np[-1]))
    clipped = np.where(mask, clipped, float(stop_values_np[0])).astype(
        np.float32, copy=False
    )

    right = np.searchsorted(stop_values_np, clipped, side="right").astype(np.int64)
    left = np.clip(right - 1, 0, stop_values_np.size - 2)
    right = left + 1

    v0 = stop_values_np[left]
    v1 = stop_values_np[right]
    denom = v1 - v0
    denom_safe = np.where(denom == 0, 1.0, denom)
    frac = (clipped - v0) / denom_safe
    frac = np.clip(frac, 0.0, 1.0).astype(np.float32, copy=False)

    c0 = stop_colors_np[left]
    c1 = stop_colors_np[right]
    rgb = c0 * (1.0 - frac[..., None]) + c1 * frac[..., None]
    rgb = np.where(mask[..., None], rgb, 0.0)

    rgba = np.zeros((*values_f.shape, 4), dtype=np.uint8)
    alpha = np.zeros(values_f.shape, dtype=np.uint8)
    alpha[mask] = 255
    rgba[..., :3] = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
    rgba[..., 3] = alpha
    return rgba


@dataclass(frozen=True)
class TileGenerationResult:
    layer: str
    variable: str
    time: str
    output_dir: Path
    min_zoom: int
    max_zoom: int
    tiles_written: int


class CLDASTileGenerator:
    def __init__(
        self,
        ds: xr.Dataset,
        *,
        variable: str = "TMP",
        time_index: int = 0,
        layer: str = "cldas/tmp",
    ) -> None:
        self._ds = ds
        self._variable = variable
        self._time_index = int(time_index)
        self._layer = _validate_layer(layer)
        self._legend: Optional[dict[str, Any]] = None
        if self._variable.strip() == "":
            raise ValueError("variable must not be empty")

    @classmethod
    def from_netcdf(
        cls,
        source_path: str | Path,
        *,
        variable: str = "TMP",
        time_index: int = 0,
        layer: str = "cldas/tmp",
        engine: Optional[str] = None,
    ) -> "CLDASTileGenerator":
        ds = load_cldas_dataset(source_path, engine=engine)
        return cls(ds, variable=variable, time_index=time_index, layer=layer)

    @property
    def variable(self) -> str:
        return self._variable

    @property
    def layer(self) -> str:
        return self._layer

    def _load_legend(self) -> dict[str, Any]:
        if self._legend is None:
            parts = self._layer.split("/")
            self._legend = load_legend(*parts, "legend.json")
        return self._legend

    def _colorize(self, values: np.ndarray) -> np.ndarray:
        if self._layer == "cldas/tmp":
            return temperature_rgba(values)
        legend = self._load_legend()
        return gradient_rgba_from_legend(values, legend=legend)

    def _extract_grid(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if self._variable not in self._ds.data_vars:
            raise CldasTilingError(
                f"Variable {self._variable!r} not found; available={list(self._ds.data_vars)}"
            )

        da = self._ds[self._variable]
        if "time" in da.dims:
            if da.sizes.get("time", 0) == 0:
                raise CldasTilingError("time dimension is empty")
            if self._time_index < 0 or self._time_index >= int(da.sizes["time"]):
                raise CldasTilingError("time_index is out of range")
            da = da.isel(time=self._time_index)

        if set(da.dims) != {"lat", "lon"}:
            raise CldasTilingError(
                f"Expected data dims {{'lat','lon'}}, got {list(da.dims)}"
            )
        da = da.transpose("lat", "lon")

        lat = np.asarray(self._ds["lat"].values)
        lon = np.asarray(self._ds["lon"].values)
        grid = np.asarray(da.values).astype(np.float32, copy=False)

        lat, grid = _ensure_ascending_axis(lat, grid, axis=0)
        lon, grid = _ensure_ascending_axis(lon, grid, axis=1)
        lon, grid = _normalize_longitudes(lon, grid)

        if lat.size != grid.shape[0] or lon.size != grid.shape[1]:
            raise CldasTilingError("lat/lon coordinates do not match data grid shape")

        return (
            lat.astype(np.float64, copy=False),
            lon.astype(np.float64, copy=False),
            grid,
        )

    def _render_tile_array(
        self,
        *,
        zoom: int,
        x: int,
        y: int,
        tile_size: int,
        lat: np.ndarray,
        lon: np.ndarray,
        grid: np.ndarray,
    ) -> np.ndarray:
        if tile_size <= 0:
            raise ValueError("tile_size must be > 0")

        bounds: TileBounds = tile_bounds(zoom, x, y)

        cols = (np.arange(tile_size, dtype=np.float64) + 0.5) / tile_size
        rows = (np.arange(tile_size, dtype=np.float64) + 0.5) / tile_size

        lon_px = bounds.west + cols * (bounds.east - bounds.west)
        lat_px = bounds.north - rows * (bounds.north - bounds.south)

        sampled = _bilinear_sample(
            lat, lon, grid, lat_query=lat_px.astype(np.float64), lon_query=lon_px
        )
        return self._colorize(sampled)

    @staticmethod
    def _validate_config(config: TilingConfig) -> None:
        if config.crs != "EPSG:4326":
            raise ValueError(
                f"Unsupported tiling CRS={config.crs!r}; expected EPSG:4326"
            )

    @staticmethod
    def _validate_zoom_range(
        *, min_zoom: int, max_zoom: int, config: TilingConfig
    ) -> None:
        if min_zoom < 0 or max_zoom < 0 or max_zoom < min_zoom:
            raise ValueError("Invalid zoom range")

        global_range = config.global_
        event_range = config.event

        if min_zoom < global_range.min_zoom:
            raise ValueError(
                f"Requested min_zoom={min_zoom} below configured global min_zoom={global_range.min_zoom}"
            )
        if max_zoom > event_range.max_zoom:
            raise ValueError(
                f"Requested max_zoom={max_zoom} exceeds configured max_zoom={event_range.max_zoom}"
            )

        in_global = (
            min_zoom >= global_range.min_zoom and max_zoom <= global_range.max_zoom
        )
        in_event = min_zoom >= event_range.min_zoom and max_zoom <= event_range.max_zoom
        if not (in_global or in_event):
            raise ValueError(
                "Requested zoom range must fall entirely within configured "
                f"global={global_range.min_zoom}–{global_range.max_zoom} "
                f"or event={event_range.min_zoom}–{event_range.max_zoom}"
            )

    def render_tile(
        self, *, zoom: int, x: int, y: int, tile_size: int | None = None
    ) -> Image.Image:
        config = get_tiling_config()
        self._validate_config(config)

        lat, lon, grid = self._extract_grid()
        resolved_tile_size = int(config.tile_size if tile_size is None else tile_size)
        self._validate_zoom_range(min_zoom=int(zoom), max_zoom=int(zoom), config=config)
        rgba = self._render_tile_array(
            zoom=zoom,
            x=x,
            y=y,
            tile_size=resolved_tile_size,
            lat=lat,
            lon=lon,
            grid=grid,
        )
        return Image.fromarray(rgba)

    def write_legend(self, output_dir: str | Path) -> Path:
        base = Path(output_dir).resolve()
        layer_dir = (base / self._layer).resolve()
        _ensure_relative_to_base(base_dir=base, path=layer_dir, label="layer")
        layer_dir.mkdir(parents=True, exist_ok=True)

        legend = self._load_legend()
        target = (layer_dir / "legend.json").resolve()
        _ensure_relative_to_base(base_dir=base, path=target, label="layer")
        target.write_text(
            json.dumps(legend, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return target

    def generate(
        self,
        output_dir: str | Path,
        *,
        min_zoom: int | None = None,
        max_zoom: int | None = None,
        tile_size: int | None = None,
        time_key: Optional[str] = None,
    ) -> TileGenerationResult:
        config = get_tiling_config()
        self._validate_config(config)

        resolved_min_zoom: int
        resolved_max_zoom: int
        if min_zoom is None and max_zoom is None:
            resolved_min_zoom = int(config.global_.min_zoom)
            resolved_max_zoom = int(config.global_.max_zoom)
        else:
            resolved_min_zoom = int(max_zoom if min_zoom is None else min_zoom)
            resolved_max_zoom = int(min_zoom if max_zoom is None else max_zoom)

        resolved_tile_size = int(config.tile_size if tile_size is None else tile_size)

        self._validate_zoom_range(
            min_zoom=resolved_min_zoom, max_zoom=resolved_max_zoom, config=config
        )

        lat, lon, grid = self._extract_grid()
        lat_min = float(np.nanmin(lat))
        lat_max = float(np.nanmax(lat))
        lon_min = float(np.nanmin(lon))
        lon_max = float(np.nanmax(lon))

        time_iso = self._ds.attrs.get("time")
        if not isinstance(time_iso, str) or time_iso.strip() == "":
            time_iso = ""
        resolved_time_key = time_key or (
            _normalize_time_key(time_iso) if time_iso else "unknown"
        )
        resolved_time_key = _validate_time_key(resolved_time_key)

        base = Path(output_dir).resolve()
        layer_dir = (base / self._layer).resolve()
        _ensure_relative_to_base(base_dir=base, path=layer_dir, label="layer")

        tiles_root = (layer_dir / resolved_time_key).resolve()
        _ensure_relative_to_base(base_dir=base, path=tiles_root, label="time_key")
        tiles_root.mkdir(parents=True, exist_ok=True)

        self.write_legend(base)

        tiles_written = 0
        for zoom in range(resolved_min_zoom, resolved_max_zoom + 1):
            x0 = lon_to_tile_x(lon_min, zoom)
            x1 = lon_to_tile_x(lon_max, zoom)
            y0 = lat_to_tile_y(lat_max, zoom)
            y1 = lat_to_tile_y(lat_min, zoom)

            for x in range(x0, x1 + 1):
                x_dir = tiles_root / str(zoom) / str(x)
                x_dir.mkdir(parents=True, exist_ok=True)
                for y in range(y0, y1 + 1):
                    rgba = self._render_tile_array(
                        zoom=zoom,
                        x=x,
                        y=y,
                        tile_size=resolved_tile_size,
                        lat=lat,
                        lon=lon,
                        grid=grid,
                    )
                    img = Image.fromarray(rgba)
                    target = x_dir / f"{y}.png"
                    img.save(target, format="PNG", optimize=True)
                    tiles_written += 1

        return TileGenerationResult(
            layer=self._layer,
            variable=self._variable,
            time=resolved_time_key,
            output_dir=layer_dir,
            min_zoom=resolved_min_zoom,
            max_zoom=resolved_max_zoom,
            tiles_written=tiles_written,
        )

    def upload_layer_to_s3(
        self,
        output_dir: str | Path,
        *,
        settings: Settings,
        cache_control: Optional[str] = "public, max-age=3600",
        prefix: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        region_name: Optional[str] = None,
    ) -> int:
        root = Path(output_dir) / self._layer
        access_key = (
            settings.storage.access_key_id.get_secret_value()
            if settings.storage.access_key_id
            else None
        )
        secret_key = (
            settings.storage.secret_access_key.get_secret_value()
            if settings.storage.secret_access_key
            else None
        )
        cfg = S3UploadConfig(
            bucket=settings.storage.tiles_bucket,
            prefix=prefix or self._layer,
            endpoint_url=endpoint_url,
            region_name=region_name,
            access_key_id=access_key,
            secret_access_key=secret_key,
            cache_control=cache_control,
        )
        return upload_directory_to_s3(root, config=cfg)
