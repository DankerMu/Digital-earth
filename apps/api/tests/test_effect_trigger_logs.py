from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from redis_fakes import FakeRedis


def _write_config(dir_path: Path, env: str, data: dict[str, Any]) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{env}.json").write_text(json.dumps(data), encoding="utf-8")


def _base_config(
    *,
    effect_logging: dict[str, Any] | None = None,
) -> dict[str, Any]:
    api_section: dict[str, Any] = {
        "host": "0.0.0.0",
        "port": 8000,
        "debug": True,
        "cors_origins": [],
        "rate_limit": {"enabled": False},
    }
    if effect_logging is not None:
        api_section["effect_trigger_logging"] = effect_logging

    return {
        "api": api_section,
        "pipeline": {"workers": 2, "batch_size": 100},
        "web": {"api_base_url": "http://localhost:8000"},
        "database": {"host": "localhost", "port": 5432, "name": "digital_earth"},
        "redis": {"host": "localhost", "port": 6379},
        "storage": {"tiles_bucket": "tiles", "raw_bucket": "raw"},
    }


def _seed_schema(db_url: str) -> None:
    from models import Base

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)


def _make_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    db_url: str,
    config: dict[str, Any],
) -> TestClient:
    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", config)

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
    return TestClient(main_module.create_app())


def _count_rows(db_url: str) -> int:
    from models import EffectTriggerLog

    engine = create_engine(db_url)
    with Session(engine) as session:
        return int(
            session.execute(
                select(func.count()).select_from(EffectTriggerLog)
            ).scalar_one()
        )


def test_ingest_effect_trigger_logs_sample_rate_zero_stores_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'effects.db'}"
    _seed_schema(db_url)

    client = _make_client(
        monkeypatch,
        tmp_path,
        db_url=db_url,
        config=_base_config(effect_logging={"enabled": True, "sample_rate": 0.0}),
    )

    response = client.post(
        "/api/v1/effects/trigger-logs",
        json={
            "events": [
                {
                    "effect_type": "rain",
                    "timestamp": "2026-01-20T00:00:00Z",
                    "client_id": "client-a",
                    "client": "web",
                    "fps": 60,
                }
            ]
        },
    )
    assert response.status_code == 204
    assert _count_rows(db_url) == 0


def test_ingest_effect_trigger_logs_sample_rate_one_stores_all_events(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'effects.db'}"
    _seed_schema(db_url)

    client = _make_client(
        monkeypatch,
        tmp_path,
        db_url=db_url,
        config=_base_config(effect_logging={"enabled": True, "sample_rate": 1.0}),
    )

    response = client.post(
        "/api/v1/effects/trigger-logs",
        json={
            "events": [
                {
                    "effect_type": "rain",
                    "timestamp": "2026-01-20T00:00:00Z",
                    "client_id": "client-a",
                    "client": "web",
                    "fps": 60,
                },
                {
                    "effect_type": "snow",
                    "timestamp": "2026-01-20T00:00:01Z",
                    "client_id": "client-b",
                    "client": "ios",
                    "fps": 30,
                },
            ]
        },
    )
    assert response.status_code == 204
    assert _count_rows(db_url) == 2


def test_ingest_effect_trigger_logs_enforces_max_events_per_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'effects.db'}"
    _seed_schema(db_url)

    client = _make_client(
        monkeypatch,
        tmp_path,
        db_url=db_url,
        config=_base_config(
            effect_logging={
                "enabled": True,
                "sample_rate": 1.0,
                "max_events_per_request": 1,
            }
        ),
    )

    response = client.post(
        "/api/v1/effects/trigger-logs",
        json={
            "events": [
                {"effect_type": "rain", "timestamp": "2026-01-20T00:00:00Z"},
                {"effect_type": "snow", "timestamp": "2026-01-20T00:00:01Z"},
            ]
        },
    )
    assert response.status_code == 413
    assert _count_rows(db_url) == 0


def test_list_effect_trigger_logs_returns_paginated_recent_items(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'effects.db'}"
    _seed_schema(db_url)

    client = _make_client(
        monkeypatch,
        tmp_path,
        db_url=db_url,
        config=_base_config(effect_logging={"enabled": True, "sample_rate": 1.0}),
    )

    response = client.post(
        "/api/v1/effects/trigger-logs",
        json={
            "events": [
                {"effect_type": "rain", "timestamp": "2026-01-20T00:00:00Z"},
                {"effect_type": "snow", "timestamp": "2026-01-20T00:00:01Z"},
                {"effect_type": "fog", "timestamp": "2026-01-20T00:00:02Z"},
            ]
        },
    )
    assert response.status_code == 204

    response = client.get(
        "/api/v1/effects/trigger-logs",
        params={"page": 1, "page_size": 2},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 1
    assert payload["page_size"] == 2
    assert payload["total"] == 3
    assert len(payload["items"]) == 2
    assert payload["items"][0]["effect_type"] == "fog"

    response = client.get(
        "/api/v1/effects/trigger-logs",
        params={"effect_type": "snow"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["effect_type"] == "snow"


def test_should_sample_is_deterministic_for_same_input() -> None:
    from routers.effects import _should_sample

    triggered_at = datetime(2026, 1, 20, tzinfo=timezone.utc)
    sample_rate = 0.42
    client_id = "client-a"
    effect_type = "rain"

    sample_key = f"{client_id}:{effect_type}:{triggered_at.isoformat()}"
    digest = hashlib.sha256(sample_key.encode("utf-8")).digest()
    sample_value = int.from_bytes(digest[:8], "big") / 2**64

    assert _should_sample(
        sample_rate=sample_rate,
        client_id=client_id,
        effect_type=effect_type,
        triggered_at=triggered_at,
    ) == (sample_value < sample_rate)


def test_list_effect_trigger_logs_rejects_blank_client_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'effects.db'}"
    _seed_schema(db_url)

    client = _make_client(
        monkeypatch,
        tmp_path,
        db_url=db_url,
        config=_base_config(effect_logging={"enabled": True, "sample_rate": 1.0}),
    )

    response = client.get("/api/v1/effects/trigger-logs", params={"client_id": " "})
    assert response.status_code == 400
