from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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


def _seed_run_times(
    db_url: str,
    *,
    run_time: datetime,
    valid_times: list[datetime],
) -> None:
    from models import Base, EcmwfRun, EcmwfTime

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        run = EcmwfRun(run_time=run_time, status="complete")
        session.add(run)
        for valid_time in valid_times:
            session.add(EcmwfTime(run=run, valid_time=valid_time))
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


def test_catalog_ecmwf_run_times_applies_std_policy_and_marks_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from routers import catalog as catalog_router

    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_times = [
        run_time + timedelta(hours=-3),
        run_time,
        run_time + timedelta(hours=1),
        run_time + timedelta(hours=6),
        run_time + timedelta(hours=72),
        run_time + timedelta(hours=75),
        run_time + timedelta(hours=78),
        run_time + timedelta(hours=240),
        run_time + timedelta(hours=246),
    ]
    _seed_run_times(db_url, run_time=run_time, valid_times=valid_times)

    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)
    run_key = catalog_router._time_key_from_datetime(run_time)

    response = client.get(f"/api/v1/catalog/ecmwf/runs/{run_key}/times")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60"
    assert response.headers["etag"].startswith('"sha256-')

    payload = response.json()
    assert payload["times"] == [
        catalog_router._time_key_from_datetime(run_time),
        catalog_router._time_key_from_datetime(run_time + timedelta(hours=6)),
        catalog_router._time_key_from_datetime(run_time + timedelta(hours=72)),
        catalog_router._time_key_from_datetime(run_time + timedelta(hours=78)),
        catalog_router._time_key_from_datetime(run_time + timedelta(hours=240)),
    ]

    expected_keys = catalog_router._expected_time_keys_for_run(
        run_time=run_time, policy="std"
    )
    assert set(payload["times"]).issubset(set(expected_keys))
    assert set(payload["missing"]).issubset(set(expected_keys))
    assert set(payload["times"]).isdisjoint(set(payload["missing"]))
    assert set(payload["times"]) | set(payload["missing"]) == set(expected_keys)

    assert catalog_router._time_key_from_datetime(run_time + timedelta(hours=3)) in set(
        payload["missing"]
    )
    assert catalog_router._time_key_from_datetime(
        run_time + timedelta(hours=1)
    ) not in set(payload["times"])
    assert catalog_router._time_key_from_datetime(
        run_time + timedelta(hours=1)
    ) not in set(payload["missing"])
    assert catalog_router._time_key_from_datetime(
        run_time + timedelta(hours=75)
    ) not in set(payload["missing"])


def test_catalog_ecmwf_run_times_policy_validation_and_etag_304(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from routers import catalog as catalog_router

    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _seed_run_times(db_url, run_time=run_time, valid_times=[run_time])

    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)
    run_key = catalog_router._time_key_from_datetime(run_time)

    ok = client.get(
        f"/api/v1/catalog/ecmwf/runs/{run_key}/times", params={"policy": "STD"}
    )
    assert ok.status_code == 200

    bad = client.get(
        f"/api/v1/catalog/ecmwf/runs/{run_key}/times", params={"policy": "raw"}
    )
    assert bad.status_code == 400

    etag = ok.headers["etag"]
    cached = client.get(
        f"/api/v1/catalog/ecmwf/runs/{run_key}/times",
        params={"policy": "std"},
        headers={"If-None-Match": etag},
    )
    assert cached.status_code == 304
    assert cached.headers["etag"] == etag
    assert cached.text == ""


def test_catalog_ecmwf_run_times_cache_hit_skips_db_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from routers import catalog as catalog_router

    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _seed_run_times(db_url, run_time=run_time, valid_times=[run_time])

    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)
    run_key = catalog_router._time_key_from_datetime(run_time)

    first = client.get(f"/api/v1/catalog/ecmwf/runs/{run_key}/times")
    assert first.status_code == 200

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("expected cached response (no DB query)")

    monkeypatch.setattr(catalog_router, "_query_ecmwf_run_times", _boom)

    second = client.get(f"/api/v1/catalog/ecmwf/runs/{run_key}/times")
    assert second.status_code == 200
    assert second.json() == first.json()


def test_catalog_ecmwf_run_times_rejects_bad_run_param(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    bad = client.get("/api/v1/catalog/ecmwf/runs/not-a-time/times")
    assert bad.status_code == 400


def test_catalog_ecmwf_run_times_404_when_run_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from routers import catalog as catalog_router

    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _seed_run_times(db_url, run_time=run_time, valid_times=[run_time])

    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    missing_run = datetime(2026, 1, 2, tzinfo=timezone.utc)
    missing_key = catalog_router._time_key_from_datetime(missing_run)
    response = client.get(f"/api/v1/catalog/ecmwf/runs/{missing_key}/times")
    assert response.status_code == 404
