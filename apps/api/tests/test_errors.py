from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from observability import TraceIdMiddleware, register_exception_handlers
from routers.errors import ErrorReport, router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(TraceIdMiddleware)
    register_exception_handlers(app)

    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(router)
    app.include_router(api_v1)
    return app


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


def _make_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    from config import get_settings
    from main import create_app

    get_settings.cache_clear()
    return TestClient(create_app())


def test_error_report_model_normalizes_timestamp_to_utc() -> None:
    naive = datetime(2024, 1, 1, 12, 0, 0)
    report = ErrorReport(
        trace_id="abc",
        error_code="E123",
        message="boom",
        version="1.0",
        timestamp=naive,
    )
    assert report.timestamp.tzinfo == timezone.utc

    tz_east_8 = timezone(timedelta(hours=8))
    aware = datetime(2024, 1, 1, 12, 0, 0, tzinfo=tz_east_8)
    report2 = ErrorReport(
        trace_id="abc",
        error_code="E123",
        message="boom",
        version="1.0",
        timestamp=aware,
    )
    assert report2.timestamp.tzinfo == timezone.utc
    assert report2.timestamp.hour == 4


def test_post_errors_logs_structured_payload(caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(_make_app())
    payload = {
        "trace_id": "frontend-123",
        "error_code": "E123",
        "message": "Something went wrong",
        "stack": "Error: boom\\n  at line 1",
        "browser_info": {"ua": "pytest"},
        "app_state": {"route": "/"},
        "version": "web@1.2.3",
        "timestamp": "2024-01-01T00:00:00",
    }

    with caplog.at_level(logging.ERROR, logger="api.error"):
        response = client.post("/api/v1/errors", json=payload)

    assert response.status_code == 204

    record = next(
        item
        for item in caplog.records
        if item.name == "api.error" and item.getMessage() == "frontend.error_reported"
    )
    assert record.error_code == payload["error_code"]
    assert record.sanitized_message == payload["message"]
    assert record.reported_at == "2024-01-01T00:00:00Z"
    assert "frontend_trace_id" not in record.__dict__
    assert "frontend_version" not in record.__dict__
    assert "error_message" not in record.__dict__
    assert "error_stack" not in record.__dict__
    assert "browser_info" not in record.__dict__
    assert "app_state" not in record.__dict__


def test_errors_endpoint_registered_in_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path)
    response = client.post(
        "/api/v1/errors",
        json={
            "trace_id": "frontend-123",
            "error_code": "E123",
            "message": "boom",
            "version": "web@1.0.0",
        },
    )
    assert response.status_code == 204
    assert "x-trace-id" in response.headers


def test_errors_endpoint_validation_error_returns_400(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path)
    response = client.post("/api/v1/errors", json={"trace_id": "t", "message": "m"})
    assert response.status_code == 400

    trace_id = response.headers["X-Trace-Id"]
    payload = response.json()
    assert payload["error_code"] == 40000
    assert payload["message"] == "Bad Request"
    assert payload["trace_id"] == trace_id


def test_errors_endpoint_rejects_non_alphanumeric_error_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(_make_app())
    with caplog.at_level(logging.ERROR, logger="api.error"):
        response = client.post(
            "/api/v1/errors",
            json={
                "trace_id": "frontend-123",
                "error_code": "ERR-1",
                "message": "boom",
                "version": "web@1.0.0",
            },
        )
    assert response.status_code == 400
    assert response.json()["message"] == "Bad Request"
    assert not any(
        item.name == "api.error" and item.getMessage() == "frontend.error_reported"
        for item in caplog.records
    )


def test_errors_endpoint_rejects_too_long_message() -> None:
    client = TestClient(_make_app())
    response = client.post(
        "/api/v1/errors",
        json={
            "trace_id": "frontend-123",
            "error_code": "E123",
            "message": "x" * 1001,
            "version": "web@1.0.0",
        },
    )
    assert response.status_code == 400
    assert response.json()["message"] == "Bad Request"


def test_errors_endpoint_rejects_too_long_stack() -> None:
    client = TestClient(_make_app())
    response = client.post(
        "/api/v1/errors",
        json={
            "trace_id": "frontend-123",
            "error_code": "E123",
            "message": "boom",
            "stack": "x" * 5001,
            "version": "web@1.0.0",
        },
    )
    assert response.status_code == 400
    assert response.json()["message"] == "Bad Request"
