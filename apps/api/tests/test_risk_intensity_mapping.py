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
    from risk_intensity_config import get_risk_intensity_mappings_payload

    get_settings.cache_clear()
    get_effect_presets_payload.cache_clear()
    get_risk_intensity_mappings_payload.cache_clear()
    return TestClient(create_app())


def _write_risk_intensity_config(path: Path, *, intensity_scale: float = 1.0) -> None:
    text = "\n".join(
        [
            "level_1:",
            f"  intensity: {0.2 * intensity_scale}",
            "  particles: 100",
            "level_2:",
            f"  intensity: {0.4 * intensity_scale}",
            "  particles: 300",
            "level_3:",
            f"  intensity: {0.6 * intensity_scale}",
            "  particles: 600",
            "level_4:",
            f"  intensity: {0.8 * intensity_scale}",
            "  particles: 1000",
            "level_5:",
            f"  intensity: {1.0 * intensity_scale}",
            "  particles: 1500",
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")


def test_risk_intensity_mapping_returns_payload_and_etag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path)
    response = client.get("/api/v1/risk/intensity-mapping")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=0, must-revalidate"

    etag = response.headers["etag"]
    assert etag.startswith('"sha256-')

    payload = response.json()
    assert payload["merge_strategy"] == "max"
    assert isinstance(payload["mappings"], list)
    assert [item["level"] for item in payload["mappings"]] == [1, 2, 3, 4, 5]

    first = payload["mappings"][0]
    assert first["intensity"] == 0.2
    assert first["effect_params"]["particle_count"] == 100
    assert "opacity" in first["effect_params"]
    assert "speed" in first["effect_params"]


def test_risk_intensity_mapping_if_none_match_returns_304(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path)
    first = client.get("/api/v1/risk/intensity-mapping")
    assert first.status_code == 200
    etag = first.headers["etag"]

    cached = client.get(
        "/api/v1/risk/intensity-mapping", headers={"If-None-Match": etag}
    )
    assert cached.status_code == 304
    assert cached.headers["etag"] == etag
    assert cached.text == ""

    wildcard = client.get(
        "/api/v1/risk/intensity-mapping", headers={"If-None-Match": "*"}
    )
    assert wildcard.status_code == 304
    assert wildcard.headers["etag"] == etag


def test_risk_intensity_mapping_missing_config_returns_500(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "missing.yaml"
    monkeypatch.setenv("DIGITAL_EARTH_RISK_INTENSITY_CONFIG", str(missing))

    client = _make_client(monkeypatch, tmp_path)
    response = client.get("/api/v1/risk/intensity-mapping")
    assert response.status_code == 500
    payload = response.json()
    assert payload["error_code"] == 50000
    assert "trace_id" in payload


def test_risk_intensity_mapping_invalid_yaml_returns_500(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("level_1: [\n", encoding="utf-8")
    monkeypatch.setenv("DIGITAL_EARTH_RISK_INTENSITY_CONFIG", str(bad_yaml))

    client = _make_client(monkeypatch, tmp_path)
    response = client.get("/api/v1/risk/intensity-mapping")
    assert response.status_code == 500
    payload = response.json()
    assert payload["error_code"] == 50000
    assert "trace_id" in payload


def test_risk_intensity_mapping_cache_invalidation_on_update(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "risk-intensity.yaml"
    _write_risk_intensity_config(config_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_INTENSITY_CONFIG", str(config_path))

    client = _make_client(monkeypatch, tmp_path)
    first = client.get("/api/v1/risk/intensity-mapping")
    assert first.status_code == 200
    first_etag = first.headers["etag"]

    time.sleep(0.01)
    _write_risk_intensity_config(config_path, intensity_scale=0.9)

    second = client.get("/api/v1/risk/intensity-mapping")
    assert second.status_code == 200
    assert second.headers["etag"] != first_etag
