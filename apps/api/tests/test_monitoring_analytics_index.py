from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_indexer_upserts_historical_statistics(tmp_path: Path) -> None:
    from monitoring_analytics_index import index_historical_statistics
    from models import Base, HistoricalStatisticArtifact

    db_url = f"sqlite+pysqlite:///{tmp_path / 'idx.db'}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    statistics_root = tmp_path / "Data" / "statistics"
    meta_path = (
        statistics_root
        / "cldas"
        / "SNOWFALL"
        / "rolling_days"
        / "v1"
        / "20260108T000000Z-P7D"
        / "statistics.nc.meta.json"
    )
    _write_json(
        meta_path,
        {
            "schema_version": 1,
            "source_kind": "cldas",
            "output_source": "cldas",
            "variable": "SNOWFALL",
            "window_kind": "rolling_days",
            "window_key": "20260108T000000Z-P7D",
            "window_start": "2026-01-01T00:00:00Z",
            "window_end": "2026-01-08T00:00:00Z",
            "samples": 168,
            "version": "v1",
        },
    )

    with Session(engine) as session:
        created, updated = index_historical_statistics(
            session, statistics_root=statistics_root
        )
        session.commit()
        assert created == 1
        assert updated == 0

        created2, updated2 = index_historical_statistics(
            session, statistics_root=statistics_root
        )
        session.commit()
        assert created2 == 0
        assert updated2 == 1

        row = session.execute(select(HistoricalStatisticArtifact)).scalar_one()
        assert row.source == "cldas"
        assert row.variable == "SNOWFALL"
        assert row.window_key == "20260108T000000Z-P7D"
        assert row.dataset_path.endswith("/statistics.nc")
        assert row.metadata_path.endswith("/statistics.nc.meta.json")


def test_indexer_upserts_bias_tiles(tmp_path: Path) -> None:
    from monitoring_analytics_index import index_bias_tiles
    from models import Base, BiasTileSet

    db_url = f"sqlite+pysqlite:///{tmp_path / 'idx.db'}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    tiles_root = tmp_path / "Data" / "tiles"
    (tiles_root / "bias").mkdir(parents=True, exist_ok=True)
    (tiles_root / "bias" / "README.txt").write_text("x", encoding="utf-8")
    png = tiles_root / "bias" / "temp" / "20260101T000000Z" / "sfc" / "0" / "0" / "0.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    png.write_bytes(b"\x89PNG\r\n\x1a\n")

    webp = (
        tiles_root
        / "bias"
        / "temp"
        / "20260101T000000Z"
        / "sfc"
        / "1"
        / "0"
        / "0.webp"
    )
    webp.parent.mkdir(parents=True, exist_ok=True)
    webp.write_bytes(b"RIFF....WEBP")

    with Session(engine) as session:
        created, updated = index_bias_tiles(session, tiles_root=tiles_root)
        session.commit()
        assert created == 1
        assert updated == 0

        created2, updated2 = index_bias_tiles(session, tiles_root=tiles_root)
        session.commit()
        assert created2 == 0
        assert updated2 == 1

        row = session.execute(select(BiasTileSet)).scalar_one()
        assert row.layer == "bias/temp"
        assert row.time_key == "20260101T000000Z"
        assert row.level_key == "sfc"
        assert row.min_zoom == 0
        assert row.max_zoom == 1
        assert set(row.formats) == {"png", "webp"}


def test_indexer_main_runs_with_database_url(tmp_path: Path) -> None:
    from monitoring_analytics_index import main

    db_url = f"sqlite+pysqlite:///{tmp_path / 'idx.db'}"
    statistics_root = tmp_path / "stats"
    tiles_root = tmp_path / "tiles"

    code = main(
        [
            "--database-url",
            db_url,
            "--statistics-root",
            str(statistics_root),
            "--tiles-root",
            str(tiles_root),
        ]
    )
    assert code == 0


def test_indexer_helpers_cover_error_branches(tmp_path: Path) -> None:
    from monitoring_analytics_index import _detect_zoom_range, _load_json, _parse_iso_datetime

    with pytest.raises(ValueError, match="must not be empty"):
        _parse_iso_datetime("")
    parsed = _parse_iso_datetime("2026-01-01T00:00:00")
    assert parsed.tzinfo is not None

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("[1,2,3]", encoding="utf-8")
    with pytest.raises(ValueError, match="must be an object"):
        _load_json(bad_json)

    level_dir = tmp_path / "level"
    level_dir.mkdir()
    (level_dir / "not-a-dir.txt").write_text("x", encoding="utf-8")
    (level_dir / "x").mkdir()
    assert _detect_zoom_range(level_dir) is None


def test_index_bias_tiles_returns_empty_when_bias_root_missing(tmp_path: Path) -> None:
    from monitoring_analytics_index import index_bias_tiles
    from models import Base

    db_url = f"sqlite+pysqlite:///{tmp_path / 'idx.db'}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        created, updated = index_bias_tiles(session, tiles_root=tmp_path / "no-tiles")
        session.commit()
        assert created == 0
        assert updated == 0
