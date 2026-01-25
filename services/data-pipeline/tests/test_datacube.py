from __future__ import annotations

import types
from pathlib import Path

import numpy as np
import pytest
import xarray as xr


def _surface_dataset(*, missing_value: float = -9999.0) -> xr.Dataset:
    values = np.array(
        [[[1.0, missing_value, 3.0], [4.0, 5.0, missing_value]]], dtype=np.float32
    )
    da = xr.DataArray(values, dims=["time", "latitude", "longitude"], name="t2m")
    da.attrs["_FillValue"] = np.float32(missing_value)
    da.attrs["missing_value"] = np.array([missing_value], dtype=np.float32)
    return xr.Dataset(
        {"t2m": da},
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "latitude": np.array([10.0, 11.0], dtype=np.float32),
            "longitude": np.array([100.0, 101.0, 102.0], dtype=np.float32),
        },
    )


def test_normalize_surface_dataset_adds_level_and_standardizes_missing() -> None:
    from datacube.core import DataCube

    ds = _surface_dataset()
    cube = DataCube.from_dataset(ds)
    out = cube.dataset

    assert set(out.dims) == {"time", "level", "lat", "lon"}
    assert out["level"].values.tolist() == [0.0]
    assert out["t2m"].dims == ("time", "level", "lat", "lon")
    assert out["t2m"].dtype == np.float32
    assert np.isnan(out["t2m"].values[0, 0, 0, 1])
    assert np.isnan(out["t2m"].values[0, 0, 1, 2])
    assert "_FillValue" not in out["t2m"].attrs
    assert "missing_value" not in out["t2m"].attrs


def test_normalize_converts_level_units_to_hpa() -> None:
    from datacube.normalize import normalize_datacube_dataset

    ds = xr.Dataset(
        {
            "t": xr.DataArray(
                np.zeros((1, 2, 2, 3), dtype=np.float32),
                dims=["time", "plev", "latitude", "longitude"],
            )
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "plev": xr.DataArray(
                np.array([100000.0, 85000.0], dtype=np.float32),
                dims=["plev"],
                attrs={"units": "Pa"},
            ),
            "latitude": np.array([10.0, 11.0], dtype=np.float32),
            "longitude": np.array([100.0, 101.0, 102.0], dtype=np.float32),
        },
    )

    out = normalize_datacube_dataset(ds)
    assert out["level"].attrs.get("units") == "hPa"
    assert out["level"].values.tolist() == [1000.0, 850.0]


def test_normalize_rejects_unsupported_dims() -> None:
    from datacube.errors import DataCubeValidationError
    from datacube.normalize import normalize_datacube_dataset

    ds = xr.Dataset(
        {
            "t": xr.DataArray(
                np.zeros((1, 2, 3, 4), dtype=np.float32),
                dims=["time", "lat", "lon", "step"],
            )
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.array([10.0, 11.0], dtype=np.float32),
            "lon": np.array([100.0, 101.0, 102.0], dtype=np.float32),
            "step": np.array([0, 1, 2, 3], dtype=np.int32),
        },
    )

    with pytest.raises(DataCubeValidationError, match="unsupported dims"):
        normalize_datacube_dataset(ds)


def test_normalize_converts_temperature_and_precipitation_units() -> None:
    from datacube.normalize import normalize_datacube_dataset

    ds = xr.Dataset(
        {
            "air_temperature": xr.DataArray(
                np.array([[[273.15, 274.15], [275.15, np.nan]]], dtype=np.float32),
                dims=["time", "lat", "lon"],
                attrs={"units": "K"},
            ),
            "precipitation_amount": xr.DataArray(
                np.array([[[0.001, 0.0], [0.01, np.nan]]], dtype=np.float32),
                dims=["time", "lat", "lon"],
                attrs={"units": "m"},
            ),
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.array([10.0, 11.0], dtype=np.float32),
            "lon": np.array([100.0, 101.0], dtype=np.float32),
        },
    )

    out = normalize_datacube_dataset(ds)
    assert out["air_temperature"].attrs.get("units") == "°C"
    assert out["air_temperature"].dtype == np.float32
    assert out["air_temperature"].values[0, 0, 0, 0] == pytest.approx(0.0, abs=1e-3)
    assert out["air_temperature"].values[0, 0, 0, 1] == pytest.approx(1.0, abs=1e-3)

    assert out["precipitation_amount"].attrs.get("units") == "mm"
    assert out["precipitation_amount"].dtype == np.float32
    assert out["precipitation_amount"].values[0, 0, 0, 0] == pytest.approx(
        1.0, abs=1e-6
    )
    assert out["precipitation_amount"].values[0, 0, 1, 0] == pytest.approx(
        10.0, abs=1e-6
    )


def test_normalize_does_not_convert_non_precip_meter_variables() -> None:
    from datacube.normalize import normalize_datacube_dataset

    ds = xr.Dataset(
        {
            "geopotential_height": xr.DataArray(
                np.array([[[123.0, 456.0], [789.0, 101.0]]], dtype=np.float32),
                dims=["time", "lat", "lon"],
                attrs={"units": "m"},
            )
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.array([10.0, 11.0], dtype=np.float32),
            "lon": np.array([100.0, 101.0], dtype=np.float32),
        },
    )

    out = normalize_datacube_dataset(ds)
    assert out["geopotential_height"].attrs.get("units") == "m"
    assert out["geopotential_height"].values[0, 0, 0, 0] == pytest.approx(123.0)


def test_normalize_standardizes_wind_units_without_changing_values() -> None:
    from datacube.normalize import normalize_datacube_dataset

    ds = xr.Dataset(
        {
            "eastward_wind_10m": xr.DataArray(
                np.array([[[1.5, 2.0], [3.0, 4.0]]], dtype=np.float32),
                dims=["time", "lat", "lon"],
                attrs={"units": "m s-1"},
            ),
            "tp": xr.DataArray(
                np.array([[[0.001, 0.002], [0.0, 0.01]]], dtype=np.float32),
                dims=["time", "lat", "lon"],
                attrs={"units": "m"},
            ),
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.array([10.0, 11.0], dtype=np.float32),
            "lon": np.array([100.0, 101.0], dtype=np.float32),
        },
    )

    out = normalize_datacube_dataset(ds)
    assert out["eastward_wind_10m"].attrs.get("units") == "m/s"
    assert out["eastward_wind_10m"].values[0, 0, 0, 0] == pytest.approx(1.5)

    assert out["tp"].attrs.get("units") == "mm"
    assert out["tp"].values[0, 0, 0, 1] == pytest.approx(2.0, abs=1e-6)


def test_decode_netcdf_and_write_roundtrip(tmp_path: Path) -> None:
    from datacube.decoder import decode_datacube
    from datacube.inspect import inspect_datacube
    from datacube.storage import open_datacube

    source = tmp_path / "source.nc"
    ds = _surface_dataset()
    ds.to_netcdf(source, engine="h5netcdf")

    cube = decode_datacube(source)
    out_path = cube.write(tmp_path / "cube.nc")
    assert out_path.is_file()

    with open_datacube(out_path) as ds_out:
        assert set(ds_out.dims) == {"time", "level", "lat", "lon"}
        assert "t2m" in ds_out.data_vars
        assert np.isnan(ds_out["t2m"].values).any()

    summary = inspect_datacube(out_path)
    assert summary["dims"]["level"] == 1
    assert summary["times"] == ["2026-01-01T00:00:00Z"]
    assert summary["variables"]["t2m"]["nan_count"] == 2


def test_decode_grib_filters_surface_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    from datacube.decoder import decode_grib

    lat = np.array([10.0, 11.0], dtype=np.float32)
    lon = np.array([100.0, 101.0, 102.0], dtype=np.float32)
    valid_time = np.datetime64("2026-01-01T00:00:00")

    def make_ds(
        name: str, values: np.ndarray, *, units: str | None = None
    ) -> xr.Dataset:
        da = xr.DataArray(values, dims=["latitude", "longitude"], name=name)
        if units is not None:
            da.attrs["units"] = units
        return xr.Dataset(
            {name: da},
            coords={
                "valid_time": valid_time,
                "latitude": lat,
                "longitude": lon,
            },
        )

    temp_ds = make_ds("t2m", np.full((2, 3), 273.15, dtype=np.float32), units="K")
    tcc_ds = make_ds("tcc", np.full((2, 3), 0.5, dtype=np.float32))
    tp_ds = make_ds("tp", np.full((2, 3), 0.001, dtype=np.float32), units="m")
    u10_ds = make_ds("u10", np.full((2, 3), 2.0, dtype=np.float32), units="m/s")
    v10_ds = make_ds("v10", np.full((2, 3), 3.0, dtype=np.float32), units="m/s")

    calls: list[dict[str, object]] = []

    def fake_open_dataset(*args, **kwargs):  # noqa: ANN001,ANN002
        backend_kwargs = kwargs.get("backend_kwargs") or {}
        calls.append(
            {
                "engine": kwargs.get("engine"),
                "backend_kwargs": backend_kwargs,
            }
        )
        keys = dict(backend_kwargs.get("filter_by_keys") or {})
        short = keys.get("shortName")
        if short == "2t":
            return temp_ds
        if short == "tcc":
            return tcc_ds
        if short == "tp":
            return tp_ds
        if short == "10u":
            return u10_ds
        if short == "10v":
            return v10_ds
        return xr.Dataset()

    monkeypatch.setattr("datacube.decoder.xr.open_dataset", fake_open_dataset)

    cube = decode_grib("dummy.grib")
    out = cube.dataset
    assert set(out.dims) == {"time", "level", "lat", "lon"}
    assert "t2m" in out.data_vars
    assert "tcc" in out.data_vars
    assert "tp" in out.data_vars
    assert "eastward_wind_10m" in out.data_vars
    assert "northward_wind_10m" in out.data_vars
    assert "precipitation_amount" in out.data_vars
    assert "wind_speed" in out.data_vars

    short_names = [
        (call.get("backend_kwargs") or {}).get("filter_by_keys", {}).get("shortName")
        for call in calls
    ]
    assert set(short_names) >= {"2t", "tcc", "tp", "10u", "10v"}
    assert all(call.get("engine") == "cfgrib" for call in calls)


def test_decode_grib_filters_humidity_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datacube.decoder import decode_grib

    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")
    levels = np.array([850.0, 700.0], dtype=np.float32)
    lat = np.array([10.0, 11.0], dtype=np.float32)
    lon = np.array([100.0, 101.0, 102.0], dtype=np.float32)

    rh_ds = xr.Dataset(
        {
            "r": xr.DataArray(
                np.full((1, levels.size, lat.size, lon.size), 50.0, dtype=np.float32),
                dims=["valid_time", "isobaricInhPa", "latitude", "longitude"],
                attrs={"units": "%"},
            )
        },
        coords={
            "valid_time": time,
            "isobaricInhPa": levels,
            "latitude": lat,
            "longitude": lon,
        },
    )

    calls: list[dict[str, object]] = []

    def fake_open_dataset(*args, **kwargs):  # noqa: ANN001,ANN002
        backend_kwargs = kwargs.get("backend_kwargs") or {}
        calls.append(
            {
                "engine": kwargs.get("engine"),
                "backend_kwargs": backend_kwargs,
            }
        )
        keys = dict(backend_kwargs.get("filter_by_keys") or {})
        short = keys.get("shortName")
        if short == "r":
            return rh_ds
        return xr.Dataset()

    monkeypatch.setattr("datacube.decoder.xr.open_dataset", fake_open_dataset)

    cube = decode_grib("dummy.grib", subset="humidity")
    out = cube.dataset
    assert set(out.dims) == {"time", "level", "lat", "lon"}
    assert "r" in out.data_vars

    short_names = [
        (call.get("backend_kwargs") or {}).get("filter_by_keys", {}).get("shortName")
        for call in calls
    ]
    assert "r" in set(short_names)
    assert all(call.get("engine") == "cfgrib" for call in calls)


def test_decode_grib_humidity_subset_aliases_and_no_variables_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datacube.decoder import decode_grib
    from datacube.errors import DataCubeDecodeError

    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")
    levels = np.array([850.0], dtype=np.float32)
    lat = np.array([10.0, 11.0], dtype=np.float32)
    lon = np.array([100.0, 101.0, 102.0], dtype=np.float32)

    rh_ds = xr.Dataset(
        {
            "r": xr.DataArray(
                np.full((1, levels.size, lat.size, lon.size), 50.0, dtype=np.float32),
                dims=["valid_time", "isobaricInhPa", "latitude", "longitude"],
                attrs={"units": "%"},
            )
        },
        coords={
            "valid_time": time,
            "isobaricInhPa": levels,
            "latitude": lat,
            "longitude": lon,
        },
    )

    calls: list[dict[str, object]] = []

    def fake_open_dataset(*args, **kwargs):  # noqa: ANN001,ANN002
        backend_kwargs = kwargs.get("backend_kwargs") or {}
        calls.append(
            {
                "engine": kwargs.get("engine"),
                "backend_kwargs": backend_kwargs,
            }
        )
        keys = dict(backend_kwargs.get("filter_by_keys") or {})
        short = keys.get("shortName")
        level_type = keys.get("typeOfLevel")
        if short == "r" and level_type == "isobaricInhPa":
            return rh_ds
        return xr.Dataset()

    monkeypatch.setattr("datacube.decoder.xr.open_dataset", fake_open_dataset)

    cube = decode_grib("dummy.grib", subset="rh")
    assert "r" in cube.dataset.data_vars

    cube = decode_grib("dummy.grib", subset="isobaric-humidity")
    assert "r" in cube.dataset.data_vars

    def fake_open_dataset_empty(*args, **kwargs):  # noqa: ANN001,ANN002
        backend_kwargs = kwargs.get("backend_kwargs") or {}
        calls.append(
            {
                "engine": kwargs.get("engine"),
                "backend_kwargs": backend_kwargs,
            }
        )
        return xr.Dataset()

    monkeypatch.setattr("datacube.decoder.xr.open_dataset", fake_open_dataset_empty)

    with pytest.raises(DataCubeDecodeError, match="no supported humidity variables"):
        decode_grib("dummy.grib", subset="humidity")

    short_names = [
        (call.get("backend_kwargs") or {}).get("filter_by_keys", {}).get("shortName")
        for call in calls
    ]
    assert "r" in set(short_names)


def test_decode_grib_rejects_invalid_subset() -> None:
    from datacube.decoder import decode_grib

    with pytest.raises(ValueError, match="subset must be one of"):
        decode_grib("dummy.grib", subset="nope")


def test_decode_grib_filters_isobaric_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datacube.decoder import decode_grib

    time = np.datetime64("2026-01-01T00:00:00")
    levels = np.array([850.0, 700.0], dtype=np.float32)
    lat = np.array([10.0, 11.0], dtype=np.float32)
    lon = np.array([100.0, 101.0, 102.0], dtype=np.float32)

    def make_pl(name: str) -> xr.Dataset:
        da = xr.DataArray(
            np.zeros((levels.size, lat.size, lon.size), dtype=np.float32),
            dims=["isobaricInhPa", "latitude", "longitude"],
            name=name,
        )
        return xr.Dataset(
            {name: da},
            coords={
                "valid_time": time,
                "isobaricInhPa": levels,
                "latitude": lat,
                "longitude": lon,
            },
        )

    t_ds = make_pl("t")
    u_ds = make_pl("u")
    v_ds = make_pl("v")

    def fake_open_dataset(*args, **kwargs):  # noqa: ANN001,ANN002
        backend_kwargs = kwargs.get("backend_kwargs") or {}
        keys = dict(backend_kwargs.get("filter_by_keys") or {})
        short = keys.get("shortName")
        if short == "t":
            return t_ds
        if short == "u":
            return u_ds
        if short == "v":
            return v_ds
        return xr.Dataset()

    monkeypatch.setattr("datacube.decoder.xr.open_dataset", fake_open_dataset)

    cube = decode_grib("dummy.grib", subset="isobaric")
    out = cube.dataset
    assert set(out.dims) == {"time", "level", "lat", "lon"}
    assert "t" in out.data_vars
    assert "u" in out.data_vars
    assert "v" in out.data_vars


def test_decode_grib_surface_falls_back_to_height_above_ground_wind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datacube.decoder import decode_grib

    lat = np.array([10.0, 11.0], dtype=np.float32)
    lon = np.array([100.0, 101.0, 102.0], dtype=np.float32)

    temp_ds = xr.Dataset(
        {
            "t2m": xr.DataArray(
                np.full((2, 3), 273.15, dtype=np.float32),
                dims=["latitude", "longitude"],
                attrs={"units": "K"},
            )
        },
        coords={
            "valid_time": np.datetime64("2026-01-01T00:00:00"),
            "latitude": lat,
            "longitude": lon,
        },
    )

    wind_u10_ds = xr.Dataset(
        {
            "u10": xr.DataArray(
                np.full((2, 3), 2.0, dtype=np.float32),
                dims=["latitude", "longitude"],
                attrs={"units": "m/s"},
            )
        },
        coords={
            "time": np.datetime64("2026-01-01T00:00:00"),
            "step": np.timedelta64(0, "h"),
            "latitude": lat,
            "longitude": lon,
        },
    )

    wind_u_ds = xr.Dataset(
        {
            "u": xr.DataArray(
                np.full((2, 3), 2.0, dtype=np.float32),
                dims=["latitude", "longitude"],
                attrs={"units": "m/s"},
            )
        },
        coords={
            "time": np.datetime64("2026-01-01T00:00:00"),
            "step": np.timedelta64(0, "h"),
            "latitude": lat,
            "longitude": lon,
        },
    )
    wind_v_ds = xr.Dataset(
        {
            "v": xr.DataArray(
                np.full((2, 3), 3.0, dtype=np.float32),
                dims=["latitude", "longitude"],
                attrs={"units": "m/s"},
            )
        },
        coords={
            "time": np.datetime64("2026-01-01T00:00:00"),
            "step": np.timedelta64(0, "h"),
            "latitude": lat,
            "longitude": lon,
        },
    )

    def fake_open_dataset(*args, **kwargs):  # noqa: ANN001,ANN002
        backend_kwargs = kwargs.get("backend_kwargs") or {}
        keys = dict(backend_kwargs.get("filter_by_keys") or {})
        short = keys.get("shortName")
        if short == "2t":
            return temp_ds
        if short == "10u":
            return wind_u10_ds
        if short == "u" and keys.get("typeOfLevel") == "heightAboveGround":
            return wind_u_ds
        if short == "v" and keys.get("typeOfLevel") == "heightAboveGround":
            return wind_v_ds
        return xr.Dataset()

    monkeypatch.setattr("datacube.decoder.xr.open_dataset", fake_open_dataset)

    cube = decode_grib("dummy.grib", subset="surface")
    out = cube.dataset
    assert "t2m" in out.data_vars
    assert "u" in out.data_vars
    assert "v" in out.data_vars


def test_decode_grib_missing_dependency_is_wrapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datacube.decoder import decode_datacube
    from datacube.errors import DataCubeDecodeError

    def fake_open_dataset(*args, **kwargs):  # noqa: ANN001,ANN002
        raise ValueError("unrecognized engine cfgrib")

    monkeypatch.setattr("datacube.decoder.xr.open_dataset", fake_open_dataset)

    path = tmp_path / "source.grib2"
    path.write_bytes(b"fake")

    with pytest.raises(DataCubeDecodeError, match="requires the optional dependency"):
        decode_datacube(path, source_format="grib")


def test_write_zarr_uses_to_zarr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datacube.storage import write_datacube

    ds = xr.Dataset(
        {
            "t": xr.DataArray(
                np.zeros((1, 1, 2, 3), dtype=np.float32),
                dims=["time", "level", "lat", "lon"],
            )
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "level": np.array([0.0], dtype=np.float32),
            "lat": np.array([10.0, 11.0], dtype=np.float32),
            "lon": np.array([100.0, 101.0, 102.0], dtype=np.float32),
        },
    )

    # Fake zarr/numcodecs so the test does not depend on optional runtime deps.
    dummy_zarr = types.ModuleType("zarr")

    class DummyBlosc:
        BITSHUFFLE = 2

        def __init__(self, *, cname: str, clevel: int, shuffle: int) -> None:
            self.cname = cname
            self.clevel = clevel
            self.shuffle = shuffle

    dummy_numcodecs = types.ModuleType("numcodecs")
    dummy_numcodecs.Blosc = DummyBlosc

    monkeypatch.setitem(__import__("sys").modules, "zarr", dummy_zarr)
    monkeypatch.setitem(__import__("sys").modules, "numcodecs", dummy_numcodecs)

    called = {}

    def fake_to_zarr(self, path, *, mode, encoding, consolidated):  # noqa: ANN001
        called["path"] = Path(path)
        called["mode"] = mode
        called["encoding"] = encoding
        called["consolidated"] = consolidated

    monkeypatch.setattr(xr.Dataset, "to_zarr", fake_to_zarr, raising=True)

    out = write_datacube(ds, tmp_path / "cube.zarr", format="zarr")
    assert out.is_dir()
    assert called["mode"] == "w"
    assert called["consolidated"] is True
    assert "t" in called["encoding"]
    assert called["encoding"]["t"]["chunks"] == (1, 1, 2, 3)


def test_datacube_open_loads_and_normalizes(tmp_path: Path) -> None:
    from datacube.core import DataCube

    source = tmp_path / "source.nc"
    ds = _surface_dataset()
    ds.to_netcdf(source, engine="h5netcdf")

    cube = DataCube.open(source)
    out = cube.dataset
    assert set(out.dims) == {"time", "level", "lat", "lon"}


def test_datacube_validate_raises_for_missing_dims() -> None:
    from datacube.core import DataCube
    from datacube.errors import DataCubeValidationError

    cube = DataCube(dataset=xr.Dataset())
    with pytest.raises(DataCubeValidationError, match="missing required dimensions"):
        cube.validate()
