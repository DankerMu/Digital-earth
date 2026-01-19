from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import xarray as xr


def test_resolve_precip_type_temp_threshold_c_handles_bad_configs(
    tmp_path: Path,
) -> None:
    from processing.precip_type import DEFAULT_PRECIP_TYPE_TEMP_THRESHOLD_C
    from processing.precip_type import resolve_precip_type_temp_threshold_c

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    environ = {
        "DIGITAL_EARTH_ENV": "dev",
        "DIGITAL_EARTH_CONFIG_DIR": str(config_dir),
    }

    assert resolve_precip_type_temp_threshold_c(environ) == pytest.approx(
        DEFAULT_PRECIP_TYPE_TEMP_THRESHOLD_C
    )

    (config_dir / "dev.json").write_text("{", encoding="utf-8")
    assert resolve_precip_type_temp_threshold_c(environ) == pytest.approx(
        DEFAULT_PRECIP_TYPE_TEMP_THRESHOLD_C
    )

    (config_dir / "dev.json").write_text(json.dumps(["not-a-dict"]), encoding="utf-8")
    assert resolve_precip_type_temp_threshold_c(environ) == pytest.approx(
        DEFAULT_PRECIP_TYPE_TEMP_THRESHOLD_C
    )

    (config_dir / "dev.json").write_text(
        json.dumps({"pipeline": "not-a-dict"}), encoding="utf-8"
    )
    assert resolve_precip_type_temp_threshold_c(environ) == pytest.approx(
        DEFAULT_PRECIP_TYPE_TEMP_THRESHOLD_C
    )


def test_resolve_precip_type_temp_threshold_c_prefers_env_var(tmp_path: Path) -> None:
    from processing.precip_type import PRECIP_TYPE_THRESHOLD_ENV
    from processing.precip_type import resolve_precip_type_temp_threshold_c

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "dev.json").write_text(
        json.dumps({"pipeline": {"precip_type_temp_threshold_c": 2.0}}),
        encoding="utf-8",
    )

    environ = {
        "DIGITAL_EARTH_ENV": "dev",
        "DIGITAL_EARTH_CONFIG_DIR": str(config_dir),
        PRECIP_TYPE_THRESHOLD_ENV: "1.25",
    }
    assert resolve_precip_type_temp_threshold_c(environ) == pytest.approx(1.25)

    environ[PRECIP_TYPE_THRESHOLD_ENV] = "nope"
    assert resolve_precip_type_temp_threshold_c(environ) == pytest.approx(2.0)


def test_derive_precip_type_supports_time_lat_lon_and_unit_inference() -> None:
    from processing.precip_type import derive_precip_type

    ds = xr.Dataset(
        {
            "air_temperature": xr.DataArray(
                np.array([[[270.0]]], dtype=np.float32),  # inferred Kelvin => -3.15°C
                dims=["time", "lat", "lon"],
            )
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.array([10.0], dtype=np.float32),
            "lon": np.array([100.0], dtype=np.float32),
        },
    )

    out = derive_precip_type(ds, temp_threshold_c=0.0)
    assert out is not None
    assert out.dims == ("time", "lat", "lon")
    assert out.values[0, 0, 0] == pytest.approx(1.0)  # snow


def test_derive_precip_type_converts_kelvin_units_to_celsius() -> None:
    from processing.precip_type import derive_precip_type

    ds = xr.Dataset(
        {
            "air_temperature": xr.DataArray(
                np.array([[[272.15, 274.15]]], dtype=np.float32),  # -1°C, +1°C
                dims=["time", "lat", "lon"],
                attrs={"units": "K"},
            )
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.array([10.0], dtype=np.float32),
            "lon": np.array([100.0, 101.0], dtype=np.float32),
        },
    )

    out = derive_precip_type(ds, temp_threshold_c=0.0)
    assert out is not None
    assert out.values[0, 0, 0] == pytest.approx(1.0)  # -1°C => snow
    assert out.values[0, 0, 1] == pytest.approx(0.0)  # +1°C => rain


def test_derive_precip_type_returns_none_for_missing_required_dims() -> None:
    from processing.precip_type import derive_precip_type

    ds = xr.Dataset(
        {
            "air_temperature": xr.DataArray(
                np.array([1.0], dtype=np.float32),
                dims=["time"],
                attrs={"units": "°C"},
            )
        },
        coords={"time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")},
    )
    assert derive_precip_type(ds, temp_threshold_c=0.0) is None


def test_derive_precip_type_returns_none_on_shape_mismatch() -> None:
    from processing.precip_type import derive_precip_type

    ds_bad_ptype = xr.Dataset(
        {
            "ptype": xr.DataArray(
                np.array([[1.0]], dtype=np.float32),
                dims=["time", "lat"],  # missing lon dimension
            ),
            "air_temperature": xr.DataArray(
                np.array([[[273.15]]], dtype=np.float32),
                dims=["time", "lat", "lon"],
                attrs={"units": "K"},
            ),
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.array([10.0], dtype=np.float32),
            "lon": np.array([100.0], dtype=np.float32),
        },
    )
    assert derive_precip_type(ds_bad_ptype, temp_threshold_c=0.0) is None

    ds_bad_temp = xr.Dataset(
        {
            "ptype": xr.DataArray(
                np.array([[[np.nan]]], dtype=np.float32),
                dims=["time", "lat", "lon"],
            ),
            "air_temperature": xr.DataArray(
                np.array([[273.15]], dtype=np.float32),
                dims=["time", "lat"],  # missing lon dimension
                attrs={"units": "K"},
            ),
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.array([10.0], dtype=np.float32),
            "lon": np.array([100.0], dtype=np.float32),
        },
    )
    assert derive_precip_type(ds_bad_temp, temp_threshold_c=0.0) is None


def test_ensure_precip_type_is_noop_when_present() -> None:
    from processing.precip_type import ensure_precip_type

    ds = xr.Dataset(
        {
            "precip_type": xr.DataArray(
                np.array([[[0.0]]], dtype=np.float32), dims=["time", "lat", "lon"]
            )
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.array([10.0], dtype=np.float32),
            "lon": np.array([100.0], dtype=np.float32),
        },
    )

    out = ensure_precip_type(ds, temp_threshold_c=0.0)
    assert out is ds


def test_derive_precip_type_allows_empty_candidate_lists() -> None:
    from processing.precip_type import derive_precip_type

    ds = xr.Dataset(
        {
            "air_temperature": xr.DataArray(
                np.array([[[273.15]]], dtype=np.float32),
                dims=["time", "lat", "lon"],
                attrs={"units": "K"},
            )
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.array([10.0], dtype=np.float32),
            "lon": np.array([100.0], dtype=np.float32),
        },
    )
    assert (
        derive_precip_type(
            ds, temp_threshold_c=0.0, ptype_names=(), temperature_names=()
        )
        is None
    )


def test_coerce_temperature_to_celsius_unknown_units_are_passed_through() -> None:
    from processing.precip_type import derive_precip_type

    ds = xr.Dataset(
        {
            "air_temperature": xr.DataArray(
                np.array([[[-5.0]]], dtype=np.float32),
                dims=["time", "lat", "lon"],
                attrs={"units": "F"},
            )
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.array([10.0], dtype=np.float32),
            "lon": np.array([100.0], dtype=np.float32),
        },
    )

    out = derive_precip_type(ds, temp_threshold_c=0.0)
    assert out is not None
    assert out.values[0, 0, 0] == pytest.approx(1.0)
