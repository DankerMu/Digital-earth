from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient


def _write_config(dir_path: Path, env: str, data: dict) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{env}.json").write_text(json.dumps(data), encoding="utf-8")


def _base_config() -> dict:
    return {
        "api": {"host": "0.0.0.0", "port": 8000, "debug": True, "cors_origins": []},
        "pipeline": {"workers": 2, "batch_size": 100},
        "web": {"api_base_url": "http://localhost:8000"},
        "database": {"host": "localhost", "port": 5432, "name": "digital_earth"},
        "redis": {"host": "localhost", "port": 6379},
        "storage": {"tiles_bucket": "tiles", "raw_bucket": "raw"},
    }


def _write_attribution(
    config_dir: Path, *, version: str = "1.0.0", extra_disclaimer: Optional[str] = None
) -> None:
    lines = [
        "schema_version: 1",
        f'version: "{version}"',
        'updated_at: "2026-01-16"',
        "",
        "sources:",
        "  - id: demo",
        '    name: "Demo Weather Dataset"',
        '    attribution: "© Demo Provider"',
        "",
        "disclaimer:",
        '  - "仅供参考"',
        '  - " "',
    ]
    if extra_disclaimer:
        lines.append(f'  - "{extra_disclaimer}"')
    (config_dir / "attribution.yaml").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _make_client(monkeypatch: pytest.MonkeyPatch, config_dir: Path) -> TestClient:
    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    from attribution_config import get_attribution_payload
    from config import get_settings
    from main import create_app

    get_settings.cache_clear()
    get_attribution_payload.cache_clear()

    return TestClient(create_app())


def test_attribution_returns_text_and_etag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())
    _write_attribution(config_dir, version="9.9.9")

    client = _make_client(monkeypatch, config_dir)

    response = client.get("/api/v1/attribution")
    assert response.status_code == 200
    assert response.headers["x-attribution-version"] == "9.9.9"
    assert response.headers["cache-control"] == "public, max-age=0, must-revalidate"
    assert response.headers["content-type"].startswith("text/plain")

    etag = response.headers["etag"]
    assert etag.startswith('"sha256-')
    assert "Attribution (v9.9.9)" in response.text
    assert "Sources:" in response.text
    assert "Disclaimer:" in response.text

    cached = client.get("/api/v1/attribution", headers={"If-None-Match": etag})
    assert cached.status_code == 304
    assert cached.headers["etag"] == etag
    assert cached.text == ""


def test_attribution_cache_invalidation_on_update(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())
    _write_attribution(config_dir, version="1.0.0")

    client = _make_client(monkeypatch, config_dir)

    first = client.get("/api/v1/attribution")
    assert first.status_code == 200
    first_etag = first.headers["etag"]

    time.sleep(0.01)
    _write_attribution(config_dir, version="1.0.1", extra_disclaimer="变更生效")

    second = client.get("/api/v1/attribution")
    assert second.status_code == 200
    assert second.headers["etag"] != first_etag
    assert "Attribution (v1.0.1)" in second.text
    assert "变更生效" in second.text


def test_attribution_if_none_match_wildcard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())
    _write_attribution(config_dir)

    client = _make_client(monkeypatch, config_dir)

    baseline = client.get("/api/v1/attribution")
    assert baseline.status_code == 200
    etag = baseline.headers["etag"]

    cached = client.get("/api/v1/attribution", headers={"If-None-Match": "*"})
    assert cached.status_code == 304
    assert cached.headers["etag"] == etag


def test_attribution_missing_config_returns_500(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())

    client = _make_client(monkeypatch, config_dir)

    response = client.get("/api/v1/attribution")
    assert response.status_code == 500
    payload = response.json()
    assert payload["error_code"] == 50000
    assert "trace_id" in payload


def test_attribution_invalid_yaml_returns_500(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())
    (config_dir / "attribution.yaml").write_text(
        "schema_version: [\n", encoding="utf-8"
    )

    client = _make_client(monkeypatch, config_dir)

    response = client.get("/api/v1/attribution")
    assert response.status_code == 500
    payload = response.json()
    assert payload["error_code"] == 50000
    assert "trace_id" in payload
