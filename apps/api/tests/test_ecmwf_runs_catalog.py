from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


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


def _seed_runs(db_url: str, runs: list[tuple[datetime, str]]) -> None:
    from models import Base, EcmwfRun

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        for run_time, status in runs:
            session.add(EcmwfRun(run_time=run_time, status=status))
        session.commit()


def _make_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, db_url: str
) -> TestClient:
    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")
    monkeypatch.setenv("DATABASE_URL", db_url)

    from config import get_settings
    from db import get_engine
    from main import create_app
    from routers.catalog import reset_ecmwf_runs_cache_for_tests

    get_settings.cache_clear()
    get_engine.cache_clear()
    reset_ecmwf_runs_cache_for_tests()

    return TestClient(create_app())


def test_catalog_ecmwf_runs_returns_runs_with_status_and_etag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    _seed_runs(
        db_url,
        runs=[
            (datetime(2026, 1, 1, 12, tzinfo=timezone.utc), "complete"),
            (datetime(2026, 1, 1, tzinfo=timezone.utc), "partial"),
            (datetime(2025, 12, 31, 12, tzinfo=timezone.utc), "unknown"),
        ],
    )

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    response = client.get("/api/v1/catalog/ecmwf/runs", params={"limit": 10})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60"
    etag = response.headers["etag"]
    assert etag.startswith('"sha256-')

    payload = response.json()
    assert [item["run_time"] for item in payload["runs"]] == [
        "20260101T120000Z",
        "20260101T000000Z",
        "20251231T120000Z",
    ]
    assert [item["status"] for item in payload["runs"]] == [
        "complete",
        "partial",
        "partial",
    ]

    cached = client.get(
        "/api/v1/catalog/ecmwf/runs",
        params={"limit": 10},
        headers={"If-None-Match": etag},
    )
    assert cached.status_code == 304
    assert cached.headers["etag"] == etag
    assert cached.text == ""


def test_catalog_ecmwf_runs_cache_hit_skips_db_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    _seed_runs(
        db_url,
        runs=[(datetime(2026, 1, 1, tzinfo=timezone.utc), "complete")],
    )

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    first = client.get("/api/v1/catalog/ecmwf/runs", params={"limit": 10})
    assert first.status_code == 200

    from routers import catalog as catalog_router

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("expected cached response (no DB query)")

    monkeypatch.setattr(catalog_router, "_query_ecmwf_runs", _boom)

    second = client.get("/api/v1/catalog/ecmwf/runs", params={"limit": 10})
    assert second.status_code == 200
    assert second.json() == first.json()


def test_catalog_ecmwf_runs_pagination_latest_and_cache_expiry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    _seed_runs(
        db_url,
        runs=[
            (datetime(2026, 1, 1, 12, tzinfo=timezone.utc), "complete"),
            (datetime(2026, 1, 1, 6, tzinfo=timezone.utc), "complete"),
            (datetime(2026, 1, 1, tzinfo=timezone.utc), "partial"),
        ],
    )

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)

    from routers import catalog as catalog_router

    clock = {"now": 0.0}
    monkeypatch.setattr(catalog_router.time, "monotonic", lambda: clock["now"])
    catalog_router.reset_ecmwf_runs_cache_for_tests()

    first_page = client.get(
        "/api/v1/catalog/ecmwf/runs", params={"limit": 2, "offset": 0}
    )
    assert first_page.status_code == 200
    assert [item["run_time"] for item in first_page.json()["runs"]] == [
        "20260101T120000Z",
        "20260101T060000Z",
    ]

    second_page = client.get(
        "/api/v1/catalog/ecmwf/runs", params={"limit": 2, "offset": 2}
    )
    assert second_page.status_code == 200
    assert [item["run_time"] for item in second_page.json()["runs"]] == [
        "20260101T000000Z"
    ]

    latest = client.get("/api/v1/catalog/ecmwf/runs", params={"latest": 1})
    assert latest.status_code == 200
    assert [item["run_time"] for item in latest.json()["runs"]] == ["20260101T120000Z"]

    bad = client.get("/api/v1/catalog/ecmwf/runs", params={"latest": 1, "offset": 1})
    assert bad.status_code == 400

    clock["now"] = 61.0
    _seed_runs(
        db_url,
        runs=[(datetime(2026, 1, 2, tzinfo=timezone.utc), "complete")],
    )

    expired = client.get("/api/v1/catalog/ecmwf/runs", params={"limit": 2})
    assert expired.status_code == 200
    assert [item["run_time"] for item in expired.json()["runs"]] == [
        "20260102T000000Z",
        "20260101T120000Z",
    ]
