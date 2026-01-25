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
from derived.cloud_density import normalize_relative_humidity
from tiling.cldas_tiles import (
    _bilinear_sample,
    _ensure_ascending_axis,
    _normalize_longitudes,
)
from tiling.config import TilingConfig, get_tiling_config
from tiling.epsg4326 import TileBounds, lat_to_tile_y, lon_to_tile_x, tile_bounds
from tiling.tcc_tiles import tcc_rgba


class HumidityTilingError(RuntimeError):
    pass


DEFAULT_HUMIDITY_LAYER: Final[str] = "ecmwf/humidity"
DEFAULT_HUMIDITY_VARIABLE: Final[str] = "r"

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
        raise HumidityTilingError("Dataset missing required coordinate: time")

    values = np.asarray(ds["time"].values)
    if values.size == 0:
        raise HumidityTilingError("time coordinate is empty")

    dt = _parse_time(valid_time)
    key = _validate_time_key(_normalize_time_key(dt))

    target = np.datetime64(dt.strftime("%Y-%m-%dT%H:%M:%S"))
    matches = np.where(values.astype("datetime64[s]") == target)[0]
    if matches.size == 0:
        available = [
            _normalize_time_key(_parse_time(item))
            for item in values[: min(5, values.size)]
        ]
        raise HumidityTilingError(
            f"valid_time not found in dataset: {dt.isoformat()} (sample={available})"
        )
    return int(matches[0]), key


def _normalize_level_request(value: object) -> tuple[str, float | None]:
    if isinstance(value, str):
        normalized = value.strip()
        if normalized == "":
            raise ValueError("level must not be empty")
        lowered = normalized.lower()
        if lowered in _SURFACE_LEVEL_ALIASES:
            return "sfc", None
        try:
            stripped = re.sub(r"hpa$", "", lowered).strip()
            numeric = float(stripped)
        except ValueError as exc:
            raise ValueError("level must be 'sfc' or a numeric pressure level") from exc
        if not np.isfinite(numeric):
            raise ValueError("level must be a finite number")
        if numeric.is_integer():
            level_key = str(int(numeric))
        else:
            level_key = str(numeric).replace(".", "p")
        return _validate_level_key(level_key), numeric

    if isinstance(value, (int, float, np.number)):
        numeric = float(value)
        if not np.isfinite(numeric):
            raise ValueError("level must be a finite number")
        if numeric.is_integer():
            level_key = str(int(numeric))
        else:
            level_key = str(numeric).replace(".", "p")
        return _validate_level_key(level_key), numeric

    raise ValueError("level must be 'sfc' or a numeric pressure level")


def _resolve_surface_level_index(levels: np.ndarray, attrs: dict) -> int:
    units = str(attrs.get("units") or "").strip().lower()
    long_name = str(attrs.get("long_name") or "").strip().lower()

    if "surface" in long_name or units in {"1", ""}:
        return 0

    matches = np.where(
        np.isclose(levels.astype(np.float64, copy=False), 0.0, atol=1e-3)
    )[0]
    if matches.size:
        return int(matches[0])
    raise HumidityTilingError(
        "surface level requested but dataset has no surface level"
    )


def _resolve_level_index(ds: xr.Dataset, level: object) -> tuple[int, str]:
    if "level" not in ds.coords:
        raise HumidityTilingError("Dataset missing required coordinate: level")

    levels = np.asarray(ds["level"].values)
    if levels.size == 0:
        raise HumidityTilingError("level coordinate is empty")

    level_key, numeric = _normalize_level_request(level)
    if level_key.lower() in _SURFACE_LEVEL_ALIASES or level_key == "sfc":
        idx = _resolve_surface_level_index(levels, dict(ds["level"].attrs))
        return idx, "sfc"

    if numeric is None or not np.isfinite(numeric):
        raise HumidityTilingError("Pressure level must be a finite number")

    numeric_f = float(numeric)
    matches = np.where(
        np.isclose(levels.astype(np.float64, copy=False), numeric_f, atol=1e-3)
    )[0]
    if matches.size == 0:
        available = [str(val) for val in levels[: min(5, levels.size)]]
        raise HumidityTilingError(
            f"level not found in dataset: {numeric_f} (sample={available})"
        )

    resolved = levels[int(matches[0])]
    if np.isfinite(resolved) and float(resolved).is_integer():
        level_key = str(int(float(resolved)))
    else:
        level_key = str(numeric_f).replace(".", "p")
    return int(matches[0]), _validate_level_key(level_key)


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


def _validate_opacity(value: float) -> float:
    opacity = float(value)
    if not np.isfinite(opacity) or opacity < 0.0 or opacity > 1.0:
        raise ValueError("opacity must be between 0 and 1")
    return opacity


@dataclass(frozen=True)
class HumidityTileGenerationResult:
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


class HumidityTileGenerator:
    def __init__(
        self,
        cube: DataCube,
        *,
        variable: str = DEFAULT_HUMIDITY_VARIABLE,
        layer: str = DEFAULT_HUMIDITY_LAYER,
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
        variable: str = DEFAULT_HUMIDITY_VARIABLE,
        layer: str = DEFAULT_HUMIDITY_LAYER,
    ) -> "HumidityTileGenerator":
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
            raise HumidityTilingError(
                f"Variable {self._variable!r} not found; available={list(ds.data_vars)}"
            )

        da = ds[self._variable]
        if "time" not in da.dims:
            raise HumidityTilingError("humidity variable missing required dim: time")
        if "level" not in da.dims:
            raise HumidityTilingError("humidity variable missing required dim: level")

        time_count = int(da.sizes.get("time", 0))
        level_count = int(da.sizes.get("level", 0))
        if time_count == 0:
            raise HumidityTilingError("time dimension is empty")
        if level_count == 0:
            raise HumidityTilingError("level dimension is empty")
        if time_index < 0 or time_index >= time_count:
            raise HumidityTilingError("time_index is out of range")
        if level_index < 0 or level_index >= level_count:
            raise HumidityTilingError("level_index is out of range")

        slice_da = da.isel(time=int(time_index), level=int(level_index))
        if set(slice_da.dims) != {"lat", "lon"}:
            raise HumidityTilingError(
                f"Expected data dims {{'lat','lon'}}, got {list(slice_da.dims)}"
            )
        slice_da = slice_da.transpose("lat", "lon")

        lat = np.asarray(ds["lat"].values)
        lon = np.asarray(ds["lon"].values)
        grid = np.asarray(normalize_relative_humidity(slice_da).values).astype(
            np.float32, copy=False
        )

        lat, grid = _ensure_ascending_axis(lat, grid, axis=0)
        lon, grid = _ensure_ascending_axis(lon, grid, axis=1)
        lon, grid = _normalize_longitudes(lon, grid)

        if lat.size != grid.shape[0] or lon.size != grid.shape[1]:
            raise HumidityTilingError("lat/lon coordinates do not match grid shape")

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
        level: object,
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
            opacity=_validate_opacity(opacity),
        )
        return Image.fromarray(rgba)

    def generate(
        self,
        output_dir: str | Path,
        *,
        valid_time: object,
        level: object,
        opacity: float = 1.0,
        min_zoom: int | None = None,
        max_zoom: int | None = None,
        tile_size: int | None = None,
        formats: Sequence[str] = ("png", "webp"),
    ) -> HumidityTileGenerationResult:
        ds = self._cube.dataset
        time_index, time_key = _resolve_time_index(ds, valid_time)
        level_index, level_key = _resolve_level_index(ds, level)

        resolved_formats = _validate_tile_formats(formats)
        resolved_opacity = _validate_opacity(opacity)

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
                        opacity=resolved_opacity,
                    )
                    img = Image.fromarray(rgba)
                    for fmt in resolved_formats:
                        target = x_dir / f"{y}.{fmt}"
                        _save_tile_image(img, target)
                        tiles_written += 1

        return HumidityTileGenerationResult(
            layer=self._layer,
            variable=self._variable,
            time=time_key,
            level=level_key,
            opacity=resolved_opacity,
            output_dir=layer_dir,
            min_zoom=resolved_min_zoom,
            max_zoom=resolved_max_zoom,
            formats=resolved_formats,
            tiles_written=tiles_written,
        )
