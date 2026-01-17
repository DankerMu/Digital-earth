from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _write_config(dir_path: Path, env: str, data: dict) -> None:
    import json

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


def _make_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    from config import get_settings
    from effect_presets_config import get_effect_presets_payload
    from main import create_app

    get_settings.cache_clear()
    get_effect_presets_payload.cache_clear()
    return TestClient(create_app())


def _write_effect_presets(
    path: Path,
    *,
    version: int = 1,
    preset_id: str = "demo_rain",
    effect_type: str = "rain",
    intensity: int = 2,
) -> None:
    text = "\n".join(
        [
            f"schema_version: {version}",
            "",
            "presets:",
            f"  {preset_id}:",
            f"    effect_type: {effect_type}",
            f"    intensity: {intensity}",
            "    duration: 60",
            '    color_hint: "rgba(180, 200, 255, 0.5)"',
            "    spawn_rate: 80",
            "    particle_size: [0.5, 1.5]",
            "    wind_influence: 0.2",
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")


def test_effect_presets_returns_list_and_etag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path)
    response = client.get("/api/v1/effects/presets")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=0, must-revalidate"

    etag = response.headers["etag"]
    assert etag.startswith('"sha256-')

    payload = response.json()
    assert isinstance(payload, list)

    light_rain = next(item for item in payload if item["id"] == "light_rain")
    assert light_rain["effect_type"] == "rain"
    assert light_rain["risk_level"] == "low"
    assert light_rain["particle_size"] == {"min": 0.5, "max": 1.5}


def test_effect_presets_if_none_match_returns_304(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path)
    first = client.get("/api/v1/effects/presets")
    assert first.status_code == 200
    etag = first.headers["etag"]

    cached = client.get("/api/v1/effects/presets", headers={"If-None-Match": etag})
    assert cached.status_code == 304
    assert cached.headers["etag"] == etag
    assert cached.text == ""

    wildcard = client.get("/api/v1/effects/presets", headers={"If-None-Match": "*"})
    assert wildcard.status_code == 304
    assert wildcard.headers["etag"] == etag


def test_effect_presets_filter_by_effect_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path)
    response = client.get("/api/v1/effects/presets?effect_type=rain")
    assert response.status_code == 200
    payload = response.json()
    assert payload
    assert all(item["effect_type"] == "rain" for item in payload)


def test_effect_presets_invalid_effect_type_is_422(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path)
    response = client.get("/api/v1/effects/presets?effect_type=nope")
    # Validation error returns 400 with unified error format
    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == 40000
    assert "trace_id" in payload


def test_effect_presets_missing_config_returns_500(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "missing.yaml"
    monkeypatch.setenv("DIGITAL_EARTH_EFFECT_PRESETS_CONFIG", str(missing))

    client = _make_client(monkeypatch, tmp_path)
    response = client.get("/api/v1/effects/presets")
    assert response.status_code == 500
    payload = response.json()
    assert payload["error_code"] == 50000
    assert "trace_id" in payload


def test_effect_presets_invalid_yaml_returns_500(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("schema_version: [\n", encoding="utf-8")
    monkeypatch.setenv("DIGITAL_EARTH_EFFECT_PRESETS_CONFIG", str(bad_yaml))

    client = _make_client(monkeypatch, tmp_path)
    response = client.get("/api/v1/effects/presets")
    assert response.status_code == 500
    payload = response.json()
    assert payload["error_code"] == 50000
    assert "trace_id" in payload


def test_effect_presets_cache_invalidation_on_update(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "effect_presets.yaml"
    _write_effect_presets(config_path, preset_id="p1", intensity=2)
    monkeypatch.setenv("DIGITAL_EARTH_EFFECT_PRESETS_CONFIG", str(config_path))

    client = _make_client(monkeypatch, tmp_path)
    first = client.get("/api/v1/effects/presets")
    assert first.status_code == 200
    first_etag = first.headers["etag"]

    time.sleep(0.01)
    _write_effect_presets(config_path, preset_id="p2", intensity=5)

    second = client.get("/api/v1/effects/presets")
    assert second.status_code == 200
    assert second.headers["etag"] != first_etag
    payload = second.json()
    assert payload[0]["id"] == "p2"
    assert payload[0]["risk_level"] == "extreme"
