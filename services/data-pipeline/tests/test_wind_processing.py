from __future__ import annotations

import numpy as np
import pytest
import xarray as xr


def _reference_wind_speed(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    return np.sqrt(u**2 + v**2)


def _reference_wind_dir(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    # Spec: wind_dir = atan2(u, v) converted to degrees and wrapped to [0, 360)
    deg = np.degrees(np.arctan2(u, v))
    return (deg + 360.0) % 360.0


def test_derive_wind_speed_and_dir_match_reference_script() -> None:
    from processing.wind import derive_wind_dir, derive_wind_speed

    rng = np.random.default_rng(42)
    u = rng.normal(size=(32, 16)).astype(np.float32)
    v = rng.normal(size=(32, 16)).astype(np.float32)

    u_da = xr.DataArray(
        u,
        dims=["y", "x"],
        coords={"y": np.arange(u.shape[0]), "x": np.arange(u.shape[1])},
        attrs={"units": "m/s"},
    )
    v_da = xr.DataArray(
        v,
        dims=["y", "x"],
        coords={"y": np.arange(v.shape[0]), "x": np.arange(v.shape[1])},
        attrs={"units": "m/s"},
    )

    speed = derive_wind_speed(u_da, v_da)
    direction = derive_wind_dir(u_da, v_da)

    np.testing.assert_allclose(
        speed.values, _reference_wind_speed(u, v), rtol=1e-6, atol=1e-6
    )
    np.testing.assert_allclose(
        direction.values, _reference_wind_dir(u, v), rtol=1e-6, atol=1e-6
    )


def test_wind_dir_is_bearing_from_north_clockwise() -> None:
    from processing.wind import derive_wind_dir, derive_wind_speed

    u = xr.DataArray(
        np.array([0.0, 1.0, 0.0, -1.0], dtype=np.float32),
        dims=["point"],
        coords={"point": np.arange(4)},
        attrs={"units": "m/s"},
    )
    v = xr.DataArray(
        np.array([1.0, 0.0, -1.0, 0.0], dtype=np.float32),
        dims=["point"],
        coords={"point": np.arange(4)},
        attrs={"units": "m/s"},
    )

    speed = derive_wind_speed(u, v)
    direction = derive_wind_dir(u, v)

    assert speed.attrs.get("units") == "m/s"
    np.testing.assert_allclose(speed.values, np.ones(4, dtype=np.float32))
    np.testing.assert_allclose(direction.values, np.array([0, 90, 180, 270]))
    assert "clockwise" in str(direction.attrs.get("comment", "")).lower()


def test_wind_derivation_propagates_nan() -> None:
    from processing.wind import derive_wind_dir, derive_wind_speed

    u = xr.DataArray(
        np.array([np.nan, 1.0], dtype=np.float32),
        dims=["point"],
        coords={"point": [0, 1]},
    )
    v = xr.DataArray(
        np.array([1.0, np.nan], dtype=np.float32),
        dims=["point"],
        coords={"point": [0, 1]},
    )

    speed = derive_wind_speed(u, v)
    direction = derive_wind_dir(u, v)

    assert np.isnan(speed.values[0])
    assert np.isnan(speed.values[1])
    assert np.isnan(direction.values[0])
    assert np.isnan(direction.values[1])


def test_wind_derivation_requires_matching_coordinates() -> None:
    from processing.wind import WindDerivationError, derive_wind_speed

    u = xr.DataArray(
        np.array([1.0, 2.0], dtype=np.float32), dims=["x"], coords={"x": [0, 1]}
    )
    v = xr.DataArray(
        np.array([1.0, 2.0], dtype=np.float32), dims=["x"], coords={"x": [0, 2]}
    )

    with pytest.raises(WindDerivationError, match="identical coordinates"):
        derive_wind_speed(u, v)


def test_derive_wind_speed_omits_units_when_components_units_differ() -> None:
    from processing.wind import derive_wind_speed

    u = xr.DataArray(
        np.array([1.0, 2.0], dtype=np.float32),
        dims=["x"],
        coords={"x": [0, 1]},
        attrs={"units": "m/s"},
    )
    v = xr.DataArray(
        np.array([1.0, 2.0], dtype=np.float32),
        dims=["x"],
        coords={"x": [0, 1]},
        attrs={"units": "m s-1"},
    )

    speed = derive_wind_speed(u, v)
    assert "units" not in speed.attrs


def test_maybe_add_wind_speed_dir_skips_when_component_missing() -> None:
    from processing.wind import maybe_add_wind_speed_dir

    ds = xr.Dataset(
        {"u": xr.DataArray(np.ones((2, 2), dtype=np.float32), dims=["y", "x"])}
    )
    out = maybe_add_wind_speed_dir(ds, u_name="u", v_name="v")
    assert out is ds


def test_maybe_add_wind_speed_dir_respects_existing_outputs() -> None:
    from processing.wind import maybe_add_wind_speed_dir

    ds = xr.Dataset(
        {
            "u": xr.DataArray(np.ones((2, 2), dtype=np.float32), dims=["y", "x"]),
            "v": xr.DataArray(np.ones((2, 2), dtype=np.float32), dims=["y", "x"]),
            "wind_speed": xr.DataArray(
                np.zeros((2, 2), dtype=np.float32), dims=["y", "x"]
            ),
        }
    )

    out = maybe_add_wind_speed_dir(ds, u_name="u", v_name="v", overwrite=False)
    assert out is ds

    out_overwrite = maybe_add_wind_speed_dir(ds, u_name="u", v_name="v", overwrite=True)
    assert out_overwrite is not ds
    assert out_overwrite["wind_speed"].values[0, 0] == pytest.approx(np.sqrt(2.0))


def test_datacube_normalize_adds_wind_speed_and_dir() -> None:
    from datacube.normalize import normalize_datacube_dataset

    ds = xr.Dataset(
        {
            "eastward_wind_10m": xr.DataArray(
                np.array([[[0.0, 1.0], [-1.0, 0.0]]], dtype=np.float32),
                dims=["time", "lat", "lon"],
                attrs={"units": "m/s"},
            ),
            "northward_wind_10m": xr.DataArray(
                np.array([[[1.0, 0.0], [0.0, -1.0]]], dtype=np.float32),
                dims=["time", "lat", "lon"],
                attrs={"units": "m/s"},
            ),
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.array([10.0, 11.0], dtype=np.float32),
            "lon": np.array([100.0, 101.0], dtype=np.float32),
        },
    )

    out = normalize_datacube_dataset(ds)
    assert "wind_speed" in out.data_vars
    assert "wind_dir" in out.data_vars
    assert out["wind_speed"].dims == ("time", "level", "lat", "lon")
    assert out["wind_dir"].dims == ("time", "level", "lat", "lon")

    np.testing.assert_allclose(
        out["wind_speed"].values[0, 0],
        np.array([[1.0, 1.0], [1.0, 1.0]], dtype=np.float32),
    )
    np.testing.assert_allclose(
        out["wind_dir"].values[0, 0],
        np.array([[0.0, 90.0], [270.0, 180.0]], dtype=np.float32),
    )
    assert out["wind_dir"].attrs.get("units") == "degree"
