from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Mapping, Optional, Sequence

import numpy as np
import xarray as xr
from PIL import Image

from datacube.core import DataCube
from digital_earth_config.settings import _resolve_config_dir
from tiling.cldas_tiles import (
    _bilinear_sample,
    _ensure_ascending_axis,
    _normalize_longitudes,
    gradient_rgba_from_legend,
)
from tiling.config import TilingConfig, get_tiling_config
from tiling.epsg4326 import TileBounds, lat_to_tile_y, lon_to_tile_x, tile_bounds


class PrecipAmountTilingError(RuntimeError):
    pass


DEFAULT_PRECIP_AMOUNT_LAYER: Final[str] = "ecmwf/precip_amount"
DEFAULT_PRECIP_AMOUNT_VARIABLE: Final[str] = "precipitation_amount"
DEFAULT_PRECIP_AMOUNT_LEGEND_FILENAME: Final[str] = "precip_amount_legend.json"
DEFAULT_OUTPUT_LEGEND_FILENAME: Final[str] = "legend.json"

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


def _parse_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PrecipAmountTilingError(f"Failed to read legend file: {path}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PrecipAmountTilingError(f"Legend file is not valid JSON: {path}") from exc

    if not isinstance(data, dict):
        raise PrecipAmountTilingError(f"Legend JSON must be an object: {path}")
    return data


def load_precip_amount_legend(
    *,
    config_dir: str | Path | None = None,
    filename: str = DEFAULT_PRECIP_AMOUNT_LEGEND_FILENAME,
) -> dict[str, Any]:
    resolved_dir = (
        Path(config_dir).expanduser().resolve()
        if config_dir is not None
        else _resolve_config_dir()
    )
    path = resolved_dir / filename
    if not path.is_file():
        raise FileNotFoundError(f"Precip legend file not found: {path}")
    return _parse_json(path)


@lru_cache(maxsize=8)
def _get_precip_amount_legend_cached(
    config_dir: str, filename: str, mtime_ns: int, size: int
) -> dict[str, Any]:
    _ = (mtime_ns, size)
    return load_precip_amount_legend(config_dir=config_dir, filename=filename)


def get_precip_amount_legend(
    *,
    config_dir: str | Path | None = None,
    filename: str = DEFAULT_PRECIP_AMOUNT_LEGEND_FILENAME,
) -> dict[str, Any]:
    resolved_dir = (
        Path(config_dir).expanduser().resolve()
        if config_dir is not None
        else _resolve_config_dir()
    )
    path = resolved_dir / filename
    try:
        stat = path.stat()
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Precip legend file not found: {path}") from exc
    return _get_precip_amount_legend_cached(
        str(resolved_dir), filename, stat.st_mtime_ns, stat.st_size
    )


get_precip_amount_legend.cache_clear = _get_precip_amount_legend_cached.cache_clear  # type: ignore[attr-defined]


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
        raise PrecipAmountTilingError("Dataset missing required coordinate: time")

    values = np.asarray(ds["time"].values)
    if values.size == 0:
        raise PrecipAmountTilingError("time coordinate is empty")

    dt = _parse_time(valid_time)
    key = _validate_time_key(_normalize_time_key(dt))

    target = np.datetime64(dt.strftime("%Y-%m-%dT%H:%M:%S"))
    matches = np.where(values.astype("datetime64[s]") == target)[0]
    if matches.size == 0:
        available = [
            _normalize_time_key(_parse_time(item))
            for item in values[: min(5, values.size)]
        ]
        raise PrecipAmountTilingError(
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
        raise ValueError("level must be 'sfc' for precipitation tiling")

    raise ValueError("level must be 'sfc' for precipitation tiling")


def _resolve_level_index(ds: xr.Dataset, level: object) -> tuple[int, str]:
    level_key = _validate_level_key(_normalize_level_request(level))

    if "level" in ds.coords:
        levels = np.asarray(ds["level"].values)
        if levels.size == 0:
            raise PrecipAmountTilingError("level coordinate is empty")

    return 0, level_key


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


def _interval_hours(time_values: np.ndarray, time_index: int) -> float:
    if time_index <= 0:
        return float("nan")

    times = np.asarray(time_values).astype("datetime64[s]")
    if time_index >= times.size:
        raise PrecipAmountTilingError("time_index is out of range")

    delta = times[int(time_index)] - times[int(time_index) - 1]
    hours = delta / np.timedelta64(1, "h")
    hours_f = float(hours)
    if not np.isfinite(hours_f) or hours_f <= 0:
        raise PrecipAmountTilingError("time coordinate must be strictly increasing")
    return hours_f


def _alpha_from_legend_range(
    values: np.ndarray, *, legend: Mapping[str, Any]
) -> np.ndarray:
    stops = legend.get("stops")
    if not isinstance(stops, list) or len(stops) < 2:
        raise ValueError("legend.stops must be a list with at least 2 stops")

    stop_values: list[float] = []
    for stop in stops:
        if not isinstance(stop, dict):
            raise ValueError("legend.stops entries must be objects")
        raw_value = stop.get("value")
        if not isinstance(raw_value, (int, float)) or not np.isfinite(float(raw_value)):
            raise ValueError("legend stop value must be a finite number")
        stop_values.append(float(raw_value))

    values_np = np.asarray(stop_values, dtype=np.float64)
    vmin = float(np.nanmin(values_np))
    vmax = float(np.nanmax(values_np))
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax <= vmin:
        raise ValueError("legend stop values must span a positive range")

    values_f = values.astype(np.float32, copy=False)
    mask = np.isfinite(values_f)
    clipped = np.clip(values_f, vmin, vmax)
    norm = (clipped - np.float32(vmin)) / np.float32(vmax - vmin)
    norm = np.clip(norm, 0.0, 1.0)

    alpha = np.zeros(values_f.shape, dtype=np.uint8)
    alpha[mask] = np.rint(norm[mask] * 255.0).astype(np.uint8)
    return alpha


def precip_intensity_rgba(values: np.ndarray, *, legend: dict[str, Any]) -> np.ndarray:
    rgba = gradient_rgba_from_legend(values, legend=legend)
    rgba[..., 3] = _alpha_from_legend_range(values, legend=legend)
    return rgba


@dataclass(frozen=True)
class PrecipAmountTileGenerationResult:
    layer: str
    variable: str
    time: str
    level: str
    output_dir: Path
    min_zoom: int
    max_zoom: int
    formats: tuple[str, ...]
    tiles_written: int


class PrecipAmountTileGenerator:
    def __init__(
        self,
        cube: DataCube,
        *,
        variable: str = DEFAULT_PRECIP_AMOUNT_VARIABLE,
        layer: str = DEFAULT_PRECIP_AMOUNT_LAYER,
        legend_filename: str = DEFAULT_PRECIP_AMOUNT_LEGEND_FILENAME,
    ) -> None:
        self._cube = cube
        self._variable = (variable or "").strip()
        if self._variable == "":
            raise ValueError("variable must not be empty")

        self._layer = _validate_layer(layer)
        self._legend_filename = (
            legend_filename or ""
        ).strip() or DEFAULT_PRECIP_AMOUNT_LEGEND_FILENAME
        self._legend: Optional[dict[str, Any]] = None

    @classmethod
    def from_dataset(
        cls,
        ds: xr.Dataset,
        *,
        variable: str = DEFAULT_PRECIP_AMOUNT_VARIABLE,
        layer: str = DEFAULT_PRECIP_AMOUNT_LAYER,
        legend_filename: str = DEFAULT_PRECIP_AMOUNT_LEGEND_FILENAME,
    ) -> "PrecipAmountTileGenerator":
        return cls(
            DataCube.from_dataset(ds),
            variable=variable,
            layer=layer,
            legend_filename=legend_filename,
        )

    @property
    def variable(self) -> str:
        return self._variable

    @property
    def layer(self) -> str:
        return self._layer

    def _load_legend(self) -> dict[str, Any]:
        if self._legend is None:
            self._legend = get_precip_amount_legend(filename=self._legend_filename)
        return self._legend

    def _colorize(self, values: np.ndarray) -> np.ndarray:
        legend = self._load_legend()
        return precip_intensity_rgba(values, legend=legend)

    def _extract_intensity_grid(
        self, *, time_index: int, level_index: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        ds = self._cube.dataset
        if self._variable not in ds.data_vars:
            raise PrecipAmountTilingError(
                f"Variable {self._variable!r} not found; available={list(ds.data_vars)}"
            )

        da = ds[self._variable]
        if "time" not in da.dims:
            raise PrecipAmountTilingError(
                "precip amount variable missing required dim: time"
            )
        if "level" not in da.dims:
            raise PrecipAmountTilingError(
                "precip amount variable missing required dim: level"
            )

        time_count = int(da.sizes.get("time", 0))
        if time_count == 0:
            raise PrecipAmountTilingError("time dimension is empty")
        level_count = int(da.sizes.get("level", 0))
        if level_count == 0:
            raise PrecipAmountTilingError("level dimension is empty")
        if time_index < 0 or time_index >= time_count:
            raise PrecipAmountTilingError("time_index is out of range")
        if level_index < 0 or level_index >= level_count:
            raise PrecipAmountTilingError("level_index is out of range")

        slice_da = da.isel(time=int(time_index), level=int(level_index))
        if set(slice_da.dims) != {"lat", "lon"}:
            raise PrecipAmountTilingError(
                f"Expected data dims {{'lat','lon'}}, got {list(slice_da.dims)}"
            )
        slice_da = slice_da.transpose("lat", "lon")

        lat = np.asarray(ds["lat"].values)
        lon = np.asarray(ds["lon"].values)
        amount = np.asarray(slice_da.values).astype(np.float32, copy=False)

        lat, amount = _ensure_ascending_axis(lat, amount, axis=0)
        lon, amount = _ensure_ascending_axis(lon, amount, axis=1)
        lon, amount = _normalize_longitudes(lon, amount)

        if lat.size != amount.shape[0] or lon.size != amount.shape[1]:
            raise PrecipAmountTilingError(
                "lat/lon coordinates do not match precip amount grid shape"
            )

        if np.isfinite(amount).any():
            amount = np.where(amount < 0.0, 0.0, amount).astype(np.float32, copy=False)

        # Convert per-interval amount into intensity (mm/h) using time deltas.
        if int(time_index) == 0:
            intensity = np.full_like(amount, np.nan, dtype=np.float32)
        else:
            interval_hours = _interval_hours(
                np.asarray(ds["time"].values), int(time_index)
            )
            intensity = (amount / np.float32(interval_hours)).astype(
                np.float32, copy=False
            )

        return (
            lat.astype(np.float64, copy=False),
            lon.astype(np.float64, copy=False),
            intensity,
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
        intensity: np.ndarray,
    ) -> np.ndarray:
        if tile_size <= 0:
            raise ValueError("tile_size must be > 0")

        bounds: TileBounds = tile_bounds(zoom, x, y)

        cols = (np.arange(tile_size, dtype=np.float64) + 0.5) / tile_size
        rows = (np.arange(tile_size, dtype=np.float64) + 0.5) / tile_size

        lon_px = bounds.west + cols * (bounds.east - bounds.west)
        lat_px = bounds.north - rows * (bounds.north - bounds.south)

        sampled = _bilinear_sample(
            lat, lon, intensity, lat_query=lat_px.astype(np.float64), lon_query=lon_px
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
        self,
        *,
        zoom: int,
        x: int,
        y: int,
        valid_time: object,
        level: object = "sfc",
        tile_size: int | None = None,
    ) -> Image.Image:
        ds = self._cube.dataset
        time_index, _ = _resolve_time_index(ds, valid_time)
        level_index, _ = _resolve_level_index(ds, level)

        config = get_tiling_config()
        self._validate_config(config)

        lat, lon, intensity = self._extract_intensity_grid(
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
            intensity=intensity,
        )
        return Image.fromarray(rgba)

    def write_legend(self, output_dir: str | Path) -> Path:
        base = Path(output_dir).resolve()
        layer_dir = (base / self._layer).resolve()
        _ensure_relative_to_base(base_dir=base, path=layer_dir, label="layer")
        layer_dir.mkdir(parents=True, exist_ok=True)

        legend = self._load_legend()
        target = (layer_dir / DEFAULT_OUTPUT_LEGEND_FILENAME).resolve()
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
        valid_time: object,
        level: object = "sfc",
        min_zoom: int | None = None,
        max_zoom: int | None = None,
        tile_size: int | None = None,
        formats: Sequence[str] = ("png", "webp"),
    ) -> PrecipAmountTileGenerationResult:
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

        lat, lon, intensity = self._extract_intensity_grid(
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
                        intensity=intensity,
                    )
                    img = Image.fromarray(rgba)
                    for fmt in resolved_formats:
                        target = x_dir / f"{y}.{fmt}"
                        _save_tile_image(img, target)
                        tiles_written += 1

        return PrecipAmountTileGenerationResult(
            layer=self._layer,
            variable=self._variable,
            time=time_key,
            level=level_key,
            output_dir=layer_dir,
            min_zoom=resolved_min_zoom,
            max_zoom=resolved_max_zoom,
            formats=resolved_formats,
            tiles_written=tiles_written,
        )
