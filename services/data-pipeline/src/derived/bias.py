from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

import numpy as np
import xarray as xr


BiasMode = Literal["difference", "relative_error"]


class BiasDerivationError(RuntimeError):
    pass


_SUPPORTED_INTERP_METHODS: Final[set[str]] = {"linear", "nearest"}


def _interp_1d_indices(
    coord: np.ndarray, query: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    coord_f = coord.astype(np.float64, copy=False)
    query_f = query.astype(np.float64, copy=False)
    count = int(coord_f.size)
    right = np.searchsorted(coord_f, query_f, side="right").astype(np.int64)
    left = right - 1
    valid = (query_f >= coord_f[0]) & (query_f <= coord_f[-1])

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


def _nearest_indices(
    coord: np.ndarray, query: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    coord_f = coord.astype(np.float64, copy=False)
    query_f = query.astype(np.float64, copy=False)
    count = int(coord_f.size)
    right = np.searchsorted(coord_f, query_f, side="left").astype(np.int64)
    left = right - 1

    right = np.clip(right, 0, count - 1)
    left = np.clip(left, 0, count - 1)

    dist_left = np.abs(query_f - coord_f[left])
    dist_right = np.abs(query_f - coord_f[right])
    idx = np.where(dist_right < dist_left, right, left)

    valid = (query_f >= coord_f[0]) & (query_f <= coord_f[-1])
    return idx, valid


def _nearest_sample(
    lat: np.ndarray,
    lon: np.ndarray,
    grid: np.ndarray,
    *,
    lat_query: np.ndarray,
    lon_query: np.ndarray,
) -> np.ndarray:
    lat_idx, lat_ok = _nearest_indices(lat, lat_query)
    lon_idx, lon_ok = _nearest_indices(lon, lon_query)

    out = grid[np.ix_(lat_idx, lon_idx)].astype(np.float32, copy=False)
    mask = lat_ok[:, None] & lon_ok[None, :]
    out = np.where(mask, out, np.nan)
    return out


def _require_coord_1d(da: xr.DataArray, name: str) -> xr.DataArray:
    if name not in da.coords:
        raise BiasDerivationError(f"Missing required coordinate: {name}")
    coord = da[name]
    if coord.ndim != 1:
        raise BiasDerivationError(f"Coordinate {name!r} must be 1D")
    if coord.size == 0:
        raise BiasDerivationError(f"Coordinate {name!r} must not be empty")
    return coord


def _require_dims(da: xr.DataArray, dims: set[str]) -> None:
    present = set(da.dims)
    if not dims.issubset(present):
        raise BiasDerivationError(
            f"DataArray missing required dims={sorted(dims)}; got dims={list(da.dims)}"
        )


def _wrap_longitudes(values: np.ndarray) -> np.ndarray:
    lon_f = values.astype(np.float64, copy=False)
    if lon_f.size and np.nanmin(lon_f) >= 0.0 and np.nanmax(lon_f) > 180.0:
        wrapped = ((lon_f + 180.0) % 360.0) - 180.0
        return wrapped.astype(values.dtype, copy=False)
    return values


def normalize_lat_lon(da: xr.DataArray) -> xr.DataArray:
    """Return a copy of `da` with ascending lat/lon and lon wrapped to [-180, 180]."""

    _require_coord_1d(da, "lat")
    _require_coord_1d(da, "lon")

    out = da
    out = out.sortby("lat")

    lon = np.asarray(out["lon"].values)
    wrapped = _wrap_longitudes(lon)
    if not np.array_equal(wrapped, lon):
        out = out.assign_coords(lon=wrapped)
    out = out.sortby("lon")

    return out


def _coerce_time_coord(da: xr.DataArray) -> xr.DataArray:
    if "time" not in da.coords:
        return da
    raw = np.asarray(da["time"].values)
    if raw.size == 0:
        raise BiasDerivationError("time coordinate is empty")
    if not np.issubdtype(raw.dtype, np.datetime64):
        raise BiasDerivationError(
            f"time coordinate must be datetime64; got {raw.dtype}"
        )
    return da.assign_coords(time=raw.astype("datetime64[s]"))


def align_observation_to_forecast(
    forecast: xr.DataArray,
    observation: xr.DataArray,
    *,
    target_time: np.datetime64,
    time_method: str = "linear",
    spatial_method: str = "linear",
) -> xr.DataArray:
    """Interpolate observation onto forecast's (time, lat, lon) grid.

    Returns a 2D (lat, lon) DataArray aligned to `forecast`.
    """

    if time_method not in _SUPPORTED_INTERP_METHODS:
        raise ValueError(f"Unsupported time interpolation method: {time_method!r}")
    if spatial_method not in _SUPPORTED_INTERP_METHODS:
        raise ValueError(
            f"Unsupported spatial interpolation method: {spatial_method!r}"
        )

    _require_dims(forecast, {"lat", "lon"})
    _require_coord_1d(forecast, "lat")
    _require_coord_1d(forecast, "lon")

    forecast_norm = normalize_lat_lon(forecast)

    obs = observation
    _require_dims(obs, {"lat", "lon"})
    obs = normalize_lat_lon(obs)
    obs = _coerce_time_coord(obs)

    obs_2d: xr.DataArray
    if "time" in obs.dims:
        obs = obs.sortby("time")
        time_values = np.asarray(obs["time"].values).astype("datetime64[s]")
        if time_values.size == 0:
            raise BiasDerivationError("time coordinate is empty")

        target_time_s = np.datetime64(target_time, "s")
        times_i = time_values.astype("int64")
        target_i = int(
            np.asarray(target_time_s, dtype="datetime64[s]").astype("int64").item()
        )

        if time_method == "nearest" or time_values.size == 1:
            idx = int(np.argmin(np.abs(times_i - target_i)))
            obs_2d = obs.isel(time=idx)
        else:
            right = int(np.searchsorted(times_i, target_i, side="right"))
            if right <= 0:
                obs_2d = obs.isel(time=0)
            elif right >= int(times_i.size):
                obs_2d = obs.isel(time=int(times_i.size - 1))
            else:
                left = right - 1
                t0 = int(times_i[left])
                t1 = int(times_i[right])
                if t1 == t0:
                    obs_2d = obs.isel(time=left)
                else:
                    frac = float(target_i - t0) / float(t1 - t0)
                    v0 = obs.isel(time=left).astype(np.float32, copy=False)
                    v1 = obs.isel(time=right).astype(np.float32, copy=False)
                    obs_2d = (np.float32(1.0 - frac) * v0) + (np.float32(frac) * v1)
    else:
        obs_2d = obs.astype(np.float32, copy=False)

    obs_2d = obs_2d.transpose("lat", "lon")
    fc_lat = np.asarray(forecast_norm["lat"].values, dtype=np.float64)
    fc_lon = np.asarray(forecast_norm["lon"].values, dtype=np.float64)

    obs_lat = np.asarray(obs_2d["lat"].values, dtype=np.float64)
    obs_lon = np.asarray(obs_2d["lon"].values, dtype=np.float64)
    obs_grid = np.asarray(obs_2d.values, dtype=np.float32)

    if spatial_method == "nearest":
        sampled = _nearest_sample(
            obs_lat,
            obs_lon,
            obs_grid,
            lat_query=fc_lat,
            lon_query=fc_lon,
        )
    else:
        sampled = _bilinear_sample(
            obs_lat,
            obs_lon,
            obs_grid,
            lat_query=fc_lat,
            lon_query=fc_lon,
        )

    return xr.DataArray(
        sampled.astype(np.float32, copy=False),
        dims=("lat", "lon"),
        coords={"lat": forecast_norm["lat"].values, "lon": forecast_norm["lon"].values},
        attrs=dict(obs.attrs),
    )


def compute_bias(
    forecast: xr.DataArray,
    observation_on_forecast: xr.DataArray,
    *,
    mode: BiasMode = "difference",
    relative_epsilon: float = 1e-6,
    relative_scale: float = 100.0,
) -> xr.DataArray:
    """Compute bias from pre-aligned arrays.

    - difference: forecast - observation
    - relative_error: ((forecast - observation) / observation) * relative_scale
    """

    if mode not in {"difference", "relative_error"}:
        raise ValueError(f"Unsupported bias mode: {mode!r}")

    fc = forecast.astype(np.float32, copy=False)
    obs = observation_on_forecast.astype(np.float32, copy=False)

    if mode == "difference":
        out = fc - obs
        attrs = dict(fc.attrs)
        attrs.update({"bias_mode": "difference"})
        out.attrs = attrs
        return out.astype(np.float32, copy=False)

    eps = float(relative_epsilon)
    if not np.isfinite(eps) or eps < 0.0:
        raise ValueError("relative_epsilon must be a finite number >= 0")

    denom = obs.where(np.abs(obs) > np.float32(eps))
    out = (fc - obs) / denom
    out = out * np.float32(relative_scale)

    attrs = dict(fc.attrs)
    attrs.update(
        {
            "bias_mode": "relative_error",
            "relative_scale": float(relative_scale),
            "relative_epsilon": float(relative_epsilon),
            "units": "%",
        }
    )
    out.attrs = attrs
    return out.astype(np.float32, copy=False)


@dataclass(frozen=True)
class BiasGridResult:
    bias: xr.DataArray
    forecast_grid: xr.DataArray
    observation_grid: xr.DataArray


def derive_bias_grid(
    forecast_grid: xr.DataArray,
    observation: xr.DataArray,
    *,
    target_time: np.datetime64,
    mode: BiasMode = "difference",
    time_method: str = "linear",
    spatial_method: str = "linear",
    relative_epsilon: float = 1e-6,
    relative_scale: float = 100.0,
) -> BiasGridResult:
    """Align observation to forecast and compute the bias grid (lat, lon)."""

    forecast_norm = normalize_lat_lon(forecast_grid)
    obs_on_fc = align_observation_to_forecast(
        forecast_norm,
        observation,
        target_time=target_time,
        time_method=time_method,
        spatial_method=spatial_method,
    )
    bias = compute_bias(
        forecast_norm,
        obs_on_fc,
        mode=mode,
        relative_epsilon=relative_epsilon,
        relative_scale=relative_scale,
    )
    return BiasGridResult(
        bias=bias,
        forecast_grid=forecast_norm.astype(np.float32, copy=False),
        observation_grid=obs_on_fc.astype(np.float32, copy=False),
    )
