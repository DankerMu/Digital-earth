from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest
import xarray as xr


def test_normalize_lat_lon_wraps_and_sorts_longitudes() -> None:
    from derived.bias import normalize_lat_lon

    lat = np.array([0.0], dtype=np.float32)
    lon = np.array([0.0, 90.0, 180.0, 270.0], dtype=np.float32)
    values = np.array([[0.0, 1.0, 2.0, 3.0]], dtype=np.float32)

    da = xr.DataArray(values, dims=("lat", "lon"), coords={"lat": lat, "lon": lon})
    normalized = normalize_lat_lon(da)

    assert normalized.dims == ("lat", "lon")
    assert normalized["lon"].values.tolist() == [-180.0, -90.0, 0.0, 90.0]
    # 180° wraps to -180° and 270° wraps to -90°, preserving original values.
    assert normalized.values.tolist() == [[2.0, 3.0, 0.0, 1.0]]


def test_derive_bias_grid_aligns_time_and_space() -> None:
    from derived.bias import derive_bias_grid

    target_time = np.datetime64("2026-01-01T00:30:00", "s")

    fc_lat = np.array([0.0, 1.0], dtype=np.float32)
    fc_lon = np.array([0.0, 1.0], dtype=np.float32)
    fc_values = np.array([[10.0, 11.0], [11.0, 12.0]], dtype=np.float32)
    forecast = xr.DataArray(
        fc_values, dims=("lat", "lon"), coords={"lat": fc_lat, "lon": fc_lon}
    )

    obs_lat = np.array([0.0, 0.5, 1.0], dtype=np.float32)
    obs_lon = np.array([0.0, 0.5, 1.0], dtype=np.float32)
    obs_time = np.array(
        ["2026-01-01T00:00:00", "2026-01-01T01:00:00"], dtype="datetime64[s]"
    )

    base = obs_lat[:, None] + obs_lon[None, :]
    obs_t0 = base.astype(np.float32)
    obs_t1 = (base + 2.0).astype(np.float32)
    observation = xr.DataArray(
        np.stack([obs_t0, obs_t1], axis=0),
        dims=("time", "lat", "lon"),
        coords={"time": obs_time, "lat": obs_lat, "lon": obs_lon},
    )

    result = derive_bias_grid(forecast, observation, target_time=target_time)
    bias = result.bias

    # At 00:30, observation interpolates to base + 1.0.
    # forecast is base + 10.0 => bias is constant 9.0.
    assert np.allclose(bias.values, 9.0, atol=1e-5)


def test_compute_bias_relative_error_masks_near_zero() -> None:
    from derived.bias import compute_bias

    forecast = xr.DataArray(
        np.array([[2.0]], dtype=np.float32),
        dims=("lat", "lon"),
        coords={"lat": [0.0], "lon": [0.0]},
    )
    observation = xr.DataArray(
        np.array([[0.0]], dtype=np.float32),
        dims=("lat", "lon"),
        coords={"lat": [0.0], "lon": [0.0]},
    )
    out = compute_bias(
        forecast,
        observation,
        mode="relative_error",
        relative_epsilon=0.1,
        relative_scale=100.0,
    )
    assert np.isnan(out.values[0, 0])


def test_align_observation_requires_lat_lon() -> None:
    from derived.bias import BiasDerivationError, align_observation_to_forecast

    forecast = xr.DataArray(
        np.array([[1.0]], dtype=np.float32),
        dims=("lat", "lon"),
        coords={"lat": [0.0], "lon": [0.0]},
    )
    observation = xr.DataArray(np.array([[1.0]], dtype=np.float32), dims=("x", "y"))

    with pytest.raises(BiasDerivationError, match="missing required dims"):
        align_observation_to_forecast(
            forecast,
            observation,
            target_time=np.datetime64(datetime.now(timezone.utc), "s"),
        )
