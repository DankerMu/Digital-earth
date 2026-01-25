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

from legend import normalize_legend_for_clients
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


class TemperatureTilingError(RuntimeError):
    pass


DEFAULT_TEMPERATURE_LAYER: Final[str] = "ecmwf/temp"
DEFAULT_TEMPERATURE_VARIABLE: Final[str] = "temp"
DEFAULT_TEMPERATURE_VARIABLE_ALIASES: Final[tuple[str, ...]] = (
    "temp",
    "t2m",
    "2t",
    "air_temperature",
    "tmp",
)
DEFAULT_TEMPERATURE_LEGEND_FILENAME: Final[str] = "legend.json"

_LAYER_SEGMENT_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_]+$")
_TIME_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9TZ-]+$")
_LEVEL_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_-]+$")

_SURFACE_LEVEL_ALIASES: Final[set[str]] = {"sfc", "surface"}

SUPPORTED_TILE_FORMATS: Final[set[str]] = {"png", "webp"}


def _resolve_temperature_variable(ds: xr.Dataset, preferred: str) -> str:
    preferred_norm = (preferred or "").strip()
    if preferred_norm == "":
        raise ValueError("variable must not be empty")

    present = {name.lower(): name for name in ds.data_vars}
    direct = present.get(preferred_norm.lower())
    if direct is not None:
        return direct

    for candidate in DEFAULT_TEMPERATURE_VARIABLE_ALIASES:
        resolved = present.get(candidate.lower())
        if resolved is not None:
            return resolved

    available = ", ".join(sorted(ds.data_vars))
    raise TemperatureTilingError(
        f"Temperature variable {preferred_norm!r} not found; available=[{available}]"
    )


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
        raise TemperatureTilingError(f"Failed to read legend file: {path}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TemperatureTilingError(f"Legend file is not valid JSON: {path}") from exc

    if not isinstance(data, dict):
        raise TemperatureTilingError(f"Legend JSON must be an object: {path}")
    return data


def load_temperature_legend(
    *,
    config_dir: str | Path | None = None,
    filename: str = DEFAULT_TEMPERATURE_LEGEND_FILENAME,
) -> dict[str, Any]:
    resolved_dir = (
        Path(config_dir).expanduser().resolve()
        if config_dir is not None
        else _resolve_config_dir()
    )
    path = resolved_dir / filename
    if not path.is_file():
        raise FileNotFoundError(f"Temperature legend file not found: {path}")
    return _parse_json(path)


@lru_cache(maxsize=8)
def _get_temperature_legend_cached(
    config_dir: str, filename: str, mtime_ns: int, size: int
) -> dict[str, Any]:
    _ = (mtime_ns, size)
    return load_temperature_legend(config_dir=config_dir, filename=filename)


def get_temperature_legend(
    *,
    config_dir: str | Path | None = None,
    filename: str = DEFAULT_TEMPERATURE_LEGEND_FILENAME,
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
        raise FileNotFoundError(f"Temperature legend file not found: {path}") from exc
    return _get_temperature_legend_cached(
        str(resolved_dir), filename, stat.st_mtime_ns, stat.st_size
    )


get_temperature_legend.cache_clear = _get_temperature_legend_cached.cache_clear  # type: ignore[attr-defined]


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
        raise TemperatureTilingError("Dataset missing required coordinate: time")

    values = np.asarray(ds["time"].values)
    if values.size == 0:
        raise TemperatureTilingError("time coordinate is empty")

    dt = _parse_time(valid_time)
    key = _validate_time_key(_normalize_time_key(dt))

    target = np.datetime64(dt.strftime("%Y-%m-%dT%H:%M:%S"))
    matches = np.where(values.astype("datetime64[s]") == target)[0]
    if matches.size == 0:
        available = [
            _normalize_time_key(_parse_time(item))
            for item in values[: min(5, values.size)]
        ]
        raise TemperatureTilingError(
            f"valid_time not found in dataset: {dt.isoformat()} (sample={available})"
        )
    return int(matches[0]), key


def _normalize_level_request(value: object) -> tuple[str, Optional[float]]:
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

    if isinstance(value, (int, float, np.integer, np.floating)):
        numeric = float(value)
        if not np.isfinite(numeric):
            raise ValueError("level must be a finite number")
        if numeric.is_integer():
            level_key = str(int(numeric))
        else:
            level_key = str(numeric).replace(".", "p")
        return _validate_level_key(level_key), numeric

    raise ValueError("level must be 'sfc' or a numeric pressure level")


def _resolve_surface_level_index(levels: np.ndarray, attrs: Mapping[str, Any]) -> int:
    units = str(attrs.get("units") or "").strip().lower()
    long_name = str(attrs.get("long_name") or "").strip().lower()

    if "surface" in long_name or units in {"1", ""}:
        return 0

    matches = np.where(
        np.isclose(levels.astype(np.float64, copy=False), 0.0, atol=1e-3)
    )[0]
    if matches.size:
        return int(matches[0])
    raise TemperatureTilingError(
        "surface level requested but dataset has no surface level"
    )


def _resolve_level_index(ds: xr.Dataset, level: object) -> tuple[int, str]:
    if "level" not in ds.coords:
        raise TemperatureTilingError("Dataset missing required coordinate: level")

    levels = np.asarray(ds["level"].values)
    if levels.size == 0:
        raise TemperatureTilingError("level coordinate is empty")

    level_key, numeric = _normalize_level_request(level)
    if level_key.lower() in _SURFACE_LEVEL_ALIASES or level_key == "sfc":
        idx = _resolve_surface_level_index(levels, ds["level"].attrs)
        return idx, "sfc"

    if numeric is None or not np.isfinite(numeric):
        raise TemperatureTilingError("Pressure level must be a finite number")

    numeric_f = float(numeric)
    matches = np.where(
        np.isclose(levels.astype(np.float64, copy=False), numeric_f, atol=1e-3)
    )[0]
    if matches.size == 0:
        available = [str(val) for val in levels[: min(5, levels.size)]]
        raise TemperatureTilingError(
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


@dataclass(frozen=True)
class TemperatureTileGenerationResult:
    layer: str
    variable: str
    time: str
    level: str
    output_dir: Path
    min_zoom: int
    max_zoom: int
    formats: tuple[str, ...]
    tiles_written: int


class TemperatureTileGenerator:
    def __init__(
        self,
        cube: DataCube,
        *,
        variable: str = DEFAULT_TEMPERATURE_VARIABLE,
        layer: str = DEFAULT_TEMPERATURE_LAYER,
        legend_filename: str = DEFAULT_TEMPERATURE_LEGEND_FILENAME,
    ) -> None:
        self._cube = cube
        self._variable = (variable or "").strip()
        if self._variable == "":
            raise ValueError("variable must not be empty")

        self._layer = _validate_layer(layer)
        self._legend_filename = (
            legend_filename or ""
        ).strip() or DEFAULT_TEMPERATURE_LEGEND_FILENAME
        self._legend: Optional[dict[str, Any]] = None

    @classmethod
    def from_dataset(
        cls,
        ds: xr.Dataset,
        *,
        variable: str = DEFAULT_TEMPERATURE_VARIABLE,
        layer: str = DEFAULT_TEMPERATURE_LAYER,
        legend_filename: str = DEFAULT_TEMPERATURE_LEGEND_FILENAME,
    ) -> "TemperatureTileGenerator":
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

    def _resolve_variable_name(self, ds: xr.Dataset) -> str:
        return _resolve_temperature_variable(ds, self._variable)

    def _load_legend(self) -> dict[str, Any]:
        if self._legend is None:
            self._legend = get_temperature_legend(filename=self._legend_filename)
        return self._legend

    def _colorize(self, values: np.ndarray) -> np.ndarray:
        legend = self._load_legend()
        return gradient_rgba_from_legend(values, legend=legend)

    def _extract_grid(
        self, *, time_index: int, level_index: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
        ds = self._cube.dataset
        variable_name = self._resolve_variable_name(ds)

        da = ds[variable_name]
        if "time" not in da.dims:
            raise TemperatureTilingError("temp variable missing required dim: time")
        if "level" not in da.dims:
            raise TemperatureTilingError("temp variable missing required dim: level")

        time_count = int(da.sizes.get("time", 0))
        if time_count == 0:
            raise TemperatureTilingError("time dimension is empty")
        level_count = int(da.sizes.get("level", 0))
        if level_count == 0:
            raise TemperatureTilingError("level dimension is empty")
        if time_index < 0 or time_index >= time_count:
            raise TemperatureTilingError("time_index is out of range")
        if level_index < 0 or level_index >= level_count:
            raise TemperatureTilingError("level_index is out of range")

        slice_da = da.isel(time=int(time_index), level=int(level_index))
        if set(slice_da.dims) != {"lat", "lon"}:
            raise TemperatureTilingError(
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
            raise TemperatureTilingError(
                "lat/lon coordinates do not match temp grid shape"
            )

        return (
            lat.astype(np.float64, copy=False),
            lon.astype(np.float64, copy=False),
            grid,
            variable_name,
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
        self,
        *,
        zoom: int,
        x: int,
        y: int,
        valid_time: object,
        level: object,
        tile_size: int | None = None,
    ) -> Image.Image:
        ds = self._cube.dataset
        time_index, _ = _resolve_time_index(ds, valid_time)
        level_index, _ = _resolve_level_index(ds, level)

        config = get_tiling_config()
        self._validate_config(config)

        lat, lon, grid, _variable_name = self._extract_grid(
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
        )
        return Image.fromarray(rgba)

    def write_legend(
        self, output_dir: str | Path, *, level_key: str | None = None
    ) -> Path:
        base = Path(output_dir).resolve()
        layer_dir = (base / self._layer).resolve()
        _ensure_relative_to_base(base_dir=base, path=layer_dir, label="layer")
        layer_dir.mkdir(parents=True, exist_ok=True)

        legend = normalize_legend_for_clients(self._load_legend())
        target = (layer_dir / DEFAULT_TEMPERATURE_LEGEND_FILENAME).resolve()
        _ensure_relative_to_base(base_dir=base, path=target, label="layer")
        target.write_text(
            json.dumps(legend, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        if level_key is not None:
            level_dir = (layer_dir / _validate_level_key(level_key)).resolve()
            _ensure_relative_to_base(base_dir=base, path=level_dir, label="level")
            level_dir.mkdir(parents=True, exist_ok=True)
            level_target = (level_dir / DEFAULT_TEMPERATURE_LEGEND_FILENAME).resolve()
            _ensure_relative_to_base(base_dir=base, path=level_target, label="level")
            level_target.write_text(
                json.dumps(legend, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        return target

    def generate(
        self,
        output_dir: str | Path,
        *,
        valid_time: object,
        level: object,
        min_zoom: int | None = None,
        max_zoom: int | None = None,
        tile_size: int | None = None,
        formats: Sequence[str] = ("png", "webp"),
    ) -> TemperatureTileGenerationResult:
        ds = self._cube.dataset
        time_index, time_key = _resolve_time_index(ds, valid_time)
        level_index, level_key = _resolve_level_index(ds, level)
        level_key = _validate_level_key(level_key)

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

        lat, lon, grid, variable_name = self._extract_grid(
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

        self.write_legend(base, level_key=level_key)

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
                    for fmt in resolved_formats:
                        target = x_dir / f"{y}.{fmt}"
                        _save_tile_image(img, target)
                        tiles_written += 1

        return TemperatureTileGenerationResult(
            layer=self._layer,
            variable=variable_name,
            time=time_key,
            level=level_key,
            output_dir=layer_dir,
            min_zoom=resolved_min_zoom,
            max_zoom=resolved_max_zoom,
            formats=resolved_formats,
            tiles_written=tiles_written,
        )
