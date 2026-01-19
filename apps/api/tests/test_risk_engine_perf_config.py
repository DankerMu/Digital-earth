from __future__ import annotations

import pytest

from risk_engine import (
    BATCH_EVAL_CHUNK_SIZE_ENV,
    DEFAULT_EVAL_CHUNK_SIZE,
    DEFAULT_MAX_WORKERS_CAP,
    MAX_WORKERS_ENV,
    RiskEngineInputError,
    _chunked,
    _resolve_eval_chunk_size,
    _resolve_max_workers,
)


def test_resolve_max_workers_prefers_explicit_value() -> None:
    assert _resolve_max_workers(0) == 1
    assert _resolve_max_workers(3) == 3


def test_resolve_max_workers_supports_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MAX_WORKERS_ENV, "4")
    assert _resolve_max_workers(None) == 4

    monkeypatch.setenv(MAX_WORKERS_ENV, "not-an-int")
    resolved = _resolve_max_workers(None)
    assert 1 <= resolved <= DEFAULT_MAX_WORKERS_CAP


def test_resolve_eval_chunk_size_supports_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BATCH_EVAL_CHUNK_SIZE_ENV, "256")
    assert _resolve_eval_chunk_size() == 256

    monkeypatch.setenv(BATCH_EVAL_CHUNK_SIZE_ENV, "not-an-int")
    assert _resolve_eval_chunk_size() == DEFAULT_EVAL_CHUNK_SIZE


def test_chunked_rejects_non_positive_batch_size() -> None:
    with pytest.raises(RiskEngineInputError):
        list(_chunked([], batch_size=0))
