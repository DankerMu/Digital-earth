from __future__ import annotations

import pytest


def test_get_engine_falls_back_to_settings_dsn_when_database_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import db as db_module

    db_module.get_engine.cache_clear()
    monkeypatch.delenv("DATABASE_URL", raising=False)

    class _FakeDatabase:
        dsn = "sqlite+pysqlite:///:memory:"

    class _FakeSettings:
        database = _FakeDatabase()

    monkeypatch.setattr(db_module, "get_settings", lambda: _FakeSettings())

    engine = db_module.get_engine()
    try:
        assert str(engine.url) == "sqlite+pysqlite:///:memory:"
    finally:
        engine.dispose()
        db_module.get_engine.cache_clear()
