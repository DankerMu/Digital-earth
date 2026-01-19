from __future__ import annotations

import json
import time
from pathlib import Path

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


def _make_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    from config import get_settings
    from legend_config import get_legend_config_payload
    from main import create_app

    get_settings.cache_clear()
    get_legend_config_payload.cache_clear()
    return TestClient(create_app())


def _write_legend(
    path: Path, *, colors: list[str], thresholds: list[float], labels: list[str]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"colors": colors, "thresholds": thresholds, "labels": labels},
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


def test_legends_returns_payload_and_etag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    legends_dir = tmp_path / "legends"
    _write_legend(
        legends_dir / "temperature.json",
        colors=["#000000", "#FFFFFF"],
        thresholds=[0, 1],
        labels=["0", "1"],
    )
    monkeypatch.setenv("DIGITAL_EARTH_LEGENDS_DIR", str(legends_dir))

    client = _make_client(monkeypatch, tmp_path)
    response = client.get("/api/v1/legends?layer_type=temperature")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=0, must-revalidate"

    etag = response.headers["etag"]
    assert etag.startswith('"sha256-')

    payload = response.json()
    assert payload == {
        "colors": ["#000000", "#FFFFFF"],
        "thresholds": [0.0, 1.0],
        "labels": ["0", "1"],
    }


def test_legends_if_none_match_returns_304(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    legends_dir = tmp_path / "legends"
    _write_legend(
        legends_dir / "temperature.json",
        colors=["#111111", "#222222"],
        thresholds=[-1, 2],
        labels=["-1", "2"],
    )
    monkeypatch.setenv("DIGITAL_EARTH_LEGENDS_DIR", str(legends_dir))

    client = _make_client(monkeypatch, tmp_path)
    first = client.get("/api/v1/legends?layer_type=temperature")
    assert first.status_code == 200
    etag = first.headers["etag"]

    cached = client.get(
        "/api/v1/legends?layer_type=temperature", headers={"If-None-Match": etag}
    )
    assert cached.status_code == 304
    assert cached.headers["etag"] == etag
    assert cached.text == ""

    wildcard = client.get(
        "/api/v1/legends?layer_type=temperature", headers={"If-None-Match": "*"}
    )
    assert wildcard.status_code == 304
    assert wildcard.headers["etag"] == etag


def test_legends_supports_alias_layer_types(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    legends_dir = tmp_path / "legends"
    _write_legend(
        legends_dir / "temperature.json",
        colors=["#000000", "#FFFFFF"],
        thresholds=[0, 1],
        labels=["0", "1"],
    )
    monkeypatch.setenv("DIGITAL_EARTH_LEGENDS_DIR", str(legends_dir))

    client = _make_client(monkeypatch, tmp_path)
    response = client.get("/api/v1/legends?layer_type=temp")
    assert response.status_code == 200
    payload = response.json()
    assert payload["thresholds"] == [0.0, 1.0]


def test_legends_invalid_layer_type_is_400(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path)
    response = client.get("/api/v1/legends?layer_type=nope")
    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == 40000
    assert "trace_id" in payload


def test_legends_missing_config_returns_500(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    legends_dir = tmp_path / "empty-legends"
    monkeypatch.setenv("DIGITAL_EARTH_LEGENDS_DIR", str(legends_dir))

    client = _make_client(monkeypatch, tmp_path)
    response = client.get("/api/v1/legends?layer_type=temperature")
    assert response.status_code == 500
    payload = response.json()
    assert payload["error_code"] == 50000
    assert "trace_id" in payload


def test_legends_invalid_config_returns_500(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    legends_dir = tmp_path / "legends"
    (legends_dir / "temperature.json").parent.mkdir(parents=True, exist_ok=True)
    (legends_dir / "temperature.json").write_text("not-json", encoding="utf-8")
    monkeypatch.setenv("DIGITAL_EARTH_LEGENDS_DIR", str(legends_dir))

    client = _make_client(monkeypatch, tmp_path)
    response = client.get("/api/v1/legends?layer_type=temperature")
    assert response.status_code == 500
    payload = response.json()
    assert payload["error_code"] == 50000
    assert "trace_id" in payload


def test_legends_supports_path_param(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    legends_dir = tmp_path / "legends"
    _write_legend(
        legends_dir / "wind.json",
        colors=["#000000", "#FFFFFF"],
        thresholds=[0, 1],
        labels=["0", "1"],
    )
    monkeypatch.setenv("DIGITAL_EARTH_LEGENDS_DIR", str(legends_dir))

    client = _make_client(monkeypatch, tmp_path)
    response = client.get("/api/v1/legends/wind")
    assert response.status_code == 200
    assert response.json()["colors"] == ["#000000", "#FFFFFF"]


def test_legends_unexpected_error_returns_500(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path)

    import routers.legends as legends_router

    def boom(_layer_type: str):
        raise RuntimeError("boom")

    monkeypatch.setattr(legends_router, "get_legend_config_payload", boom)

    response = client.get("/api/v1/legends?layer_type=temperature")
    assert response.status_code == 500
    payload = response.json()
    assert payload["error_code"] == 50000
    assert "trace_id" in payload


def test_legends_cache_invalidation_on_update(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    legends_dir = tmp_path / "legends"
    legend_path = legends_dir / "wind.json"
    _write_legend(
        legend_path,
        colors=["#000000", "#FFFFFF"],
        thresholds=[0, 10],
        labels=["0", "10"],
    )
    monkeypatch.setenv("DIGITAL_EARTH_LEGENDS_DIR", str(legends_dir))

    client = _make_client(monkeypatch, tmp_path)
    first = client.get("/api/v1/legends?layer_type=wind")
    assert first.status_code == 200
    first_etag = first.headers["etag"]

    time.sleep(0.01)
    _write_legend(
        legend_path,
        colors=["#FF0000", "#00FF00", "#0000FF"],
        thresholds=[0, 5, 10],
        labels=["0", "5", "10"],
    )

    second = client.get("/api/v1/legends?layer_type=wind")
    assert second.status_code == 200
    assert second.headers["etag"] != first_etag
    assert second.json()["colors"] == ["#FF0000", "#00FF00", "#0000FF"]
