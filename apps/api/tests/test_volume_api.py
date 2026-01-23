from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from fastapi.testclient import TestClient

from volume.cloud_density import DEFAULT_CLOUD_DENSITY_LAYER
from volume.pack import decode_volume_pack


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

