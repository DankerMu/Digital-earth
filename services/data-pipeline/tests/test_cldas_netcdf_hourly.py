from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import xarray as xr


def _write_hourly_netcdf(
    path: Path,
    *,
    dims: tuple[str, str, str] = ("time", "lat", "lon"),
    tmp: np.ndarray,
    rhu: np.ndarray,
    pre: np.ndarray,
) -> None:
    time_dim, lat_dim, lon_dim = dims
    ds = xr.Dataset(
        {
            "TMP": xr.DataArray(tmp, dims=[time_dim, lat_dim, lon_dim]),
            "RHU": xr.DataArray(rhu, dims=[time_dim, lat_dim, lon_dim]),
            "PRE": xr.DataArray(pre, dims=[time_dim, lat_dim, lon_dim]),
        },
        coords={
            time_dim: np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            lat_dim: np.array([10.0, 11.0], dtype=np.float32),
            lon_dim: np.array([100.0, 101.0, 102.0], dtype=np.float32),
        },
    )
    for name in ("TMP", "RHU", "PRE"):
        ds[name].attrs["_FillValue"] = np.float32(-9999.0)
    ds.to_netcdf(path, engine="h5netcdf")


def test_import_success_writes_internal_dataset_and_index(tmp_path: Path) -> None:
    from cldas.netcdf_hourly import import_cldas_netcdf_hourly

    source_path = tmp_path / "cldas.nc"
    tmp = np.array(
        [[[0.0, -9999.0, 2.0], [3.0, 4.0, 5.0]]],
        dtype=np.float32,
    )
    rhu = np.array(
        [[[50.0, -9999.0, 60.0], [70.0, 80.0, 90.0]]],
        dtype=np.float32,
    )
    pre = np.array(
        [[[0.0, 10.0, -9999.0], [5.0, 15.0, 20.0]]],
        dtype=np.float32,
    )
    _write_hourly_netcdf(source_path, tmp=tmp, rhu=rhu, pre=pre)

    out_dir = tmp_path / "out"
    result = import_cldas_netcdf_hourly(
        source_path,
        output_dir=out_dir,
        product="CLDAS-V2.0",
        resolution="0.0625",
        engine="h5netcdf",
    )

    assert result.dataset_path.is_file()
    assert result.file_index_path.is_file()
    assert result.collection_index_path.is_file()
    assert result.times == ["2026-01-01T00:00:00Z"]
    assert set(result.variables) == {
        "air_temperature",
        "precipitation_amount",
        "relative_humidity",
    }

    with xr.open_dataset(result.dataset_path, engine="h5netcdf") as ds_out:
        assert set(ds_out.dims) == {"time", "lat", "lon"}
        assert set(ds_out.data_vars) == set(result.variables)

        t2m = ds_out["air_temperature"].values
        assert np.isfinite(t2m).all()
        assert t2m[0, 0, 0] == pytest.approx(273.15, abs=1e-4)
        assert t2m[0, 0, 1] == pytest.approx(274.15, abs=1e-4)
        assert ds_out["air_temperature"].attrs.get("units") == "K"

        rh = ds_out["relative_humidity"].values
        assert rh[0, 0, 1] == pytest.approx(-9999.0, abs=1e-4)
        assert ds_out["relative_humidity"].attrs.get("units") == "%"

        pr = ds_out["precipitation_amount"].values
        assert pr[0, 0, 1] == pytest.approx(0.01, abs=1e-6)
        assert pr[0, 0, 2] == pytest.approx(0.0, abs=1e-6)
        assert ds_out["precipitation_amount"].attrs.get("units") == "m"

    file_index = json.loads(result.file_index_path.read_text(encoding="utf-8"))
    assert file_index["product"] == "CLDAS-V2.0"
    assert file_index["resolution"] == "0.0625"
    assert file_index["times"] == ["2026-01-01T00:00:00Z"]
    assert "air_temperature" in file_index["variables"]

    collection_index = json.loads(
        result.collection_index_path.read_text(encoding="utf-8")
    )
    assert collection_index["product"] == "CLDAS-V2.0"
    assert collection_index["resolution"] == "0.0625"
    assert collection_index["items"][0]["time"] == "2026-01-01T00:00:00Z"


def test_parser_normalizes_lat_lon_aliases(tmp_path: Path) -> None:
    from cldas.netcdf_hourly import parse_cldas_netcdf_hourly

    source_path = tmp_path / "cldas_alias.nc"
    tmp = np.zeros((1, 2, 3), dtype=np.float32)
    rhu = np.zeros((1, 2, 3), dtype=np.float32)
    pre = np.zeros((1, 2, 3), dtype=np.float32)
    _write_hourly_netcdf(
        source_path,
        dims=("time", "latitude", "longitude"),
        tmp=tmp,
        rhu=rhu,
        pre=pre,
    )

    ds = parse_cldas_netcdf_hourly(
        source_path,
        product="CLDAS-V2.0",
        resolution="0.0625",
        engine="h5netcdf",
    )
    assert set(ds.dims) == {"time", "lat", "lon"}


def test_missing_source_variable_raises(tmp_path: Path) -> None:
    from cldas.errors import CldasNetcdfStructureError
    from cldas.netcdf_hourly import parse_cldas_netcdf_hourly

    source_path = tmp_path / "missing_pre.nc"
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")
    lat = np.array([10.0, 11.0], dtype=np.float32)
    lon = np.array([100.0, 101.0, 102.0], dtype=np.float32)
    tmp = xr.DataArray(
        np.zeros((1, 2, 3), dtype=np.float32), dims=["time", "lat", "lon"]
    )
    tmp.attrs["_FillValue"] = np.float32(-9999.0)
    rhu = xr.DataArray(
        np.zeros((1, 2, 3), dtype=np.float32), dims=["time", "lat", "lon"]
    )
    rhu.attrs["_FillValue"] = np.float32(-9999.0)
    ds = xr.Dataset(
        {"TMP": tmp, "RHU": rhu}, coords={"time": time, "lat": lat, "lon": lon}
    )
    ds.to_netcdf(source_path, engine="h5netcdf")

    with pytest.raises(CldasNetcdfStructureError, match="Missing required variables"):
        parse_cldas_netcdf_hourly(
            source_path,
            product="CLDAS-V2.0",
            resolution="0.0625",
            engine="h5netcdf",
        )


def test_missing_required_dims_raises(tmp_path: Path) -> None:
    from cldas.errors import CldasNetcdfStructureError
    from cldas.netcdf_hourly import parse_cldas_netcdf_hourly

    source_path = tmp_path / "bad_dims.nc"
    ds = xr.Dataset(
        {
            "TMP": xr.DataArray(
                np.zeros((1, 2, 3), dtype=np.float32), dims=["t", "y", "x"]
            )
        },
        coords={"t": [0], "y": [0, 1], "x": [0, 1, 2]},
    )
    ds.to_netcdf(source_path, engine="h5netcdf")

    with pytest.raises(
        CldasNetcdfStructureError, match="Missing required dimension/coordinate"
    ):
        parse_cldas_netcdf_hourly(
            source_path,
            product="CLDAS-V2.0",
            resolution="0.0625",
            engine="h5netcdf",
        )


def test_interpolate_strategy_raises_when_field_all_missing(tmp_path: Path) -> None:
    from cldas.errors import CldasNetcdfMissingDataError
    from cldas.netcdf_hourly import parse_cldas_netcdf_hourly

    source_path = tmp_path / "all_missing.nc"
    tmp = np.full((1, 2, 3), -9999.0, dtype=np.float32)
    rhu = np.zeros((1, 2, 3), dtype=np.float32)
    pre = np.zeros((1, 2, 3), dtype=np.float32)
    _write_hourly_netcdf(source_path, tmp=tmp, rhu=rhu, pre=pre)

    with pytest.raises(CldasNetcdfMissingDataError, match="Missing values remain"):
        parse_cldas_netcdf_hourly(
            source_path,
            product="CLDAS-V2.0",
            resolution="0.0625",
            engine="h5netcdf",
        )


def test_open_error_is_wrapped(tmp_path: Path) -> None:
    from cldas.errors import CldasNetcdfOpenError
    from cldas.netcdf_hourly import parse_cldas_netcdf_hourly

    with pytest.raises(CldasNetcdfOpenError, match="Failed to open NetCDF"):
        parse_cldas_netcdf_hourly(
            tmp_path / "missing.nc",
            product="CLDAS-V2.0",
            resolution="0.0625",
            engine="h5netcdf",
        )


def test_normalize_dims_raises_when_lat_is_coord_not_dim(tmp_path: Path) -> None:
    from cldas.errors import CldasNetcdfStructureError
    from cldas.netcdf_hourly import parse_cldas_netcdf_hourly

    source_path = tmp_path / "coord_lat.nc"
    ds = xr.Dataset(
        {
            "TMP": xr.DataArray(
                np.zeros((1, 2, 3), dtype=np.float32), dims=["time", "y", "lon"]
            ),
            "RHU": xr.DataArray(
                np.zeros((1, 2, 3), dtype=np.float32), dims=["time", "y", "lon"]
            ),
            "PRE": xr.DataArray(
                np.zeros((1, 2, 3), dtype=np.float32), dims=["time", "y", "lon"]
            ),
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "y": np.array([0, 1], dtype=np.int32),
            "lon": np.array([100.0, 101.0, 102.0], dtype=np.float32),
            "lat": ("y", np.array([10.0, 11.0], dtype=np.float32)),
        },
    )
    ds.to_netcdf(source_path, engine="h5netcdf")

    with pytest.raises(
        CldasNetcdfStructureError, match="must exist after normalization"
    ):
        parse_cldas_netcdf_hourly(
            source_path,
            product="CLDAS-V2.0",
            resolution="0.0625",
            engine="h5netcdf",
        )


def test_rejects_2d_lat_lon_coordinates(tmp_path: Path) -> None:
    from cldas.errors import CldasNetcdfStructureError
    from cldas.netcdf_hourly import parse_cldas_netcdf_hourly

    source_path = tmp_path / "lat2d.nc"
    lat2d = np.array([[10.0, 10.0, 10.0], [11.0, 11.0, 11.0]], dtype=np.float32)
    lon2d = np.array([[100.0, 101.0, 102.0], [100.0, 101.0, 102.0]], dtype=np.float32)
    ds = xr.Dataset(
        {
            "TMP": xr.DataArray(
                np.zeros((1, 2, 3), dtype=np.float32), dims=["time", "lat", "lon"]
            ),
            "RHU": xr.DataArray(
                np.zeros((1, 2, 3), dtype=np.float32), dims=["time", "lat", "lon"]
            ),
            "PRE": xr.DataArray(
                np.zeros((1, 2, 3), dtype=np.float32), dims=["time", "lat", "lon"]
            ),
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": (("lat", "lon"), lat2d),
            "lon": (("lat", "lon"), lon2d),
        },
    )
    ds.to_netcdf(source_path, engine="h5netcdf")

    with pytest.raises(CldasNetcdfStructureError, match="Only 1D lat/lon"):
        parse_cldas_netcdf_hourly(
            source_path,
            product="CLDAS-V2.0",
            resolution="0.0625",
            engine="h5netcdf",
        )


def test_rejects_non_datetime_time_coordinate(tmp_path: Path) -> None:
    from cldas.errors import CldasNetcdfStructureError
    from cldas.netcdf_hourly import parse_cldas_netcdf_hourly

    source_path = tmp_path / "time_int.nc"
    ds = xr.Dataset(
        {
            "TMP": xr.DataArray(
                np.zeros((1, 2, 3), dtype=np.float32), dims=["time", "lat", "lon"]
            ),
            "RHU": xr.DataArray(
                np.zeros((1, 2, 3), dtype=np.float32), dims=["time", "lat", "lon"]
            ),
            "PRE": xr.DataArray(
                np.zeros((1, 2, 3), dtype=np.float32), dims=["time", "lat", "lon"]
            ),
        },
        coords={
            "time": np.array([0], dtype=np.int32),
            "lat": np.array([10.0, 11.0], dtype=np.float32),
            "lon": np.array([100.0, 101.0, 102.0], dtype=np.float32),
        },
    )
    ds.to_netcdf(source_path, engine="h5netcdf")

    with pytest.raises(
        CldasNetcdfStructureError, match="time coordinate must be datetime64"
    ):
        parse_cldas_netcdf_hourly(
            source_path,
            product="CLDAS-V2.0",
            resolution="0.0625",
            engine="h5netcdf",
        )


def test_missing_value_list_is_treated_as_missing(tmp_path: Path) -> None:
    from cldas.netcdf_hourly import parse_cldas_netcdf_hourly

    source_path = tmp_path / "missing_list.nc"
    tmp = np.array([[[0.0, 1.0, 2.0], [3.0, 4.0, 5.0]]], dtype=np.float32)
    rhu = np.zeros((1, 2, 3), dtype=np.float32)
    pre = np.array([[[0.0, -9999.0, 10.0], [0.0, 0.0, 0.0]]], dtype=np.float32)

    ds = xr.Dataset(
        {
            "TMP": xr.DataArray(tmp, dims=["time", "lat", "lon"]),
            "RHU": xr.DataArray(rhu, dims=["time", "lat", "lon"]),
            "PRE": xr.DataArray(pre, dims=["time", "lat", "lon"]),
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.array([10.0, 11.0], dtype=np.float32),
            "lon": np.array([100.0, 101.0, 102.0], dtype=np.float32),
        },
    )
    ds["PRE"].attrs["missing_value"] = np.array([-9999.0], dtype=np.float32)
    ds.to_netcdf(source_path, engine="h5netcdf")

    out = parse_cldas_netcdf_hourly(
        source_path,
        product="CLDAS-V2.0",
        resolution="0.0625",
        engine="h5netcdf",
    )
    assert out["precipitation_amount"].values[0, 0, 1] == pytest.approx(0.0, abs=1e-6)


def test_interpolate_fills_edges_without_scipy(tmp_path: Path) -> None:
    from cldas.netcdf_hourly import parse_cldas_netcdf_hourly

    source_path = tmp_path / "edge_missing.nc"
    tmp = np.array(
        [[[-9999.0, 1.0, 2.0], [3.0, 4.0, 5.0]]],
        dtype=np.float32,
    )
    rhu = np.zeros((1, 2, 3), dtype=np.float32)
    pre = np.zeros((1, 2, 3), dtype=np.float32)
    _write_hourly_netcdf(source_path, tmp=tmp, rhu=rhu, pre=pre)

    out = parse_cldas_netcdf_hourly(
        source_path,
        product="CLDAS-V2.0",
        resolution="0.0625",
        engine="h5netcdf",
    )

    t2m = out["air_temperature"].values
    assert np.isfinite(t2m).all()
    assert t2m[0, 0, 0] == pytest.approx(274.15, abs=1e-4)


def test_write_internal_files_supports_multiple_times(tmp_path: Path) -> None:
    from cldas.netcdf_hourly import write_cldas_internal_files

    times = np.array(
        ["2026-01-01T00:00:00", "2026-01-01T01:00:00"], dtype="datetime64[s]"
    )
    ds = xr.Dataset(
        {
            "air_temperature": xr.DataArray(
                np.zeros((2, 2, 3), dtype=np.float32), dims=["time", "lat", "lon"]
            ),
            "relative_humidity": xr.DataArray(
                np.zeros((2, 2, 3), dtype=np.float32), dims=["time", "lat", "lon"]
            ),
            "precipitation_amount": xr.DataArray(
                np.zeros((2, 2, 3), dtype=np.float32), dims=["time", "lat", "lon"]
            ),
        },
        coords={
            "time": times,
            "lat": np.array([10.0, 11.0], dtype=np.float32),
            "lon": np.array([100.0, 101.0, 102.0], dtype=np.float32),
        },
    )

    result = write_cldas_internal_files(
        ds,
        output_dir=tmp_path / "out",
        product="CLDAS-V2.0",
        resolution="0.0625",
        source_path=tmp_path / "source.nc",
        engine="h5netcdf",
    )
    assert "_" in result.dataset_path.stem


def test_invalid_collection_index_raises(tmp_path: Path) -> None:
    from cldas.errors import CldasNetcdfWriteError
    from cldas.netcdf_hourly import write_cldas_internal_files

    ds = xr.Dataset(
        {
            "air_temperature": xr.DataArray(
                np.zeros((1, 2, 3), dtype=np.float32), dims=["time", "lat", "lon"]
            ),
            "relative_humidity": xr.DataArray(
                np.zeros((1, 2, 3), dtype=np.float32), dims=["time", "lat", "lon"]
            ),
            "precipitation_amount": xr.DataArray(
                np.zeros((1, 2, 3), dtype=np.float32), dims=["time", "lat", "lon"]
            ),
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.array([10.0, 11.0], dtype=np.float32),
            "lon": np.array([100.0, 101.0, 102.0], dtype=np.float32),
        },
    )

    out_root = tmp_path / "out" / "CLDAS-V2.0" / "0.0625"
    out_root.mkdir(parents=True)
    (out_root / "index.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(CldasNetcdfWriteError, match="Failed to read collection index"):
        write_cldas_internal_files(
            ds,
            output_dir=tmp_path / "out",
            product="CLDAS-V2.0",
            resolution="0.0625",
            source_path=tmp_path / "source.nc",
            engine="h5netcdf",
        )


def test_source_scale_factor_add_offset_is_applied(tmp_path: Path) -> None:
    from cldas.config import CldasMappingConfig
    from cldas.netcdf_hourly import parse_cldas_netcdf_hourly

    source_path = tmp_path / "packed.nc"
    physical = np.array([[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]], dtype=np.float32)
    ds = xr.Dataset(
        {"TMP": xr.DataArray(physical, dims=["time", "lat", "lon"])},
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.array([10.0, 11.0], dtype=np.float32),
            "lon": np.array([100.0, 101.0, 102.0], dtype=np.float32),
        },
    )
    ds["TMP"].encoding["dtype"] = np.int16
    ds["TMP"].encoding["scale_factor"] = 0.1
    ds["TMP"].encoding["add_offset"] = 1.0
    ds.to_netcdf(source_path, engine="h5netcdf")

    mapping_config = CldasMappingConfig.model_validate(
        {
            "schema_version": 1,
            "defaults": {
                "scale": 1.0,
                "offset": 0.0,
                "missing": {"strategy": "fill_value", "fill_value": -9999.0},
            },
            "products": {
                "TEST": {
                    "resolutions": {
                        "R1": {
                            "variables": [
                                {
                                    "source_var": "TMP",
                                    "internal_var": "tmp",
                                    "unit": "1",
                                }
                            ]
                        }
                    }
                }
            },
        }
    )

    out = parse_cldas_netcdf_hourly(
        source_path,
        product="TEST",
        resolution="R1",
        mapping_config=mapping_config,
        engine="h5netcdf",
    )

    assert out["tmp"].values == pytest.approx(physical, abs=1e-6)


def test_mapping_scale_zero_is_not_treated_as_default(tmp_path: Path) -> None:
    from cldas.config import CldasMappingConfig
    from cldas.netcdf_hourly import parse_cldas_netcdf_hourly

    source_path = tmp_path / "scale_zero.nc"
    tmp = np.array([[[10.0, 20.0, 30.0], [40.0, 50.0, 60.0]]], dtype=np.float32)
    ds = xr.Dataset(
        {"TMP": xr.DataArray(tmp, dims=["time", "lat", "lon"])},
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.array([10.0, 11.0], dtype=np.float32),
            "lon": np.array([100.0, 101.0, 102.0], dtype=np.float32),
        },
    )
    ds["TMP"].attrs["_FillValue"] = np.float32(-9999.0)
    ds.to_netcdf(source_path, engine="h5netcdf")

    mapping_config = CldasMappingConfig.model_validate(
        {
            "schema_version": 1,
            "defaults": {
                "scale": 1.0,
                "offset": 0.0,
                "missing": {"strategy": "fill_value", "fill_value": -9999.0},
            },
            "products": {
                "TEST": {
                    "resolutions": {
                        "R1": {
                            "variables": [
                                {
                                    "source_var": "TMP",
                                    "internal_var": "tmp",
                                    "unit": "1",
                                    "scale": 0.0,
                                    "offset": 5.0,
                                }
                            ]
                        }
                    }
                }
            },
        }
    )

    out = parse_cldas_netcdf_hourly(
        source_path,
        product="TEST",
        resolution="R1",
        mapping_config=mapping_config,
        engine="h5netcdf",
    )
    assert out["tmp"].values == pytest.approx(
        np.full_like(tmp, 5.0, dtype=np.float32), abs=1e-6
    )
