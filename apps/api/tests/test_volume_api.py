from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from fastapi import HTTPException
from fastapi.testclient import TestClient

from volume.cloud_density import DEFAULT_CLOUD_DENSITY_LAYER
from volume.pack import decode_volume_pack
from routes import volume as volume_routes


def _write_config(dir_path: Path, env: str, data: dict) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{env}.json").write_text(json.dumps(data), encoding="utf-8")


def _base_config() -> dict:
    return {
        "api": {
            "host": "0.0.0.0",
            "port": 8000,
            "debug": True,
            "cors_origins": [],
            "rate_limit": {"enabled": False},
        },
        "pipeline": {"workers": 2, "batch_size": 100},
        "web": {"api_base_url": "http://localhost:8000"},
        "database": {"host": "localhost", "port": 5432, "name": "digital_earth"},
        "redis": {"host": "localhost", "port": 6379},
        "storage": {"tiles_bucket": "tiles", "raw_bucket": "raw"},
    }


def _make_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    volume_data_dir: Path | None = None,
) -> TestClient:
    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    if volume_data_dir is not None:
        monkeypatch.setenv("DIGITAL_EARTH_VOLUME_DATA_DIR", str(volume_data_dir))
    else:
        monkeypatch.delenv("DIGITAL_EARTH_VOLUME_DATA_DIR", raising=False)

    from config import get_settings
    from main import create_app

    get_settings.cache_clear()
    return TestClient(create_app())


def _write_cloud_density_slice(
    path: Path,
    *,
    valid_time: str,
    level: int,
    lat: list[float],
    lon: list[float],
    values: np.ndarray,
) -> None:
    data = values.astype(np.float32, copy=False).reshape((1, 1, len(lat), len(lon)))
    ds = xr.Dataset(
        {
            "cloud_density": (("time", "level", "lat", "lon"), data),
        },
        coords={
            "time": [np.datetime64(valid_time)],
            "level": [float(level)],
            "lat": np.asarray(lat, dtype=np.float64),
            "lon": np.asarray(lon, dtype=np.float64),
        },
        attrs={"schema": "digital-earth.volume-slice", "schema_version": 1},
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(path, engine="h5netcdf")


def test_volume_rejects_bbox_area_over_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path)
    response = client.get(
        "/api/v1/volume",
        params={
            "bbox": "0,0,20,20,0,1",
            "levels": "300,500",
            "res": "1000",
        },
    )
    assert response.status_code == 400


def test_volume_rejects_res_below_minimum(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path)
    response = client.get(
        "/api/v1/volume",
        params={
            "bbox": "0,0,0.1,0.1,0,1",
            "levels": "300,500",
            "res": "10",
        },
    )
    assert response.status_code == 400


def test_volume_rejects_output_size_over_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path)
    response = client.get(
        "/api/v1/volume",
        params={
            "bbox": "0,0,2,2,0,1",
            "levels": "300,400,500,600",
            "res": "100",
        },
    )
    assert response.status_code == 400


def test_volume_returns_volume_pack_for_cloud_density_slices(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base_dir = tmp_path / "volume-data"
    time_key = "20260101T000000Z"
    valid_time = "2026-01-01T00:00:00"

    time_dir = base_dir / DEFAULT_CLOUD_DENSITY_LAYER / time_key
    lat = [0.0, 0.1, 0.2]
    lon = [0.0, 0.1, 0.2]

    values_300 = np.arange(9, dtype=np.float32).reshape((3, 3))
    values_500 = values_300 + 100.0
    _write_cloud_density_slice(
        time_dir / "300.nc",
        valid_time=valid_time,
        level=300,
        lat=lat,
        lon=lon,
        values=values_300,
    )
    _write_cloud_density_slice(
        time_dir / "500.nc",
        valid_time=valid_time,
        level=500,
        lat=lat,
        lon=lon,
        values=values_500,
    )

    client = _make_client(monkeypatch, tmp_path, volume_data_dir=base_dir)
    response = client.get(
        "/api/v1/volume",
        params={
            "bbox": "0,0,0.2,0.2,0,12000",
            "levels": "300,500",
            "res": "11132",
            "valid_time": "2026-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/octet-stream")
    assert response.content[:4] == b"VOLP"

    header, array = decode_volume_pack(response.content)
    assert header["shape"] == [2, 3, 3]
    assert header["dtype"] == "float32"
    assert header["variable"] == "cloud_density"
    assert header["levels"] == [300, 500]
    assert header["bbox"]["west"] == 0.0
    assert header["bbox"]["east"] == 0.2
    assert header["valid_time"] == "2026-01-01T00:00:00Z"

    assert array.shape == (2, 3, 3)
    assert np.allclose(array[0], values_300)
    assert np.allclose(array[1], values_500)


def test_volume_returns_503_when_data_dir_not_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path, volume_data_dir=None)
    response = client.get(
        "/api/v1/volume",
        params={"bbox": "0,0,0.1,0.1,0,1", "levels": "300", "res": "1000"},
    )
    assert response.status_code == 503


def test_volume_returns_404_when_data_dir_not_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(
        monkeypatch, tmp_path, volume_data_dir=tmp_path / "nonexistent"
    )
    response = client.get(
        "/api/v1/volume",
        params={"bbox": "0,0,0.1,0.1,0,1", "levels": "300", "res": "1000"},
    )
    assert response.status_code == 404


def test_volume_returns_404_when_layer_not_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base_dir = tmp_path / "volume-data"
    base_dir.mkdir(parents=True)
    client = _make_client(monkeypatch, tmp_path, volume_data_dir=base_dir)
    response = client.get(
        "/api/v1/volume",
        params={"bbox": "0,0,0.1,0.1,0,1", "levels": "300", "res": "1000"},
    )
    assert response.status_code == 404


def test_volume_returns_404_when_level_not_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base_dir = tmp_path / "volume-data"
    time_key = "20260101T000000Z"
    time_dir = base_dir / DEFAULT_CLOUD_DENSITY_LAYER / time_key
    time_dir.mkdir(parents=True)
    client = _make_client(monkeypatch, tmp_path, volume_data_dir=base_dir)
    response = client.get(
        "/api/v1/volume",
        params={
            "bbox": "0,0,0.1,0.1,0,1",
            "levels": "999",
            "res": "1000",
            "valid_time": "2026-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 404


def test_volume_returns_400_for_invalid_bbox_format(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path)
    response = client.get(
        "/api/v1/volume",
        params={"bbox": "invalid", "levels": "300", "res": "1000"},
    )
    assert response.status_code == 400


def test_volume_returns_400_for_invalid_levels_format(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path)
    response = client.get(
        "/api/v1/volume",
        params={"bbox": "0,0,0.1,0.1,0,1", "levels": "abc", "res": "1000"},
    )
    assert response.status_code == 400


def test_volume_returns_400_for_invalid_valid_time_format(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base_dir = tmp_path / "volume-data"
    base_dir.mkdir(parents=True)
    client = _make_client(monkeypatch, tmp_path, volume_data_dir=base_dir)
    response = client.get(
        "/api/v1/volume",
        params={
            "bbox": "0,0,0.1,0.1,0,1",
            "levels": "300",
            "res": "1000",
            "valid_time": "not-a-date",
        },
    )
    assert response.status_code == 400


def test_volume_uses_latest_time_when_valid_time_not_provided(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base_dir = tmp_path / "volume-data"
    time_key = "20260115T120000Z"
    valid_time = "2026-01-15T12:00:00"

    time_dir = base_dir / DEFAULT_CLOUD_DENSITY_LAYER / time_key
    lat = [0.0, 0.1, 0.2]
    lon = [0.0, 0.1, 0.2]
    values = np.ones((3, 3), dtype=np.float32)

    _write_cloud_density_slice(
        time_dir / "300.nc",
        valid_time=valid_time,
        level=300,
        lat=lat,
        lon=lon,
        values=values,
    )

    client = _make_client(monkeypatch, tmp_path, volume_data_dir=base_dir)
    response = client.get(
        "/api/v1/volume",
        params={"bbox": "0,0,0.2,0.2,0,12000", "levels": "300", "res": "11132"},
    )
    assert response.status_code == 200

    header, _ = decode_volume_pack(response.content)
    assert header["valid_time"] == "2026-01-15T12:00:00Z"


def test_volume_returns_400_for_bbox_east_less_than_west(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path)
    response = client.get(
        "/api/v1/volume",
        params={"bbox": "10,0,5,0.1,0,1", "levels": "300", "res": "1000"},
    )
    assert response.status_code == 400


def test_volume_returns_400_for_non_finite_res(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path)
    response = client.get(
        "/api/v1/volume",
        params={"bbox": "0,0,0.1,0.1,0,1", "levels": "300", "res": "inf"},
    )
    assert response.status_code == 400


def test_estimate_grid_size_rejects_non_finite_grid() -> None:
    bbox = volume_routes.BBox(
        west=0.0,
        south=float("nan"),
        east=1.0,
        north=1.0,
        bottom=0.0,
        top=1.0,
    )
    with pytest.raises(ValueError, match="finite grid size"):
        volume_routes._estimate_grid_size(bbox, res_m=1000.0)


def test_estimate_grid_size_handles_overflow_error() -> None:
    bbox = volume_routes.BBox(
        west=0.0,
        south=0.0,
        east=0.1,
        north=0.1,
        bottom=0.0,
        top=1.0,
    )
    with pytest.raises(ValueError, match="finite grid size"):
        volume_routes._estimate_grid_size(bbox, res_m=1e-323)


def test_bounding_slice_monotonic_handles_empty_and_single_coord() -> None:
    assert volume_routes._bounding_slice_monotonic(np.array([]), 0.0, 1.0) == slice(
        0, 0
    )
    assert volume_routes._bounding_slice_monotonic(np.array([42.0]), 0.0, 1.0) == slice(
        0, 1
    )


def test_bounding_slice_monotonic_handles_descending_coords() -> None:
    coord = np.array([3.0, 2.0, 1.0, 0.0])
    assert volume_routes._bounding_slice_monotonic(coord, 0.5, 1.5) == slice(1, 4)
    assert volume_routes._bounding_slice_monotonic(coord, 2.0, -1.0) == slice(0, 0)


def test_read_cloud_density_coords_raises_when_missing_cloud_density_var(
    tmp_path: Path,
) -> None:
    path = tmp_path / "missing-var.nc"
    ds = xr.Dataset(
        {"temperature": (("lat", "lon"), np.zeros((2, 2), dtype=np.float32))},
        coords={"lat": [0.0, 1.0], "lon": [0.0, 1.0]},
    )
    ds.to_netcdf(path, engine="h5netcdf")

    with pytest.raises(HTTPException) as excinfo:
        volume_routes._read_cloud_density_coords(path)
    assert excinfo.value.status_code == 500
    assert excinfo.value.detail == "Slice missing cloud_density"


def test_read_cloud_density_coords_raises_when_dims_not_lat_lon(tmp_path: Path) -> None:
    path = tmp_path / "wrong-dims.nc"
    ds = xr.Dataset(
        {
            "cloud_density": (
                ("time", "lat", "lon"),
                np.zeros((2, 2, 2), dtype=np.float32),
            )
        },
        coords={
            "time": [np.datetime64("2026-01-01"), np.datetime64("2026-01-02")],
            "lat": [0.0, 1.0],
            "lon": [0.0, 1.0],
        },
    )
    ds.to_netcdf(path, engine="h5netcdf")

    with pytest.raises(HTTPException) as excinfo:
        volume_routes._read_cloud_density_coords(path)
    assert excinfo.value.status_code == 500
    assert excinfo.value.detail == "Slice must have lat/lon dimensions"


def test_read_cloud_density_coords_raises_when_coords_non_monotonic(
    tmp_path: Path,
) -> None:
    path = tmp_path / "non-monotonic-coords.nc"
    lat = [0.0, 0.2, 0.1]
    lon = [0.0, 0.1, 0.2]
    values = np.ones((len(lat), len(lon)), dtype=np.float32)
    _write_cloud_density_slice(
        path,
        valid_time="2026-01-01T00:00:00",
        level=300,
        lat=lat,
        lon=lon,
        values=values,
    )

    with pytest.raises(HTTPException) as excinfo:
        volume_routes._read_cloud_density_coords(path)
    assert excinfo.value.status_code == 500
    assert excinfo.value.detail == "Slice coordinates are not monotonic"


def test_read_cloud_density_grid_subsets_using_lat_lon_bounds(tmp_path: Path) -> None:
    path = tmp_path / "subset.nc"
    lat = [0.0, 1.0, 2.0, 3.0, 4.0]
    lon = [10.0, 11.0, 12.0, 13.0, 14.0]
    values = np.arange(len(lat) * len(lon), dtype=np.float32).reshape(
        (len(lat), len(lon))
    )
    _write_cloud_density_slice(
        path,
        valid_time="2026-01-01T00:00:00",
        level=300,
        lat=lat,
        lon=lon,
        values=values,
    )

    out_lat, out_lon, out_values = volume_routes._read_cloud_density_grid(
        path, lat_bounds=(2.8, 1.2), lon_bounds=(12.8, 11.2)
    )
    assert np.array_equal(out_lat, np.array([1.0, 2.0, 3.0]))
    assert np.array_equal(out_lon, np.array([11.0, 12.0, 13.0]))
    assert np.array_equal(out_values, values[1:4, 1:4])


def test_read_cloud_density_grid_raises_when_missing_cloud_density_var(
    tmp_path: Path,
) -> None:
    path = tmp_path / "grid-missing-var.nc"
    ds = xr.Dataset(
        {"temperature": (("lat", "lon"), np.zeros((2, 2), dtype=np.float32))},
        coords={"lat": [0.0, 1.0], "lon": [0.0, 1.0]},
    )
    ds.to_netcdf(path, engine="h5netcdf")

    with pytest.raises(HTTPException) as excinfo:
        volume_routes._read_cloud_density_grid(path)
    assert excinfo.value.status_code == 500
    assert excinfo.value.detail == "Slice missing cloud_density"


def test_read_cloud_density_grid_raises_when_dims_not_lat_lon(tmp_path: Path) -> None:
    path = tmp_path / "grid-wrong-dims.nc"
    ds = xr.Dataset(
        {
            "cloud_density": (
                ("time", "lat", "lon"),
                np.zeros((2, 2, 2), dtype=np.float32),
            )
        },
        coords={
            "time": [np.datetime64("2026-01-01"), np.datetime64("2026-01-02")],
            "lat": [0.0, 1.0],
            "lon": [0.0, 1.0],
        },
    )
    ds.to_netcdf(path, engine="h5netcdf")

    with pytest.raises(HTTPException) as excinfo:
        volume_routes._read_cloud_density_grid(path)
    assert excinfo.value.status_code == 500
    assert excinfo.value.detail == "Slice must have lat/lon dimensions"


def test_read_cloud_density_grid_raises_when_non_monotonic_and_bounds_used(
    tmp_path: Path,
) -> None:
    path = tmp_path / "grid-non-monotonic-bounds.nc"
    lat = [0.0, 0.2, 0.1]
    lon = [0.0, 0.1, 0.2]
    values = np.ones((len(lat), len(lon)), dtype=np.float32)
    _write_cloud_density_slice(
        path,
        valid_time="2026-01-01T00:00:00",
        level=300,
        lat=lat,
        lon=lon,
        values=values,
    )

    with pytest.raises(HTTPException) as excinfo:
        volume_routes._read_cloud_density_grid(path, lat_bounds=(0.0, 1.0))
    assert excinfo.value.status_code == 500
    assert excinfo.value.detail == "Slice coordinates are not monotonic"


def test_read_cloud_density_grid_raises_when_non_monotonic_without_bounds(
    tmp_path: Path,
) -> None:
    path = tmp_path / "grid-non-monotonic.nc"
    lat = [0.0, 0.2, 0.1]
    lon = [0.0, 0.1, 0.2]
    values = np.ones((len(lat), len(lon)), dtype=np.float32)
    _write_cloud_density_slice(
        path,
        valid_time="2026-01-01T00:00:00",
        level=300,
        lat=lat,
        lon=lon,
        values=values,
    )

    with pytest.raises(HTTPException) as excinfo:
        volume_routes._read_cloud_density_grid(path)
    assert excinfo.value.status_code == 500
    assert excinfo.value.detail == "Slice coordinates are not monotonic"


def test_read_cloud_density_grid_raises_when_data_shape_is_invalid(
    tmp_path: Path,
) -> None:
    path = tmp_path / "grid-invalid-shape.nc"
    ds = xr.Dataset(
        {"cloud_density": (("lon", "lat"), np.zeros((2, 3), dtype=np.float32))},
        coords={"lat": [0.0, 1.0, 2.0], "lon": [10.0, 11.0]},
    )
    ds.to_netcdf(path, engine="h5netcdf")

    with pytest.raises(HTTPException) as excinfo:
        volume_routes._read_cloud_density_grid(path)
    assert excinfo.value.status_code == 500
    assert excinfo.value.detail == "Slice has invalid data shape"


def test_read_cloud_density_grid_returns_empty_lat_selection_for_empty_coord(
    tmp_path: Path,
) -> None:
    path = tmp_path / "grid-empty-lat.nc"
    ds = xr.Dataset(
        {"cloud_density": (("lat", "lon"), np.empty((0, 2), dtype=np.float32))},
        coords={"lat": np.array([], dtype=np.float64), "lon": [0.0, 1.0]},
    )
    ds.to_netcdf(path, engine="h5netcdf")

    out_lat, out_lon, out_values = volume_routes._read_cloud_density_grid(
        path, lat_bounds=(0.0, 1.0)
    )
    assert out_lat.size == 0
    assert np.array_equal(out_lon, np.array([0.0, 1.0]))
    assert out_values.shape == (0, 2)


def test_read_cloud_density_grid_returns_empty_lon_selection_for_empty_coord(
    tmp_path: Path,
) -> None:
    path = tmp_path / "grid-empty-lon.nc"
    ds = xr.Dataset(
        {"cloud_density": (("lat", "lon"), np.empty((2, 0), dtype=np.float32))},
        coords={"lat": [0.0, 1.0], "lon": np.array([], dtype=np.float64)},
    )
    ds.to_netcdf(path, engine="h5netcdf")

    out_lat, out_lon, out_values = volume_routes._read_cloud_density_grid(
        path, lon_bounds=(0.0, 1.0)
    )
    assert np.array_equal(out_lat, np.array([0.0, 1.0]))
    assert out_lon.size == 0
    assert out_values.shape == (2, 0)


@pytest.mark.parametrize(
    ("bbox", "message"),
    [
        ("", "bbox must not be empty"),
        ("0,0,foo,1,0,1", "bbox values must be valid numbers"),
        ("0,0,1,1,0,inf", "bbox values must be finite numbers"),
        ("0,1,1,0,0,1", "bbox north must be > south"),
    ],
)
def test_parse_bbox_rejects_edge_cases(bbox: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        volume_routes._parse_bbox(bbox)


@pytest.mark.parametrize(
    ("levels", "message"),
    [
        ("", "levels must not be empty"),
        (" , , ", "levels must not be empty"),
        ("300,inf", "levels must be finite numbers"),
    ],
)
def test_parse_levels_rejects_edge_cases(levels: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        volume_routes._parse_levels(levels)


def test_parse_levels_preserves_non_integer_values() -> None:
    assert volume_routes._parse_levels("500.5") == ("500.5",)


def test_parse_valid_time_rejects_empty_and_defaults_to_utc() -> None:
    with pytest.raises(ValueError, match="valid_time must not be empty"):
        volume_routes._parse_valid_time("")

    parsed = volume_routes._parse_valid_time("2026-01-01T00:00:00")
    assert parsed == datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_time_key_helpers_accept_naive_datetime() -> None:
    naive = datetime(2026, 1, 1, 0, 0, 0)
    assert volume_routes._time_key(naive) == "20260101T000000Z"
    assert volume_routes._iso_z(naive) == "2026-01-01T00:00:00Z"


def test_parse_time_key_returns_none_for_invalid_value() -> None:
    assert volume_routes._parse_time_key("not-a-time-key") is None


def test_misc_helpers_cover_branch_cases() -> None:
    assert volume_routes._normalize_lon(10.0, np.array([])) == 10.0
    assert volume_routes._normalize_lon(370.0, np.array([0.0, 180.0, 270.0])) == 10.0
    assert volume_routes._monotonic_1d(np.zeros((2, 2))) is False
    assert volume_routes._bounding_slice(np.array([]), 0.0, 1.0) == slice(0, 0)


def test_interp_1d_handles_empty_and_single_point() -> None:
    with pytest.raises(ValueError, match="source coordinate is empty"):
        volume_routes._interp_1d(np.array([]), np.array([]), np.array([0.0]))

    out = volume_routes._interp_1d(
        np.array([0.0]),
        np.array([5.0], dtype=np.float32),
        np.array([0.0, 1.0], dtype=np.float64),
    )
    assert np.array_equal(out, np.array([5.0, 5.0], dtype=np.float32))


def test_interp2d_validates_inputs() -> None:
    with pytest.raises(ValueError, match="lat/lon must be 1D coordinates"):
        volume_routes._interp2d(
            lat=np.zeros((2, 2)),
            lon=np.array([0.0, 1.0]),
            values=np.zeros((2, 2), dtype=np.float32),
            target_lat=np.array([0.0]),
            target_lon=np.array([0.0]),
        )

    with pytest.raises(ValueError, match="values must have shape"):
        volume_routes._interp2d(
            lat=np.array([0.0, 1.0]),
            lon=np.array([0.0, 1.0]),
            values=np.zeros((3, 3), dtype=np.float32),
            target_lat=np.array([0.0]),
            target_lon=np.array([0.0]),
        )


def test_volume_returns_400_for_non_numeric_res(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path)
    response = client.get(
        "/api/v1/volume",
        params={
            "bbox": "0,0,0.1,0.1,0,1",
            "levels": "300",
            "res": "not-a-number",
        },
    )
    assert response.status_code == 400
