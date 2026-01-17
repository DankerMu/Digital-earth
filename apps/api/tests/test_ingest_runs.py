from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
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


def _write_scheduler_config(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "enabled: false",
                'cron: "0 * * * *"',
                "runs:",
                '  storage_path: ".cache/ingest-runs.json"',
                "  max_entries: 50",
                "alert:",
                "  consecutive_failures: 3",
                "  webhook_url:",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_ingest_runs_endpoint_returns_recent_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())
    _write_scheduler_config(config_dir / "scheduler.yaml")

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    from config import get_settings
    from main import create_app
    from scheduler.config import get_scheduler_config
    from scheduler.runs import get_ingest_run_store, reset_ingest_run_store_for_tests

    get_settings.cache_clear()
    get_scheduler_config.cache_clear()
    reset_ingest_run_store_for_tests()

    store = get_ingest_run_store()
    run1 = store.create_run()
    store.update_run(
        run1.run_id,
        status="success",
        end_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        attempts=1,
    )
    run2 = store.create_run()
    store.update_run(
        run2.run_id,
        status="failed",
        end_time=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
        error="boom",
        attempts=2,
    )

    client = TestClient(create_app())
    resp = client.get("/api/v1/ingest/runs", params={"limit": 10})
    assert resp.status_code == 200

    payload = resp.json()
    assert payload["schema_version"] == 1
    assert len(payload["items"]) == 2
    assert payload["items"][0]["run_id"] == run2.run_id
    assert payload["items"][0]["status"] == "failed"
    assert payload["items"][1]["run_id"] == run1.run_id
