from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Sequence

import numpy as np
import xarray as xr
from PIL import Image

from datacube.core import DataCube
from tiling.cldas_tiles import (
    _bilinear_sample,
    _ensure_ascending_axis,
    _normalize_longitudes,
)
from tiling.config import TilingConfig, get_tiling_config
from tiling.epsg4326 import TileBounds, lat_to_tile_y, lon_to_tile_x, tile_bounds


class TccTilingError(RuntimeError):
    pass


DEFAULT_TCC_LAYER: Final[str] = "ecmwf/tcc"
DEFAULT_TCC_VARIABLE: Final[str] = "tcc"

_LAYER_SEGMENT_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_]+$")
_TIME_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9TZ-]+$")
_LEVEL_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_-]+$")

_SURFACE_LEVEL_ALIASES: Final[set[str]] = {"sfc", "surface"}

SUPPORTED_TILE_FORMATS: Final[set[str]] = {"png", "webp"}


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


def _validate_level_key(value: str) -> str:
    normalized = (value or "").strip()
    if normalized == "":
        raise ValueError("level_key must not be empty")
    if _LEVEL_KEY_RE.fullmatch(normalized) is None:
        raise ValueError("level_key contains unsafe characters")
    return normalized


def _ensure_relative_to_base(*, base_dir: Path, path: Path, label: str) -> None:
    if not path.is_relative_to(base_dir):
        raise ValueError(f"{label} escapes output_dir")


def _normalize_time_key(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _parse_time(value: object) -> datetime:
    if isinstance(value, np.datetime64):
        # DataCube stores time as UTC-naive datetime64; treat as UTC.
        text = np.datetime_as_string(value.astype("datetime64[s]"), unit="s")
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)

    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    raw = str(value or "").strip()
    if raw == "":
        raise ValueError("valid_time must not be empty")

    candidate = raw
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        try:
            return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise ValueError(
                "valid_time must be an ISO8601 timestamp or a tile version key"
            ) from exc


def _resolve_time_index(ds: xr.Dataset, valid_time: object) -> tuple[int, str]:
    if "time" not in ds.coords:
        # Fallback: some legacy datasets only provide ds.attrs["time"].
        time_attr = str(ds.attrs.get("time") or "").strip()
        if time_attr == "":
            raise TccTilingError("Dataset missing required coordinate: time")

        dt = _parse_time(time_attr)
        key = _validate_time_key(_normalize_time_key(dt))
        return 0, key

    values = np.asarray(ds["time"].values)
    if values.size == 0:
        raise TccTilingError("time coordinate is empty")

    dt = _parse_time(valid_time)
    key = _validate_time_key(_normalize_time_key(dt))

    target = np.datetime64(dt.strftime("%Y-%m-%dT%H:%M:%S"))
    matches = np.where(values.astype("datetime64[s]") == target)[0]
    if matches.size == 0:
        available = [
            _normalize_time_key(_parse_time(item))
            for item in values[: min(5, values.size)]
        ]
        raise TccTilingError(
            f"valid_time not found in dataset: {dt.isoformat()} (sample={available})"
        )
    return int(matches[0]), key


def _normalize_level_request(value: object) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "":
            raise ValueError("level must not be empty")
        if normalized in _SURFACE_LEVEL_ALIASES:
            return "sfc"
        raise ValueError("level must be 'sfc' for tcc tiling")

    raise ValueError("level must be 'sfc' for tcc tiling")


def _resolve_surface_level_index(ds: xr.Dataset) -> int:
    if "level" not in ds.coords:
        return 0

    levels = np.asarray(ds["level"].values)
    if levels.size == 0:
        raise TccTilingError("level coordinate is empty")
    return 0


def _resolve_level_index(ds: xr.Dataset, level: object) -> tuple[int, str]:
    level_key = _validate_level_key(_normalize_level_request(level))
    return _resolve_surface_level_index(ds), level_key


def _validate_tile_formats(formats: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for fmt in formats:
        f = (fmt or "").strip().lower()
        if f == "":
            continue
        if f not in SUPPORTED_TILE_FORMATS:
            raise ValueError(f"Unsupported tile format: {fmt!r}")
        if f not in normalized:
            normalized.append(f)
    if not normalized:
        raise ValueError("At least one tile format must be specified")
    return tuple(normalized)


def _save_tile_image(img: Image.Image, path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix == ".png":
        img.save(path, format="PNG", optimize=True)
        return
    if suffix == ".webp":
        img.save(path, format="WEBP", lossless=True, method=6)
        return
    raise ValueError(f"Unsupported tile file extension: {path.suffix}")


def _normalize_units_text(value: object) -> str:
    return str(value or "").strip()


def _resolve_tcc_fraction_scale(*, units: str, grid: np.ndarray) -> float:
    """Return the multiplicative factor to convert the raw grid into [0, 1]."""

    normalized_units = _normalize_units_text(units).lower()
    if normalized_units:
        if "%" in normalized_units or "percent" in normalized_units:
            return 0.01
        if normalized_units in {"1"} or "fraction" in normalized_units:
            return 1.0

    values = np.asarray(grid, dtype=np.float32)
    mask = np.isfinite(values)
    if not mask.any():
        return 1.0

    vmax = float(np.nanmax(values))
    # Use whole-grid statistics so we don't misclassify low-cloud tiles
    # from 0–100 datasets as 0–1 data.
    if vmax > 1.0:
        return 0.01
    return 1.0


def _normalize_tcc_fraction_grid(
    *, grid: np.ndarray, units: str, clamp: bool = True
) -> np.ndarray:
    scale = _resolve_tcc_fraction_scale(units=units, grid=grid)
    values = grid.astype(np.float32, copy=False) * np.float32(scale)
    if clamp:
        return np.clip(values, 0.0, 1.0)
    return values


def _tcc_alpha(values: np.ndarray, *, opacity: float) -> np.ndarray:
    values_f = values.astype(np.float32, copy=False)
    mask = np.isfinite(values_f)
    clipped = np.clip(values_f, 0.0, 1.0)
    clipped = np.where(mask, clipped, 0.0).astype(np.float32, copy=False)

    opacity_f = float(opacity)
    scaled = np.clip(clipped * opacity_f, 0.0, 1.0)
    alpha = np.rint(scaled * 255.0).astype(np.uint8)
    return alpha


def tcc_rgba(values: np.ndarray, *, opacity: float = 1.0) -> np.ndarray:
    if not np.isfinite(float(opacity)) or float(opacity) < 0.0 or float(opacity) > 1.0:
        raise ValueError("opacity must be between 0 and 1")

    alpha = _tcc_alpha(values, opacity=float(opacity))
    rgba = np.empty((*alpha.shape, 4), dtype=np.uint8)
    rgba[..., :3] = 255
    rgba[..., 3] = alpha
    return rgba


@dataclass(frozen=True)
class TccTileGenerationResult:
    layer: str
    variable: str
    time: str
    level: str
    opacity: float
    output_dir: Path
    min_zoom: int
    max_zoom: int
    formats: tuple[str, ...]
    tiles_written: int


class TccTileGenerator:
    def __init__(
        self,
        cube: DataCube,
        *,
        variable: str = DEFAULT_TCC_VARIABLE,
        layer: str = DEFAULT_TCC_LAYER,
    ) -> None:
        self._cube = cube
        self._variable = (variable or "").strip()
        if self._variable == "":
            raise ValueError("variable must not be empty")
        self._layer = _validate_layer(layer)

    @classmethod
    def from_dataset(
        cls,
        ds: xr.Dataset,
        *,
        variable: str = DEFAULT_TCC_VARIABLE,
        layer: str = DEFAULT_TCC_LAYER,
    ) -> "TccTileGenerator":
        return cls(DataCube.from_dataset(ds), variable=variable, layer=layer)

    @property
    def variable(self) -> str:
        return self._variable

    @property
    def layer(self) -> str:
        return self._layer

    def _extract_grid(
        self, *, time_index: int, level_index: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        ds = self._cube.dataset
        if self._variable not in ds.data_vars:
            raise TccTilingError(
                f"Variable {self._variable!r} not found; available={list(ds.data_vars)}"
            )

        da = ds[self._variable]
        if "time" not in da.dims:
            raise TccTilingError("tcc variable missing required dim: time")
        if da.sizes.get("time", 0) == 0:
            raise TccTilingError("time dimension is empty")
        if time_index < 0 or time_index >= int(da.sizes["time"]):
            raise TccTilingError("time_index is out of range")

        slice_da = da.isel(time=int(time_index))
        if "level" in slice_da.dims:
            if slice_da.sizes.get("level", 0) == 0:
                raise TccTilingError("level dimension is empty")
            if level_index < 0 or level_index >= int(slice_da.sizes["level"]):
                raise TccTilingError("level_index is out of range")
            slice_da = slice_da.isel(level=int(level_index))

        if set(slice_da.dims) != {"lat", "lon"}:
            raise TccTilingError(
                f"Expected data dims {{'lat','lon'}}, got {list(slice_da.dims)}"
            )
        slice_da = slice_da.transpose("lat", "lon")

        lat = np.asarray(ds["lat"].values)
        lon = np.asarray(ds["lon"].values)
        grid = np.asarray(slice_da.values).astype(np.float32, copy=False)

        lat, grid = _ensure_ascending_axis(lat, grid, axis=0)
        lon, grid = _ensure_ascending_axis(lon, grid, axis=1)
        lon, grid = _normalize_longitudes(lon, grid)

        if lat.size != grid.shape[0] or lon.size != grid.shape[1]:
            raise TccTilingError("lat/lon coordinates do not match tcc grid shape")

        normalized_grid = _normalize_tcc_fraction_grid(
            grid=grid, units=_normalize_units_text(slice_da.attrs.get("units"))
        )

        return (
            lat.astype(np.float64, copy=False),
            lon.astype(np.float64, copy=False),
            normalized_grid,
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
        opacity: float,
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
        return tcc_rgba(sampled, opacity=opacity)

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
        self,
        *,
        zoom: int,
        x: int,
        y: int,
        valid_time: object,
        level: object = "sfc",
        tile_size: int | None = None,
        opacity: float = 1.0,
    ) -> Image.Image:
        ds = self._cube.dataset
        time_index, _ = _resolve_time_index(ds, valid_time)
        level_index, _ = _resolve_level_index(ds, level)

        config = get_tiling_config()
        self._validate_config(config)

        lat, lon, grid = self._extract_grid(
            time_index=time_index, level_index=level_index
        )
        resolved_tile_size = int(config.tile_size if tile_size is None else tile_size)
        self._validate_zoom_range(min_zoom=int(zoom), max_zoom=int(zoom), config=config)
        rgba = self._render_tile_array(
            zoom=int(zoom),
            x=int(x),
            y=int(y),
            tile_size=resolved_tile_size,
            lat=lat,
            lon=lon,
            grid=grid,
            opacity=opacity,
        )
        return Image.fromarray(rgba)

    def generate(
        self,
        output_dir: str | Path,
        *,
        valid_time: object,
        level: object = "sfc",
        opacity: float = 1.0,
        min_zoom: int | None = None,
        max_zoom: int | None = None,
        tile_size: int | None = None,
        formats: Sequence[str] = ("png", "webp"),
    ) -> TccTileGenerationResult:
        ds = self._cube.dataset
        time_index, time_key = _resolve_time_index(ds, valid_time)
        level_index, level_key = _resolve_level_index(ds, level)

        resolved_formats = _validate_tile_formats(formats)

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

        lat, lon, grid = self._extract_grid(
            time_index=time_index, level_index=level_index
        )
        lat_min = float(np.nanmin(lat))
        lat_max = float(np.nanmax(lat))
        lon_min = float(np.nanmin(lon))
        lon_max = float(np.nanmax(lon))

        base = Path(output_dir).resolve()
        layer_dir = (base / self._layer).resolve()
        _ensure_relative_to_base(base_dir=base, path=layer_dir, label="layer")

        tiles_root = (layer_dir / time_key / level_key).resolve()
        _ensure_relative_to_base(base_dir=base, path=tiles_root, label="time_key")
        tiles_root.mkdir(parents=True, exist_ok=True)

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
                        opacity=opacity,
                    )
                    img = Image.fromarray(rgba)
                    for fmt in resolved_formats:
                        target = x_dir / f"{y}.{fmt}"
                        _save_tile_image(img, target)
                        tiles_written += 1

        return TccTileGenerationResult(
            layer=self._layer,
            variable=self._variable,
            time=time_key,
            level=level_key,
            opacity=float(opacity),
            output_dir=layer_dir,
            min_zoom=resolved_min_zoom,
            max_zoom=resolved_max_zoom,
            formats=resolved_formats,
            tiles_written=tiles_written,
        )
