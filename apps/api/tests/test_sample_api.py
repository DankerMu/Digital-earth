from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from fastapi.testclient import TestClient
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from redis_fakes import FakeRedis


def _write_config(dir_path: Path, env: str, data: dict) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{env}.json").write_text(json.dumps(data), encoding="utf-8")


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


def _base_config(*, data_source: str = "local") -> dict:
    return {
        "api": {
            "host": "0.0.0.0",
            "port": 8000,
            "debug": True,
            "cors_origins": [],
            "rate_limit": {"enabled": False},
        },
        "pipeline": {"workers": 2, "batch_size": 100, "data_source": data_source},
        "web": {"api_base_url": "http://localhost:8000"},
        "database": {"host": "localhost", "port": 5432, "name": "digital_earth"},
        "redis": {"host": "localhost", "port": 6379},
        "storage": {"tiles_bucket": "tiles", "raw_bucket": "raw"},
    }


def _seed_asset(
    db_url: str,
    *,
    run_time: datetime,
    valid_time: datetime,
    variable: str,
    level: str,
    path: str,
) -> None:
    from models import Base, EcmwfAsset, EcmwfRun, EcmwfTime

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        run = EcmwfRun(run_time=run_time, status="complete")
        time = EcmwfTime(valid_time=valid_time, run=run)
        asset = EcmwfAsset(
            variable=variable,
            level=level,
            status="complete",
            version=1,
            path=path,
            run=run,
            time=time,
        )
        session.add_all([run, time, asset])
        session.commit()


def _make_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, db_url: str
) -> tuple[TestClient, FakeRedis]:
    monkeypatch.chdir(tmp_path)

    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config(data_source="local"))
    _write_local_data_config(config_dir / "local-data.yaml")

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")
    monkeypatch.setenv("DATABASE_URL", db_url)

    from config import get_settings
    from db import get_engine
    from local_data_service import get_data_source
    import main as main_module

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_data_source.cache_clear()

    from models import Base

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    redis = FakeRedis(use_real_time=False)
    monkeypatch.setattr(main_module, "create_redis_client", lambda _url: redis)
    return TestClient(main_module.create_app()), redis


def _write_test_datacube(path: Path, *, var: str, values: np.ndarray) -> None:
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")
    level = xr.DataArray(
        [0.0], dims=["level"], attrs={"long_name": "surface", "units": "1"}
    )
    lat = np.array([0.0, 1.0], dtype=np.float32)
    lon = np.array([0.0, 1.0], dtype=np.float32)

    ds = xr.Dataset(
        {
            var: xr.DataArray(
                values, dims=["time", "level", "lat", "lon"], attrs={"units": "°C"}
            )
        },
        coords={"time": time, "level": level, "lat": lat, "lon": lon},
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(path, engine="h5netcdf")


def test_sample_helpers_cover_edge_cases() -> None:
    from routers import sample as sample_router

    parsed = sample_router._parse_time("2026-01-01T00:00:00", label="run")
    assert parsed.tzinfo == timezone.utc
    assert sample_router._time_key(datetime(2026, 1, 1)) == "20260101T000000Z"

    with pytest.raises(ValueError, match="must not be empty"):
        sample_router._parse_time("", label="run")

    with pytest.raises(ValueError, match="level must not be empty"):
        sample_router._normalize_level(" ")

    assert sample_router._normalize_level("850hPa") == ("850", 850.0)
    assert sample_router._normalize_level("0.5") == ("0p5", 0.5)

    with pytest.raises(ValueError, match="finite"):
        sample_router._normalize_level("nan")

    lon_q = sample_router._normalize_query_lon(-10.0, np.array([0.0, 359.0]))
    assert lon_q == 350.0

    idx = sample_router._resolve_surface_level_index(
        np.array([0.0, 850.0], dtype=np.float32),
        {"units": "hPa"},
    )
    assert idx == 0

    with pytest.raises(HTTPException) as exc:
        sample_router._resolve_surface_level_index(
            np.array([850.0], dtype=np.float32),
            {"units": "hPa"},
        )
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        sample_router._interp_1d(np.array([], dtype=np.float32), 0.0)
    assert exc.value.status_code == 500


def test_sample_rejects_whitespace_var_and_level(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    resp = client.get(
        "/api/v1/sample",
        params={
            "run": "20260101T000000Z",
            "valid_time": "20260101T000000Z",
            "level": "sfc",
            "var": " ",
            "lon": 0.0,
            "lat": 0.0,
        },
    )
    assert resp.status_code == 400

    resp = client.get(
        "/api/v1/sample",
        params={
            "run": "20260101T000000Z",
            "valid_time": "20260101T000000Z",
            "level": " ",
            "var": "temp",
            "lon": 0.0,
            "lat": 0.0,
        },
    )
    assert resp.status_code == 400


def test_sample_returns_value_unit_and_qc_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    cube_path = tmp_path / "Data" / "cubes" / "run-20260101T000000Z.nc"
    var = "temp"

    lat = np.array([0.0, 1.0], dtype=np.float64)
    lon = np.array([0.0, 1.0], dtype=np.float64)
    grid = (10.0 * lat[:, None] + 100.0 * lon[None, :]).astype(np.float32)
    values = grid[None, None, :, :]
    _write_test_datacube(cube_path, var=var, values=values)

    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rel_path = str(cube_path.relative_to(tmp_path / "Data"))
    _seed_asset(
        db_url,
        run_time=run_time,
        valid_time=valid_time,
        variable=var,
        level="sfc",
        path=rel_path,
    )

    resp = client.get(
        "/api/v1/sample",
        params={
            "run": "20260101T000000Z",
            "valid_time": "2026-01-01T00:00:00Z",
            "level": "sfc",
            "var": "TEMP",
            "lon": 0.75,
            "lat": 0.25,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["qc"] == "ok"
    assert payload["unit"] == "°C"
    assert payload["value"] == pytest.approx(77.5)


def test_sample_missing_returns_qc_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    cube_path = tmp_path / "Data" / "cubes" / "run-20260101T000000Z.nc"
    var = "temp"

    values = np.zeros((1, 1, 2, 2), dtype=np.float32)
    values[0, 0, 0, 1] = np.nan
    _write_test_datacube(cube_path, var=var, values=values)

    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rel_path = str(cube_path.relative_to(tmp_path / "Data"))
    _seed_asset(
        db_url,
        run_time=run_time,
        valid_time=valid_time,
        variable=var,
        level="sfc",
        path=rel_path,
    )

    nan_resp = client.get(
        "/api/v1/sample",
        params={
            "run": "20260101T000000Z",
            "valid_time": "20260101T000000Z",
            "level": "sfc",
            "var": "temp",
            "lon": 0.5,
            "lat": 0.5,
        },
    )
    assert nan_resp.status_code == 200
    payload = nan_resp.json()
    assert payload["qc"] == "missing"
    assert payload["value"] is None
    assert payload["unit"] == "°C"

    oob_resp = client.get(
        "/api/v1/sample",
        params={
            "run": "20260101T000000Z",
            "valid_time": "20260101T000000Z",
            "level": "sfc",
            "var": "temp",
            "lon": 0.5,
            "lat": 2.0,
        },
    )
    assert oob_resp.status_code == 200
    payload = oob_resp.json()
    assert payload["qc"] == "missing"
    assert payload["value"] is None


def test_sample_cache_hit_skips_db_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    cube_path = tmp_path / "Data" / "cubes" / "run-20260101T000000Z.nc"
    var = "temp"
    values = np.zeros((1, 1, 2, 2), dtype=np.float32)
    _write_test_datacube(cube_path, var=var, values=values)

    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rel_path = str(cube_path.relative_to(tmp_path / "Data"))
    _seed_asset(
        db_url,
        run_time=run_time,
        valid_time=valid_time,
        variable=var,
        level="sfc",
        path=rel_path,
    )

    params = {
        "run": "20260101T000000Z",
        "valid_time": "20260101T000000Z",
        "level": "sfc",
        "var": "temp",
        "lon": 0.25,
        "lat": 0.25,
    }
    first = client.get("/api/v1/sample", params=params)
    assert first.status_code == 200

    from routers import sample as sample_router

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("expected cached response (no DB query)")

    monkeypatch.setattr(sample_router, "_query_asset_path", _boom)

    second = client.get("/api/v1/sample", params=params)
    assert second.status_code == 200
    assert second.json() == first.json()


def test_sample_invalid_time_returns_400(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    resp = client.get(
        "/api/v1/sample",
        params={
            "run": "not-a-time",
            "valid_time": "20260101T000000Z",
            "level": "sfc",
            "var": "temp",
            "lon": 0.0,
            "lat": 0.0,
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error_code"] == 40000


def test_sample_missing_asset_returns_404(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    resp = client.get(
        "/api/v1/sample",
        params={
            "run": "20260101T000000Z",
            "valid_time": "20260101T000000Z",
            "level": "sfc",
            "var": "temp",
            "lon": 0.0,
            "lat": 0.0,
        },
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["error_code"] == 40400
