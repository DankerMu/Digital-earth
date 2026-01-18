from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

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
        "pipeline": {"workers": 2, "batch_size": 100},
        "web": {"api_base_url": "http://localhost:8000"},
        "database": {"host": "localhost", "port": 5432, "name": "digital_earth"},
        "redis": {"host": "localhost", "port": 6379},
        "storage": {"tiles_bucket": "tiles", "raw_bucket": "raw"},
    }


def _seed_run(db_url: str, *, run_time: datetime) -> None:
    from models import Base, EcmwfRun

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(EcmwfRun(run_time=run_time, status="complete"))
        session.commit()


def _make_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, db_url: str
) -> tuple[TestClient, FakeRedis]:
    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")
    monkeypatch.setenv("DATABASE_URL", db_url)

    from config import get_settings
    from db import get_engine
    import main as main_module

    get_settings.cache_clear()
    get_engine.cache_clear()

    redis = FakeRedis(use_real_time=False)
    monkeypatch.setattr(main_module, "create_redis_client", lambda _url: redis)
    return TestClient(main_module.create_app()), redis


def test_catalog_ecmwf_run_vars_returns_vars_levels_units_legend_and_etag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from routers import catalog as catalog_router

    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _seed_run(db_url, run_time=run_time)

    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)
    run_key = catalog_router._time_key_from_datetime(run_time)

    response = client.get(f"/api/v1/catalog/ecmwf/runs/{run_key}/vars")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60"
    etag = response.headers["etag"]
    assert etag.startswith('"sha256-')

    payload = response.json()
    assert payload["vars"] == ["cloud", "precip", "wind", "temp"]
    assert payload["levels"] == ["sfc", "850", "700", "500", "300"]
    assert payload["units"] == {
        "cloud": "%",
        "precip": "mm",
        "wind": "m/s",
        "temp": "°C",
    }
    assert payload["legend_version"] == 2

    cached = client.get(
        f"/api/v1/catalog/ecmwf/runs/{run_key}/vars",
        headers={"If-None-Match": etag},
    )
    assert cached.status_code == 304
    assert cached.headers["etag"] == etag
    assert cached.text == ""


def test_catalog_ecmwf_run_vars_cache_hit_skips_db_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from routers import catalog as catalog_router

    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _seed_run(db_url, run_time=run_time)

    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)
    run_key = catalog_router._time_key_from_datetime(run_time)

    first = client.get(f"/api/v1/catalog/ecmwf/runs/{run_key}/vars")
    assert first.status_code == 200

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("expected cached response (no DB query)")

    monkeypatch.setattr(catalog_router, "_assert_ecmwf_run_exists", _boom)

    second = client.get(f"/api/v1/catalog/ecmwf/runs/{run_key}/vars")
    assert second.status_code == 200
    assert second.json() == first.json()


def test_catalog_ecmwf_run_vars_rejects_bad_run_param(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    bad = client.get("/api/v1/catalog/ecmwf/runs/not-a-time/vars")
    assert bad.status_code == 400


def test_catalog_ecmwf_run_vars_404_when_run_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from routers import catalog as catalog_router

    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _seed_run(db_url, run_time=run_time)

    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    missing_run = datetime(2026, 1, 2, tzinfo=timezone.utc)
    missing_key = catalog_router._time_key_from_datetime(missing_run)
    response = client.get(f"/api/v1/catalog/ecmwf/runs/{missing_key}/vars")
    assert response.status_code == 404
