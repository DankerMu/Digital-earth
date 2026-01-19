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
    from risk_rules_config import get_risk_rules_payload

    get_settings.cache_clear()
    get_effect_presets_payload.cache_clear()
    get_risk_intensity_mappings_payload.cache_clear()
    get_risk_rules_payload.cache_clear()
    return TestClient(create_app())


def _write_risk_rules_config(path: Path, *, snowfall_score_at_10: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(
        [
            "schema_version: 1",
            "",
            "factors:",
            "  - id: snowfall",
            "    weight: 1.0",
            "    direction: ascending",
            "    thresholds:",
            "      - threshold: 0",
            "        score: 0",
            "      - threshold: 10",
            f"        score: {snowfall_score_at_10}",
            "",
            "  - id: snow_depth",
            "    weight: 1.0",
            "    direction: ascending",
            "    thresholds:",
            "      - threshold: 0",
            "        score: 0",
            "",
            "  - id: wind",
            "    weight: 1.0",
            "    direction: ascending",
            "    thresholds:",
            "      - threshold: 0",
            "        score: 0",
            "",
            "  - id: temp",
            "    weight: 1.0",
            "    direction: descending",
            "    thresholds:",
            "      - threshold: 5",
            "        score: 0",
            "",
            "final_levels:",
            "  - min_score: 0",
            "    level: 1",
            "  - min_score: 1",
            "    level: 2",
            "  - min_score: 2",
            "    level: 3",
            "  - min_score: 3",
            "    level: 4",
            "  - min_score: 4",
            "    level: 5",
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")


def test_risk_rules_returns_model_and_etag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config" / "risk-rules.yaml"
    _write_risk_rules_config(config_path, snowfall_score_at_10=1)

    client = _make_client(monkeypatch, tmp_path)
    response = client.get("/api/v1/risk/rules")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=0, must-revalidate"

    etag = response.headers["etag"]
    assert etag.startswith('"sha256-')

    payload = response.json()
    assert payload["schema_version"] == 1
    assert [item["id"] for item in payload["factors"]] == [
        "snowfall",
        "snow_depth",
        "wind",
        "temp",
    ]
    assert [item["level"] for item in payload["final_levels"]] == [1, 2, 3, 4, 5]


def test_risk_rules_if_none_match_returns_304(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(config_path, snowfall_score_at_10=1)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(config_path))

    client = _make_client(monkeypatch, tmp_path)
    first = client.get("/api/v1/risk/rules")
    assert first.status_code == 200
    etag = first.headers["etag"]

    cached = client.get("/api/v1/risk/rules", headers={"If-None-Match": etag})
    assert cached.status_code == 304
    assert cached.headers["etag"] == etag
    assert cached.text == ""

    wildcard = client.get("/api/v1/risk/rules", headers={"If-None-Match": "*"})
    assert wildcard.status_code == 304
    assert wildcard.headers["etag"] == etag


def test_risk_rules_evaluate_returns_result_and_rules_etag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(config_path, snowfall_score_at_10=1)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(config_path))

    client = _make_client(monkeypatch, tmp_path)
    response = client.post(
        "/api/v1/risk/rules/evaluate",
        json={"snowfall": 10, "snow_depth": 0, "wind": 0, "temp": 0},
    )
    assert response.status_code == 200
    assert response.headers["x-risk-rules-etag"].startswith('"sha256-')

    payload = response.json()
    assert payload["level"] == 1
    assert payload["score"] == pytest.approx(0.25)
    assert len(payload["factors"]) == 4


def test_risk_rules_cache_invalidation_on_update(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(config_path, snowfall_score_at_10=1)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(config_path))

    client = _make_client(monkeypatch, tmp_path)
    first = client.post(
        "/api/v1/risk/rules/evaluate",
        json={"snowfall": 10, "snow_depth": 0, "wind": 0, "temp": 0},
    )
    assert first.status_code == 200
    first_etag = first.headers["x-risk-rules-etag"]
    assert first.json()["level"] == 1

    time.sleep(0.01)
    _write_risk_rules_config(config_path, snowfall_score_at_10=4)

    second = client.post(
        "/api/v1/risk/rules/evaluate",
        json={"snowfall": 10, "snow_depth": 0, "wind": 0, "temp": 0},
    )
    assert second.status_code == 200
    assert second.headers["x-risk-rules-etag"] != first_etag
    assert second.json()["level"] == 2


def test_risk_rules_evaluate_missing_config_returns_500(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "missing.yaml"
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(missing))

    client = _make_client(monkeypatch, tmp_path)
    response = client.post(
        "/api/v1/risk/rules/evaluate",
        json={"snowfall": 0, "snow_depth": 0, "wind": 0, "temp": 0},
    )
    assert response.status_code == 500
    payload = response.json()
    assert payload["error_code"] == 50000
    assert "trace_id" in payload


def test_risk_rules_evaluate_invalid_values_returns_400(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config" / "risk-rules.yaml"
    _write_risk_rules_config(config_path, snowfall_score_at_10=1)

    client = _make_client(monkeypatch, tmp_path)
    response = client.post(
        "/api/v1/risk/rules/evaluate",
        json={"snowfall": "nan", "snow_depth": 0, "wind": 0, "temp": 0},
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == 40000
    assert payload["message"] == "snowfall must be a finite number"


def test_risk_rules_missing_config_returns_500(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "missing.yaml"
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(missing))

    client = _make_client(monkeypatch, tmp_path)
    response = client.get("/api/v1/risk/rules")
    assert response.status_code == 500
    payload = response.json()
    assert payload["error_code"] == 50000
    assert "trace_id" in payload


def test_risk_rules_invalid_yaml_returns_500(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("schema_version: [\n", encoding="utf-8")
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(bad_yaml))

    client = _make_client(monkeypatch, tmp_path)
    response = client.get("/api/v1/risk/rules")
    assert response.status_code == 500
    payload = response.json()
    assert payload["error_code"] == 50000
    assert "trace_id" in payload


def test_risk_rules_invalid_config_returns_500(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "factors: []",
                "final_levels:",
                "  - min_score: 0",
                "    level: 1",
                "  - min_score: 1",
                "    level: 2",
                "  - min_score: 2",
                "    level: 3",
                "  - min_score: 3",
                "    level: 4",
                "  - min_score: 4",
                "    level: 5",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(invalid))

    client = _make_client(monkeypatch, tmp_path)
    response = client.get("/api/v1/risk/rules")
    assert response.status_code == 500
    payload = response.json()
    assert payload["error_code"] == 50000
    assert "trace_id" in payload
