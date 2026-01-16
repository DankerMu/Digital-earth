from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from observability import JsonFormatter, make_api_error


def _write_config(dir_path: Path, env: str, data: dict) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{env}.json").write_text(json.dumps(data), encoding="utf-8")


def _base_config(*, debug: bool = True) -> dict:
    return {
        "api": {"host": "0.0.0.0", "port": 8000, "debug": debug, "cors_origins": []},
        "pipeline": {"workers": 2, "batch_size": 100},
        "web": {"api_base_url": "http://localhost:8000"},
        "database": {"host": "localhost", "port": 5432, "name": "digital_earth"},
        "redis": {"host": "localhost", "port": 6379},
        "storage": {"tiles_bucket": "tiles", "raw_bucket": "raw"},
    }


@pytest.fixture
def api_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FastAPI:
    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config(debug=False))

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    from config import get_settings
    from main import create_app

    get_settings.cache_clear()
    yield create_app()
    get_settings.cache_clear()


def test_trace_id_is_generated_and_returned(api_app: FastAPI) -> None:
    client = TestClient(api_app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers.get("X-Trace-Id")


def test_trace_id_is_passthrough(api_app: FastAPI) -> None:
    client = TestClient(api_app)
    response = client.get("/health", headers={"X-Trace-Id": "trace-123"})
    assert response.status_code == 200
    assert response.headers["X-Trace-Id"] == "trace-123"


def test_invalid_trace_id_header_is_ignored(api_app: FastAPI) -> None:
    client = TestClient(api_app)

    blank = client.get("/health", headers={"X-Trace-Id": " "})
    assert blank.status_code == 200
    assert blank.headers["X-Trace-Id"] != " "

    too_long = "a" * 129
    long = client.get("/health", headers={"X-Trace-Id": too_long})
    assert long.status_code == 200
    assert long.headers["X-Trace-Id"] != too_long


def test_http_403_maps_to_40300(api_app: FastAPI) -> None:
    @api_app.get("/forbidden")
    def forbidden() -> None:
        raise HTTPException(status_code=403, detail="Forbidden")

    client = TestClient(api_app)
    response = client.get("/forbidden", headers={"X-Trace-Id": "trace403"})
    assert response.status_code == 403
    assert response.headers["X-Trace-Id"] == "trace403"
    assert response.json() == {
        "error_code": 40300,
        "message": "Forbidden",
        "trace_id": "trace403",
    }


def test_unknown_4xx_maps_to_40000(api_app: FastAPI) -> None:
    @api_app.get("/teapot")
    def teapot() -> None:
        raise HTTPException(status_code=418, detail="I'm a teapot")

    client = TestClient(api_app)
    response = client.get("/teapot", headers={"X-Trace-Id": "trace418"})
    assert response.status_code == 418
    assert response.headers["X-Trace-Id"] == "trace418"
    assert response.json() == {
        "error_code": 40000,
        "message": "I'm a teapot",
        "trace_id": "trace418",
    }


def test_make_api_error_handles_unknown_status_code() -> None:
    api_error = make_api_error(status_code=999)
    assert api_error.status_code == 999
    assert api_error.error_code == 50000
    assert api_error.message == "Error"
    assert api_error.trace_id


def test_error_response_contains_trace_id(api_app: FastAPI) -> None:
    client = TestClient(api_app)
    response = client.get("/nope")
    assert response.status_code == 404
    trace_id = response.headers["X-Trace-Id"]
    assert trace_id
    assert response.json() == {
        "error_code": 40400,
        "message": "Not Found",
        "trace_id": trace_id,
    }


def test_validation_error_is_400_with_trace_id(api_app: FastAPI) -> None:
    @api_app.get("/items")
    def items(limit: int) -> dict[str, int]:
        return {"limit": limit}

    client = TestClient(api_app)
    response = client.get("/items?limit=nope")
    assert response.status_code == 400
    trace_id = response.headers["X-Trace-Id"]
    assert response.json() == {
        "error_code": 40000,
        "message": "Bad Request",
        "trace_id": trace_id,
    }


def test_unhandled_error_is_500_with_trace_id(api_app: FastAPI) -> None:
    @api_app.get("/boom")
    def boom() -> None:
        raise RuntimeError("boom")

    client = TestClient(api_app)
    response = client.get("/boom")
    assert response.status_code == 500
    trace_id = response.headers["X-Trace-Id"]
    assert response.json() == {
        "error_code": 50000,
        "message": "Internal Server Error",
        "trace_id": trace_id,
    }


def test_logs_are_json_and_include_trace_id(api_app: FastAPI, caplog) -> None:
    client = TestClient(api_app)
    caplog.set_level("INFO")
    response = client.get("/health", headers={"X-Trace-Id": "trace-abc"})
    assert response.status_code == 200

    record = next(
        item
        for item in caplog.records
        if item.name == "api.request" and item.getMessage() == "request.completed"
    )
    assert record.trace_id == "trace-abc"

    payload = json.loads(JsonFormatter().format(record))
    assert set(payload) == {"timestamp", "level", "trace_id", "message", "extra"}
    assert payload["trace_id"] == "trace-abc"
    assert payload["level"] == "info"
    assert payload["extra"]["path"] == "/health"
    assert payload["extra"]["status_code"] == 200
