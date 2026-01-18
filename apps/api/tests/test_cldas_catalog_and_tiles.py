from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import xarray as xr
from fastapi.testclient import TestClient

from redis_fakes import FakeRedis


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
        "pipeline": {"workers": 2, "batch_size": 100, "data_source": "local"},
        "web": {"api_base_url": "http://localhost:8000"},
        "database": {"host": "localhost", "port": 5432, "name": "digital_earth"},
        "redis": {"host": "localhost", "port": 6379},
        "storage": {"tiles_bucket": "tiles", "raw_bucket": "raw"},
    }


def _base_config_remote() -> dict:
    config = _base_config()
    config["pipeline"]["data_source"] = "remote"
    return config


def _write_local_data_config(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "root_dir: Data",
                "sources:",
                "  cldas: CLDAS",
                "  ecmwf: EC-forecast/EC预报",
                "  town_forecast: 城镇预报导出",
                "index_cache_ttl_seconds: 0",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_tiling_config(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "tiling:",
                "  crs: EPSG:4326",
                "  global:",
                "    min_zoom: 0",
                "    max_zoom: 6",
                "  event:",
                "    min_zoom: 8",
                "    max_zoom: 10",
                "  tile_size: 256",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _make_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    config: dict | None = None,
) -> TestClient:
    monkeypatch.chdir(tmp_path)

    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", config or _base_config())
    _write_local_data_config(config_dir / "local-data.yaml")
    _write_tiling_config(config_dir / "tiling.yaml")

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    from config import get_settings
    from digital_earth_config.local_data import get_local_data_paths
    from local_data_service import get_data_source
    import main as main_module

    get_settings.cache_clear()
    get_data_source.cache_clear()
    get_local_data_paths.cache_clear()

    redis = FakeRedis(use_real_time=False)
    monkeypatch.setattr(main_module, "create_redis_client", lambda _url: redis)
    return TestClient(main_module.create_app())


def _write_cldas_file(tmp_path: Path, *, ts: str = "2025010100") -> Path:
    cldas_dir = tmp_path / "Data" / "CLDAS" / "TMP" / ts[0:4] / ts[4:6] / ts[6:8]
    cldas_dir.mkdir(parents=True, exist_ok=True)
    path = cldas_dir / f"CHINA_WEST_0P05_HOR-TMP-{ts}.nc"

    ds = xr.Dataset(
        data_vars={
            "SWDN": (("LAT", "LON"), np.arange(6, dtype=np.float32).reshape(2, 3)),
        },
        coords={
            "LAT": ("LAT", np.array([10.0, 10.5], dtype=np.float64)),
            "LON": ("LON", np.array([70.0, 70.5, 71.0], dtype=np.float64)),
        },
    )
    ds.to_netcdf(path, engine="h5netcdf")
    return path


def _write_invalid_cldas_file(tmp_path: Path, *, ts: str = "2025010100") -> Path:
    path = _write_cldas_file(tmp_path, ts=ts)
    path.write_bytes(b"not a netcdf")
    return path


def _write_multi_var_cldas_file(tmp_path: Path, *, ts: str = "2025010100") -> Path:
    cldas_dir = tmp_path / "Data" / "CLDAS" / "TMP" / ts[0:4] / ts[4:6] / ts[6:8]
    cldas_dir.mkdir(parents=True, exist_ok=True)
    path = cldas_dir / f"CHINA_WEST_0P05_HOR-TMP-{ts}.nc"

    ds = xr.Dataset(
        data_vars={
            "SWDN": (("LAT", "LON"), np.zeros((2, 3), dtype=np.float32)),
            "PRCP": (("LAT", "LON"), np.ones((2, 3), dtype=np.float32)),
        },
        coords={
            "LAT": ("LAT", np.array([10.0, 10.5], dtype=np.float64)),
            "LON": ("LON", np.array([70.0, 70.5, 71.0], dtype=np.float64)),
        },
    )
    ds.to_netcdf(path, engine="h5netcdf")
    return path


def test_catalog_cldas_times_returns_time_keys_and_etag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_cldas_file(tmp_path, ts="2025010100")

    client = _make_client(monkeypatch, tmp_path)

    response = client.get("/api/v1/catalog/cldas/times")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60"
    payload = response.json()
    assert payload["times"] == ["20250101T000000Z"]

    etag = response.headers["etag"]
    cached = client.get("/api/v1/catalog/cldas/times", headers={"If-None-Match": etag})
    assert cached.status_code == 304
    assert cached.headers["etag"] == etag
    assert cached.text == ""


def test_catalog_cldas_times_supports_var_filter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_cldas_file(tmp_path, ts="2025010100")

    client = _make_client(monkeypatch, tmp_path)

    ok = client.get("/api/v1/catalog/cldas/times", params={"var": "TMP"})
    assert ok.status_code == 200
    assert ok.json()["times"] == ["20250101T000000Z"]

    missing = client.get("/api/v1/catalog/cldas/times", params={"var": "RAIN"})
    assert missing.status_code == 200
    assert missing.json()["times"] == []


def test_tiles_cldas_returns_png_and_etag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_cldas_file(tmp_path, ts="2025010100")

    client = _make_client(monkeypatch, tmp_path)

    url = "/api/v1/tiles/cldas/20250101T000000Z/TMP/0/0/0.png"
    response = client.get(url, headers={"X-Trace-Id": "trace-tiles-1"})
    assert response.status_code == 200
    assert response.headers["x-trace-id"] == "trace-tiles-1"
    assert response.headers["cache-control"] == "public, max-age=60"
    assert response.headers["content-type"].startswith("image/png")
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")

    etag = response.headers["etag"]
    cached = client.get(
        url, headers={"If-None-Match": etag, "X-Trace-Id": "trace-tiles-2"}
    )
    assert cached.status_code == 304
    assert cached.headers["etag"] == etag
    assert cached.headers["x-trace-id"] == "trace-tiles-2"


def test_tiles_cldas_missing_time_returns_json_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_cldas_file(tmp_path, ts="2025010100")

    client = _make_client(monkeypatch, tmp_path)

    response = client.get(
        "/api/v1/tiles/cldas/20250101T010000Z/TMP/0/0/0.png",
        headers={"X-Trace-Id": "trace-miss-1"},
    )
    assert response.status_code == 404
    assert response.headers["x-trace-id"] == "trace-miss-1"
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert payload["error_code"] == 40400
    assert payload["trace_id"] == "trace-miss-1"


def test_catalog_time_key_fallback_parses_iso_when_meta_missing() -> None:
    from routers.catalog import _time_key_from_index_item

    item_z = SimpleNamespace(meta={}, time="2025-01-01T00:00:00Z")
    assert _time_key_from_index_item(item_z) == "20250101T000000Z"

    item_naive = SimpleNamespace(meta=None, time="2025-01-01T00:00:00")
    assert _time_key_from_index_item(item_naive) == "20250101T000000Z"

    item_bad = SimpleNamespace(meta=None, time="not-a-time")
    assert _time_key_from_index_item(item_bad) is None


def test_tiles_time_parsing_supports_timestamp_time_key_and_iso() -> None:
    from routers.tiles import _timestamp_from_time_key

    assert _timestamp_from_time_key("2025010100") == "2025010100"
    assert _timestamp_from_time_key("20250101T000000Z") == "2025010100"
    assert _timestamp_from_time_key("2025-01-01T00:00:00Z") == "2025010100"
    assert _timestamp_from_time_key("invalid") is None


def test_tiles_cldas_invalid_time_and_var_return_json_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_cldas_file(tmp_path, ts="2025010100")
    client = _make_client(monkeypatch, tmp_path)

    bad_time = client.get("/api/v1/tiles/cldas/not-a-time/TMP/0/0/0.png")
    assert bad_time.status_code == 400
    assert bad_time.headers["content-type"].startswith("application/json")
    assert bad_time.json()["error_code"] == 40000

    bad_var = client.get("/api/v1/tiles/cldas/20250101T000000Z/TMP!/0/0/0.png")
    assert bad_var.status_code == 400
    assert bad_var.headers["content-type"].startswith("application/json")
    assert bad_var.json()["error_code"] == 40000


def test_catalog_and_tiles_return_400_in_remote_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path, config=_base_config_remote())

    times = client.get("/api/v1/catalog/cldas/times")
    assert times.status_code == 400
    assert times.json()["error_code"] == 40000

    tile = client.get("/api/v1/tiles/cldas/20250101T000000Z/TMP/0/0/0.png")
    assert tile.status_code == 400
    assert tile.json()["error_code"] == 40000


def test_tiles_cldas_invalid_netcdf_returns_400(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_invalid_cldas_file(tmp_path, ts="2025010100")
    client = _make_client(monkeypatch, tmp_path)

    response = client.get("/api/v1/tiles/cldas/20250101T000000Z/TMP/0/0/0.png")
    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == 40000


def test_tiles_cldas_missing_variable_in_dataset_returns_400(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_multi_var_cldas_file(tmp_path, ts="2025010100")
    client = _make_client(monkeypatch, tmp_path)

    response = client.get("/api/v1/tiles/cldas/20250101T000000Z/TMP/0/0/0.png")
    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == 40000
