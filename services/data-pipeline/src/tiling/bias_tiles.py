from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Sequence

import numpy as np
import xarray as xr

from datacube.core import DataCube
from derived.bias import BiasMode, BiasDerivationError, derive_bias_grid
from digital_earth_config.settings import _resolve_config_dir
from legend import normalize_legend_for_clients
from tiling.temperature_tiles import (
    TemperatureTileGenerationResult,
    TemperatureTileGenerator,
    _ensure_relative_to_base,
    _validate_layer,
)


class BiasTilingError(RuntimeError):
    pass


DEFAULT_BIAS_LAYER: Final[str] = "bias/temp"
DEFAULT_BIAS_VARIABLE: Final[str] = "bias"
DEFAULT_BIAS_FORECAST_VARIABLE: Final[str] = "temp"
DEFAULT_BIAS_OBSERVATION_VARIABLE: Final[str] = "TMP"
DEFAULT_BIAS_LEGEND_FILENAME: Final[str] = "bias_legend.json"
DEFAULT_BIAS_RELATIVE_ERROR_LEGEND_FILENAME: Final[str] = (
    "bias_relative_error_legend.json"
)

SUPPORTED_TILE_FORMATS: Final[set[str]] = {"png", "webp"}

_INTERP_METHODS: Final[set[str]] = {"linear", "nearest"}

_TIME_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9TZ-]+$")


def _validate_time_key(value: str) -> str:
    normalized = (value or "").strip()
    if normalized == "":
        raise ValueError("time_key must not be empty")
    if _TIME_KEY_RE.fullmatch(normalized) is None:
        raise ValueError("time_key contains unsafe characters")
    return normalized


def _parse_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BiasTilingError(f"Failed to read legend file: {path}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BiasTilingError(f"Legend file is not valid JSON: {path}") from exc

    if not isinstance(data, dict):
        raise BiasTilingError(f"Legend JSON must be an object: {path}")
    return data


def load_bias_legend(
    *,
    config_dir: str | Path | None = None,
    filename: str = DEFAULT_BIAS_LEGEND_FILENAME,
) -> dict[str, Any]:
    resolved_dir = (
        Path(config_dir).expanduser().resolve()
        if config_dir is not None
        else _resolve_config_dir()
    )
    path = resolved_dir / filename
    if not path.is_file():
        raise FileNotFoundError(f"Bias legend file not found: {path}")
    return _parse_json(path)


def _validate_legend_includes_zero(legend: dict[str, Any]) -> None:
    stops = legend.get("stops")
    if stops is None:
        stops = legend.get("colorStops")
    if not isinstance(stops, list) or len(stops) < 2:
        raise BiasTilingError("Bias legend must define at least 2 color stops")

    zero_present = False
    for stop in stops:
        if not isinstance(stop, dict):
            continue
        value = stop.get("value")
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(numeric) and np.isclose(numeric, 0.0):
            zero_present = True
            break

    if not zero_present:
        raise BiasTilingError("Bias legend must include a stop at value=0")


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


def _extract_surface_level_index(levels: np.ndarray, attrs: dict[str, Any]) -> int:
    units = str(attrs.get("units") or "").strip().lower()
    long_name = str(attrs.get("long_name") or "").strip().lower()

    if "surface" in long_name or units in {"1", ""}:
        return 0
    matches = np.where(
        np.isclose(levels.astype(np.float64, copy=False), 0.0, atol=1e-3)
    )[0]
    if matches.size:
        return int(matches[0])
    raise BiasTilingError("surface level requested but dataset has no surface level")


def _resolve_time_index(ds: xr.Dataset, valid_time: object) -> tuple[int, str]:
    if "time" not in ds.coords:
        raise BiasTilingError("Dataset missing required coordinate: time")

    values = np.asarray(ds["time"].values)
    if values.size == 0:
        raise BiasTilingError("time coordinate is empty")
    if not np.issubdtype(values.dtype, np.datetime64):
        raise BiasTilingError(f"time coordinate must be datetime64; got {values.dtype}")

    def parse_time(value: object) -> datetime:
        if isinstance(value, np.datetime64):
            text = np.datetime_as_string(value.astype("datetime64[s]"), unit="s")
            return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)

        if isinstance(value, datetime):
            dt = value
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)

        raw = str(value or "").strip()
        if raw == "":
            raise BiasTilingError("valid_time must not be empty")

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
                return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(
                    tzinfo=timezone.utc
                )
            except ValueError as exc:
                raise BiasTilingError(
                    "valid_time must be an ISO8601 timestamp or a tile version key"
                ) from exc

    dt = parse_time(valid_time)
    target = np.datetime64(dt.strftime("%Y-%m-%dT%H:%M:%S"), "s")

    values_s = values.astype("datetime64[s]")
    matches = np.where(values_s == target)[0]
    if matches.size == 0:
        raise BiasTilingError("valid_time not found in dataset")

    time_key = dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return int(matches[0]), _validate_time_key(time_key)


def _resolve_level_index(ds: xr.Dataset, level: object) -> tuple[int, str]:
    if "level" not in ds.coords:
        raise BiasTilingError("Dataset missing required coordinate: level")
    levels = np.asarray(ds["level"].values)
    if levels.size == 0:
        raise BiasTilingError("level coordinate is empty")

    raw = str(level or "").strip().lower()
    if raw in {"", "sfc", "surface"}:
        idx = _extract_surface_level_index(levels, dict(ds["level"].attrs))
        return idx, "sfc"

    try:
        numeric = float(re.sub(r"hpa$", "", raw).strip())
    except ValueError as exc:
        raise BiasTilingError(
            "level must be 'sfc' or a numeric pressure level"
        ) from exc
    if not np.isfinite(numeric):
        raise BiasTilingError("level must be a finite number")

    matches = np.where(
        np.isclose(levels.astype(np.float64, copy=False), numeric, atol=1e-3)
    )[0]
    if matches.size == 0:
        raise BiasTilingError("level not found in dataset")
    return int(matches[0]), str(
        int(numeric) if float(numeric).is_integer() else numeric
    )


def _select_observation_variable(ds: xr.Dataset, name: str) -> xr.DataArray:
    if name in ds.data_vars:
        return ds[name]
    vars_ = list(ds.data_vars)
    if len(vars_) == 1:
        return ds[vars_[0]]
    raise BiasTilingError(f"Observation variable {name!r} not found; available={vars_}")


def _normalize_observation_dataset(
    ds: xr.Dataset, *, target_time: np.datetime64
) -> xr.Dataset:
    # Bias only needs a single aligned time step; allow datasets without an explicit time axis.
    time_aliases = ("time", "Time", "TIME", "valid_time")
    has_time = any(name in ds.dims or name in ds.coords for name in time_aliases)

    out = ds
    if has_time and "time" in out.coords:
        raw = np.asarray(out["time"].values)
        if raw.size == 0:
            raise BiasTilingError("observation time coordinate is empty")
        if np.issubdtype(raw.dtype, np.datetime64):
            out = out.assign_coords(time=raw.astype("datetime64[s]"))

    if not has_time:
        out = out.expand_dims({"time": [np.datetime64(target_time, "s")]})
    return out


@dataclass(frozen=True)
class BiasTileGenerationResult:
    layer: str
    variable: str
    time: str
    level: str
    mode: BiasMode
    forecast_variable: str
    observation_variable: str
    output_dir: Path
    min_zoom: int
    max_zoom: int
    formats: tuple[str, ...]
    tiles_written: int


class BiasTileGenerator:
    def __init__(
        self,
        forecast_cube: DataCube,
        observation: xr.Dataset,
        *,
        mode: BiasMode = "difference",
        forecast_variable: str = DEFAULT_BIAS_FORECAST_VARIABLE,
        observation_variable: str = DEFAULT_BIAS_OBSERVATION_VARIABLE,
        variable: str = DEFAULT_BIAS_VARIABLE,
        layer: str = DEFAULT_BIAS_LAYER,
        legend_filename: str = DEFAULT_BIAS_LEGEND_FILENAME,
        time_method: str = "linear",
        spatial_method: str = "linear",
        relative_epsilon: float = 1e-6,
        relative_scale: float = 100.0,
    ) -> None:
        self._forecast_cube = forecast_cube
        self._observation = observation

        self._mode: BiasMode = mode
        self._forecast_variable = (forecast_variable or "").strip()
        self._observation_variable = (observation_variable or "").strip()
        self._variable = (variable or "").strip()
        self._layer = _validate_layer(layer)
        resolved_legend_filename = (
            legend_filename or ""
        ).strip() or DEFAULT_BIAS_LEGEND_FILENAME
        if (
            self._mode == "relative_error"
            and resolved_legend_filename == DEFAULT_BIAS_LEGEND_FILENAME
        ):
            resolved_legend_filename = DEFAULT_BIAS_RELATIVE_ERROR_LEGEND_FILENAME
        self._legend_filename = resolved_legend_filename
        self._time_method = (time_method or "").strip() or "linear"
        self._spatial_method = (spatial_method or "").strip() or "linear"
        self._relative_epsilon = float(relative_epsilon)
        self._relative_scale = float(relative_scale)

        if self._forecast_variable == "":
            raise ValueError("forecast_variable must not be empty")
        if self._observation_variable == "":
            raise ValueError("observation_variable must not be empty")
        if self._variable == "":
            raise ValueError("variable must not be empty")
        if self._time_method not in _INTERP_METHODS:
            raise ValueError(f"Unsupported time_method={self._time_method!r}")
        if self._spatial_method not in _INTERP_METHODS:
            raise ValueError(f"Unsupported spatial_method={self._spatial_method!r}")

    def _load_legend(self) -> dict[str, Any]:
        legend = load_bias_legend(filename=self._legend_filename)
        _validate_legend_includes_zero(legend)
        return legend

    def write_legend(self, output_dir: str | Path) -> Path:
        base = Path(output_dir).resolve()
        layer_dir = (base / self._layer).resolve()
        _ensure_relative_to_base(base_dir=base, path=layer_dir, label="layer")
        layer_dir.mkdir(parents=True, exist_ok=True)

        legend = normalize_legend_for_clients(self._load_legend())
        target = (layer_dir / "legend.json").resolve()
        _ensure_relative_to_base(base_dir=base, path=target, label="layer")
        target.write_text(
            json.dumps(legend, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return target

    def _derive_bias_cube(
        self, *, valid_time: object, level: object
    ) -> tuple[DataCube, str, str]:
        ds = self._forecast_cube.dataset
        if self._forecast_variable not in ds.data_vars:
            raise BiasTilingError(
                f"Forecast variable {self._forecast_variable!r} not found; available={list(ds.data_vars)}"
            )

        time_index, time_key = _resolve_time_index(ds, valid_time)
        level_index, level_key = _resolve_level_index(ds, level)
        if level_key != "sfc":
            raise BiasTilingError("Bias tiles currently support only level='sfc'")

        target_time = np.asarray(ds["time"].values).astype("datetime64[s]")[time_index]
        level_value = np.asarray(ds["level"].values)[level_index]

        forecast_var = ds[self._forecast_variable].isel(
            time=int(time_index), level=int(level_index)
        )
        if set(forecast_var.dims) != {"lat", "lon"}:
            raise BiasTilingError(
                f"Forecast slice must have dims {{'lat','lon'}}; got dims={list(forecast_var.dims)}"
            )
        forecast_var = forecast_var.transpose("lat", "lon")

        obs_ds = _normalize_observation_dataset(
            self._observation, target_time=target_time
        )
        obs_var = _select_observation_variable(obs_ds, self._observation_variable)

        # Normalize observation into DataCube form (resolves lat/lon/time aliases).
        obs_only = obs_var.to_dataset(name=obs_var.name)
        obs_only = _normalize_observation_dataset(obs_only, target_time=target_time)
        obs_cube = DataCube.from_dataset(obs_only)
        obs_var_norm = obs_cube.dataset[obs_var.name].isel(level=0)

        try:
            derived = derive_bias_grid(
                forecast_var,
                obs_var_norm,
                target_time=target_time,
                mode=self._mode,
                time_method=self._time_method,
                spatial_method=self._spatial_method,
                relative_epsilon=self._relative_epsilon,
                relative_scale=self._relative_scale,
            )
        except BiasDerivationError as exc:
            raise BiasTilingError(str(exc)) from exc

        bias = derived.bias
        bias.name = self._variable

        # Ensure the derived cube remains compatible with existing DataCube tiling stack.
        bias_4d = (
            bias.expand_dims(time=[target_time], level=[level_value])
            .transpose("time", "level", "lat", "lon")
            .astype(np.float32, copy=False)
        )
        bias_ds = xr.Dataset(
            {self._variable: bias_4d},
            coords={
                "time": ("time", np.asarray([target_time]).astype("datetime64[s]")),
                "level": ("level", np.asarray([level_value], dtype=np.float32)),
                "lat": ("lat", np.asarray(bias["lat"].values, dtype=np.float32)),
                "lon": ("lon", np.asarray(bias["lon"].values, dtype=np.float32)),
            },
        )
        bias_ds["level"].attrs = dict(ds["level"].attrs)
        cube = DataCube.from_dataset(bias_ds)
        return cube, time_key, level_key

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
    ) -> BiasTileGenerationResult:
        _ = self._load_legend()
        resolved_formats = _validate_tile_formats(formats)

        bias_cube, time_key, level_key = self._derive_bias_cube(
            valid_time=valid_time, level=level
        )

        result: TemperatureTileGenerationResult = TemperatureTileGenerator(
            bias_cube,
            variable=self._variable,
            layer=self._layer,
            legend_filename=self._legend_filename,
        ).generate(
            output_dir,
            valid_time=valid_time,
            level=level,
            min_zoom=min_zoom,
            max_zoom=max_zoom,
            tile_size=tile_size,
            formats=resolved_formats,
        )

        # Ensure a stable, user-facing legend with explicit zero point.
        self.write_legend(output_dir)

        return BiasTileGenerationResult(
            layer=result.layer,
            variable=result.variable,
            time=time_key,
            level=level_key,
            mode=self._mode,
            forecast_variable=self._forecast_variable,
            observation_variable=self._observation_variable,
            output_dir=result.output_dir,
            min_zoom=result.min_zoom,
            max_zoom=result.max_zoom,
            formats=result.formats,
            tiles_written=result.tiles_written,
        )
