from __future__ import annotations

from types import SimpleNamespace

import pytest

import db as db_module


def test_get_engine_falls_back_to_settings_when_database_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_module.get_engine.cache_clear()

    monkeypatch.setattr(
        db_module,
        "get_settings",
        lambda: SimpleNamespace(database=SimpleNamespace(dsn="sqlite+pysqlite:///:memory:")),
    )

    engine = db_module.get_engine()
    assert "sqlite" in str(engine.url)
