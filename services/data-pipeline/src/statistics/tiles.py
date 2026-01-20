from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Optional, Sequence

import numpy as np
import xarray as xr
from PIL import Image

from digital_earth_config.settings import _resolve_config_dir
from legend import normalize_legend_for_clients
from tiling.cldas_tiles import (
    _bilinear_sample,
    _ensure_ascending_axis,
    _normalize_longitudes,
    gradient_rgba_from_legend,
)
from tiling.config import TilingConfig, get_tiling_config
from tiling.epsg4326 import TileBounds, lat_to_tile_y, lon_to_tile_x, tile_bounds


class StatisticsTilingError(RuntimeError):
    pass


DEFAULT_STATISTICS_LEGEND_FILENAME: Final[str] = "legend.json"
SUPPORTED_TILE_FORMATS: Final[set[str]] = {"png", "webp"}

_LAYER_SEGMENT_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_]+$")
_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.-]+$")


def _validate_layer(value: str) -> str:
    normalized = (value or "").strip().strip("/")
    if normalized == "":
        raise ValueError("layer must not be empty")
    segments = normalized.split("/")
    if any(_LAYER_SEGMENT_RE.fullmatch(seg) is None for seg in segments):
        raise ValueError("layer contains unsafe characters")
    return "/".join(segments)


def _validate_key(value: str, *, name: str) -> str:
    normalized = (value or "").strip()
    if normalized == "":
        raise ValueError(f"{name} must not be empty")
    if _KEY_RE.fullmatch(normalized) is None:
        raise ValueError(f"{name} contains unsafe characters")
    return normalized


def _ensure_relative_to_base(*, base_dir: Path, path: Path, label: str) -> None:
    if not path.is_relative_to(base_dir):
        raise ValueError(f"{label} escapes output_dir")


def _parse_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StatisticsTilingError(f"Failed to read legend file: {path}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StatisticsTilingError(f"Legend file is not valid JSON: {path}") from exc

    if not isinstance(data, dict):
        raise StatisticsTilingError(f"Legend JSON must be an object: {path}")
    return data


def load_statistics_legend(
    *,
    config_dir: str | Path | None = None,
    filename: str = DEFAULT_STATISTICS_LEGEND_FILENAME,
) -> dict[str, Any]:
    resolved_dir = (
        Path(config_dir).expanduser().resolve()
        if config_dir is not None
        else _resolve_config_dir()
    )
    path = resolved_dir / filename
    if not path.is_file():
        raise FileNotFoundError(f"Statistics legend file not found: {path}")
    return _parse_json(path)


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
class StatisticsTileGenerationResult:
    layer: str
    variable: str
    version: str
    window_key: str
    output_dir: Path
    min_zoom: int
    max_zoom: int
    formats: tuple[str, ...]
    tiles_written: int


class StatisticsTileGenerator:
    def __init__(
        self,
        ds: xr.Dataset,
        *,
        variable: str,
        layer: str,
        legend: Optional[dict[str, Any]] = None,
    ) -> None:
        self._ds = ds
        self._variable = (variable or "").strip()
        self._layer = _validate_layer(layer)
        self._legend = legend
        if self._variable == "":
            raise ValueError("variable must not be empty")

    @property
    def layer(self) -> str:
        return self._layer

    @property
    def variable(self) -> str:
        return self._variable

    def _load_legend(self) -> dict[str, Any]:
        if self._legend is None:
            self._legend = load_statistics_legend()
        return self._legend

    def _validate_config(self, config: TilingConfig) -> None:
        if config.crs != "EPSG:4326":
            raise StatisticsTilingError(f"Unsupported tiling CRS: {config.crs}")

    def _extract_grid(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if self._variable not in self._ds.data_vars:
            raise StatisticsTilingError(
                f"Variable {self._variable!r} not found; available={list(self._ds.data_vars)}"
            )

        da = self._ds[self._variable]
        if set(da.dims) != {"lat", "lon"}:
            raise StatisticsTilingError(
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
            raise StatisticsTilingError(
                "lat/lon coordinates do not match data grid shape"
            )

        return (
            lat.astype(np.float64, copy=False),
            lon.astype(np.float64, copy=False),
            grid,
        )

    def _colorize(self, values: np.ndarray) -> np.ndarray:
        legend = self._load_legend()
        return gradient_rgba_from_legend(values, legend=legend)

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
            lat,
            lon,
            grid,
            lat_query=lat_px.astype(np.float64, copy=False),
            lon_query=lon_px.astype(np.float64, copy=False),
        )

        return self._colorize(sampled)

    def render_tile(self, *, zoom: int, x: int, y: int, tile_size: int) -> Image.Image:
        lat, lon, grid = self._extract_grid()
        rgba = self._render_tile_array(
            zoom=zoom,
            x=x,
            y=y,
            tile_size=tile_size,
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

        legend = normalize_legend_for_clients(self._load_legend())
        target = (layer_dir / "legend.json").resolve()
        _ensure_relative_to_base(base_dir=base, path=target, label="legend")
        target.write_text(
            json.dumps(legend, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return target

    def generate(
        self,
        output_dir: str | Path,
        *,
        version: str,
        window_key: str,
        min_zoom: int | None = None,
        max_zoom: int | None = None,
        tile_size: int | None = None,
        formats: Sequence[str] = ("png",),
        legend_config_dir: str | Path | None = None,
        legend_filename: str = DEFAULT_STATISTICS_LEGEND_FILENAME,
    ) -> StatisticsTileGenerationResult:
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
        resolved_formats = _validate_tile_formats(formats)

        self._legend = load_statistics_legend(
            config_dir=legend_config_dir, filename=legend_filename
        )

        lat, lon, grid = self._extract_grid()
        lat_min = float(np.nanmin(lat))
        lat_max = float(np.nanmax(lat))
        lon_min = float(np.nanmin(lon))
        lon_max = float(np.nanmax(lon))

        ver = _validate_key(version, name="version")
        key = _validate_key(window_key, name="window_key")

        base = Path(output_dir).resolve()
        layer_dir = (base / self._layer).resolve()
        _ensure_relative_to_base(base_dir=base, path=layer_dir, label="layer")

        tiles_root = (layer_dir / ver / key).resolve()
        _ensure_relative_to_base(base_dir=base, path=tiles_root, label="tiles_root")
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
                    for fmt in resolved_formats:
                        target = x_dir / f"{y}.{fmt}"
                        _save_tile_image(img, target)
                        tiles_written += 1

        return StatisticsTileGenerationResult(
            layer=self._layer,
            variable=self._variable,
            version=ver,
            window_key=key,
            output_dir=layer_dir,
            min_zoom=resolved_min_zoom,
            max_zoom=resolved_max_zoom,
            formats=resolved_formats,
            tiles_written=tiles_written,
        )
