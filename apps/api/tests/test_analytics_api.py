from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from redis_fakes import FakeRedis


def _write_config(dir_path: Path, env: str, data: dict) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{env}.json").write_text(json.dumps(data), encoding="utf-8")


def _write_yaml(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _base_config(*, tiles_dir: str | None = None) -> dict:
    storage: dict = {"tiles_bucket": "tiles", "raw_bucket": "raw"}
    if tiles_dir is not None:
        storage["tiles_dir"] = tiles_dir

    return {
        "api": {
            "host": "0.0.0.0",
            "port": 8000,
            "debug": True,
            "cors_origins": [],
            "rate_limit": {"enabled": False},
        },
        "pipeline": {"workers": 2, "batch_size": 100, "data_source": "local"},
        "web": {"api_base_url": "http://localhost:8000"},
        "database": {"host": "localhost", "port": 5432, "name": "digital_earth"},
        "redis": {"host": "localhost", "port": 6379},
        "storage": storage,
    }


def _make_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    db_url: str,
    tiles_dir: Path | None = None,
) -> tuple[TestClient, FakeRedis]:
    monkeypatch.chdir(tmp_path)

    config_dir = tmp_path / "config"
    _write_config(
        config_dir,
        "dev",
        _base_config(tiles_dir=str(tiles_dir) if tiles_dir is not None else None),
    )

    _write_yaml(
        config_dir / "snow-statistics.yaml",
        "\n".join(
            [
                "schema_version: 1",
                "windows:",
                "  rolling_days: [7, 30]",
                "metrics:",
                "  - id: snowfall_sum",
                "    source: snowfall_mm",
                "    reducer: sum",
                "    windows: rolling_days",
                "    output_units: mm",
                "",
            ]
        ),
    )

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

    from models import Base

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    redis = FakeRedis(use_real_time=False)
    monkeypatch.setattr(main_module, "create_redis_client", lambda _url: redis)
    return TestClient(main_module.create_app()), redis


def test_analytics_snow_definition_endpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'analytics.db'}"
    client, _redis = _make_client(
        monkeypatch, tmp_path, db_url=db_url
    )
    resp = client.get("/api/v1/analytics/snow/definition")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["schema_version"] == 1
    assert payload["definition"]["schema_version"] == 1
    assert payload["definition"]["windows"]["rolling_days"] == [7, 30]


def test_analytics_historical_statistics_lists_items_and_templates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'analytics.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    from models import HistoricalStatisticArtifact

    engine = create_engine(db_url)
    with Session(engine) as session:
        session.add(
            HistoricalStatisticArtifact(
                source="cldas",
                variable="SNOWFALL",
                window_kind="rolling_days",
                window_key="20260108T000000Z-P7D",
                version="v1",
                window_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
                window_end=datetime(2026, 1, 8, tzinfo=timezone.utc),
                samples=168,
                dataset_path="cldas/SNOWFALL/rolling_days/v1/20260108T000000Z-P7D/statistics.nc",
                metadata_path="cldas/SNOWFALL/rolling_days/v1/20260108T000000Z-P7D/statistics.nc.meta.json",
                extra={"schema_version": 1},
            )
        )
        session.commit()

    resp = client.get("/api/v1/analytics/historical/statistics?fmt=png")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["source"] == "cldas"
    assert item["window_key"] == "20260108T000000Z-P7D"
    assert "sum" in item["tiles"]
    assert item["tiles"]["sum"]["template"].startswith(
        "/api/v1/tiles/statistics/cldas/snowfall/sum/v1/20260108T000000Z-P7D/"
    )


def test_analytics_bias_tile_sets_lists_items_and_templates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'analytics.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    from models import BiasTileSet

    engine = create_engine(db_url)
    with Session(engine) as session:
        session.add(
            BiasTileSet(
                layer="bias/temp",
                time_key="20260101T000000Z",
                level_key="sfc",
                min_zoom=0,
                max_zoom=6,
                formats=["png"],
            )
        )
        session.commit()

    resp = client.get("/api/v1/analytics/bias/tile-sets?layer=bias/temp&fmt=png")
    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["layer"] == "bias/temp"
    assert item["tile"]["template"].startswith(
        "/api/v1/tiles/bias/temp/20260101T000000Z/sfc/"
    )


def test_tiles_can_serve_from_local_filesystem(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tiles_root = tmp_path / "Data" / "tiles"
    target = tiles_root / "layer" / "0" / "0" / "0.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x" * 2048, encoding="utf-8")

    client, _redis = _make_client(
        monkeypatch,
        tmp_path,
        db_url=f"sqlite+pysqlite:///{tmp_path / 'analytics.db'}",
        tiles_dir=tiles_root,
    )

    ok = client.get("/api/v1/tiles/layer/0/0/0.json", headers={"Accept-Encoding": "gzip"})
    assert ok.status_code == 200
    assert ok.headers["content-encoding"] == "gzip"
    assert ok.headers["vary"] == "Accept-Encoding"
    assert ok.headers["cache-control"] == "public, max-age=3600"
    assert ok.headers["etag"].startswith('"sha256-')

    etag = ok.headers["etag"]
    cached = client.get(
        "/api/v1/tiles/layer/0/0/0.json",
        headers={"If-None-Match": etag, "Accept-Encoding": "gzip;q=0"},
    )
    assert cached.status_code == 304
