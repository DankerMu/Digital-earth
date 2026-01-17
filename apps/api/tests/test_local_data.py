from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from fastapi.testclient import TestClient


def _write_config(dir_path: Path, env: str, data: dict) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{env}.json").write_text(json.dumps(data), encoding="utf-8")


def _base_config() -> dict:
    return {
        "api": {"host": "0.0.0.0", "port": 8000, "debug": True, "cors_origins": []},
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
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_local_data_endpoints_read_local_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())
    _write_local_data_config(config_dir / "local-data.yaml")

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    # Create a tiny CLDAS NetCDF file that matches the filename convention.
    cldas_dir = tmp_path / "Data" / "CLDAS" / "TMP" / "2025" / "01" / "01"
    cldas_dir.mkdir(parents=True, exist_ok=True)
    cldas_path = cldas_dir / "CHINA_WEST_0P05_HOR-TMP-2025010100.nc"

    ds = xr.Dataset(
        data_vars={
            "SWDN": (("LAT", "LON"), np.arange(6, dtype=np.float32).reshape(2, 3)),
        },
        coords={
            "LAT": ("LAT", np.array([10.0, 10.5], dtype=np.float64)),
            "LON": ("LON", np.array([70.0, 70.5, 71.0], dtype=np.float64)),
        },
    )
    ds.to_netcdf(cldas_path, engine="h5netcdf")

    town_dir = tmp_path / "Data" / "城镇预报导出"
    town_dir.mkdir(parents=True, exist_ok=True)
    town_path = (
        town_dir / "Z_SEVP_C_BABJ_20250101000000_P_RFFC-SNWFD-202501010800-1212.TXT"
    )
    values = ["999.9"] * 18 + ["1.0", "2.0", "0.0"]
    town_path.write_text(
        "\n".join(
            [
                "ZCZC",
                "FSCI50 BABJ 010000",
                "2025010100时公共服务产品",
                "SNWFD 2025010100",
                "1",
                "58321 117.06 31.96 36.5 14 21",
                "12 " + " ".join(values),
                "",
            ]
        ),
        encoding="utf-8",
    )

    from config import get_settings
    from local_data_service import get_data_source
    from main import create_app

    get_settings.cache_clear()
    get_data_source.cache_clear()

    app = create_app()
    client = TestClient(app)

    # Index should include both files.
    resp = client.get("/api/v1/local-data/index")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["schema_version"] == 1
    assert any(item["kind"] == "cldas" for item in payload["items"])
    assert any(item["kind"] == "town_forecast" for item in payload["items"])

    cldas_rel = str(cldas_path.relative_to(tmp_path / "Data"))
    resp = client.get(
        "/api/v1/local-data/cldas/summary", params={"relative_path": cldas_rel}
    )
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["variable"] == "TMP"
    assert summary["dims"]["time"] == 1

    town_rel = str(town_path.relative_to(tmp_path / "Data"))
    resp = client.get(
        "/api/v1/local-data/town-forecast",
        params={"relative_path": town_rel, "max_stations": 1},
    )
    assert resp.status_code == 200
    parsed = resp.json()
    assert parsed["product"] == "SNWFD"
    assert parsed["stations"][0]["station_id"] == "58321"

    resp = client.get("/api/v1/local-data/file", params={"relative_path": town_rel})
    assert resp.status_code == 200
    assert b"SNWFD" in resp.content


def test_local_data_missing_file_is_404(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())
    _write_local_data_config(config_dir / "local-data.yaml")

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    from config import get_settings
    from local_data_service import get_data_source
    from main import create_app

    get_settings.cache_clear()
    get_data_source.cache_clear()

    app = create_app()
    client = TestClient(app)

    resp = client.get(
        "/api/v1/local-data/file",
        params={"relative_path": "does-not-exist.txt"},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["error_code"] == 40400
    assert "not found" in body["message"].lower()


def test_local_data_index_returns_400_in_remote_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config_remote())
    _write_local_data_config(config_dir / "local-data.yaml")

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    from config import get_settings
    from local_data_service import get_data_source
    from main import create_app

    get_settings.cache_clear()
    get_data_source.cache_clear()

    app = create_app()
    client = TestClient(app)

    resp = client.get("/api/v1/local-data/index")
    assert resp.status_code == 400
    body = resp.json()
    assert body["error_code"] == 40000
