from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest


def test_ingest_run_store_persists_runs(tmp_path: Path) -> None:
    from scheduler.runs import IngestRunStore

    path = tmp_path / "runs.json"
    store = IngestRunStore(storage_path=path, max_entries=10)

    run = store.create_run()
    finished = store.update_run(
        run.run_id,
        status="success",
        end_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        attempts=2,
    )

    reloaded = IngestRunStore(storage_path=path, max_entries=10)
    runs = reloaded.list_runs(limit=10)
    assert len(runs) == 1
    assert runs[0].run_id == finished.run_id
    assert runs[0].status == "success"
    assert runs[0].attempts == 2


def test_alert_manager_triggers_once_per_failure_streak() -> None:
    from scheduler.alert_manager import AlertManager
    from scheduler.runs import IngestRun

    seen: list[dict[str, Any]] = []

    async def send_webhook(
        url: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> None:
        seen.append({"url": url, "payload": dict(payload), "headers": dict(headers)})

    alert = AlertManager(
        consecutive_failures_threshold=2,
        webhook_url="https://example.invalid/hook",
        webhook_headers={"X-Test": "1"},
        send_webhook=send_webhook,
    )

    run1 = IngestRun(
        run_id="r1",
        status="failed",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        error="boom",
        attempts=1,
    )
    asyncio.run(alert.record_run(run1))
    assert alert.state.consecutive_failures == 1
    assert seen == []

    run2 = run1.model_copy(update={"run_id": "r2"})
    asyncio.run(alert.record_run(run2))
    assert alert.state.consecutive_failures == 2
    assert len(seen) == 1
    assert seen[0]["payload"]["event"] == "ingest.consecutive_failures"
    assert seen[0]["payload"]["threshold"] == 2
    assert seen[0]["payload"]["consecutive_failures"] == 2
    assert seen[0]["payload"]["latest_run"]["run_id"] == "r2"

    run3 = run1.model_copy(update={"run_id": "r3"})
    asyncio.run(alert.record_run(run3))
    assert alert.state.consecutive_failures == 3
    assert len(seen) == 1

    success = run1.model_copy(
        update={"run_id": "ok", "status": "success", "error": None}
    )
    asyncio.run(alert.record_run(success))
    assert alert.state.consecutive_failures == 0

    asyncio.run(alert.record_run(run1.model_copy(update={"run_id": "r4"})))
    asyncio.run(alert.record_run(run1.model_copy(update={"run_id": "r5"})))
    assert len(seen) == 2


def test_ingest_scheduler_retries_with_exponential_backoff() -> None:
    from scheduler.ingest_scheduler import ExponentialBackoff, IngestScheduler
    from scheduler.runs import IngestRunStore

    store = IngestRunStore(storage_path=None, max_entries=10)
    sleep_calls: list[float] = []

    async def sleep(delay: float) -> None:
        sleep_calls.append(delay)

    attempts = {"count": 0}

    async def ingest() -> None:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("transient")

    scheduler = IngestScheduler(
        cron="0 * * * *",
        ingest=ingest,
        run_store=store,
        max_retries=3,
        backoff=ExponentialBackoff(base_seconds=1.0, factor=2.0, max_seconds=10.0),
        sleep=sleep,
        now=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    run = asyncio.run(scheduler.run_once())
    assert run.status == "success"
    assert run.attempts == 3
    assert sleep_calls == [1.0, 2.0]


def test_ingest_scheduler_records_failed_run_after_max_retries() -> None:
    from scheduler.ingest_scheduler import ExponentialBackoff, IngestScheduler
    from scheduler.runs import IngestRunStore

    store = IngestRunStore(storage_path=None, max_entries=10)
    sleep_calls: list[float] = []

    async def sleep(delay: float) -> None:
        sleep_calls.append(delay)

    async def ingest() -> None:
        raise RuntimeError("permanent")

    scheduler = IngestScheduler(
        cron="0 * * * *",
        ingest=ingest,
        run_store=store,
        max_retries=2,
        backoff=ExponentialBackoff(base_seconds=1.0, factor=2.0, max_seconds=10.0),
        sleep=sleep,
        now=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    run = asyncio.run(scheduler.run_once())
    assert run.status == "failed"
    assert run.attempts == 3
    assert "permanent" in (run.error or "")
    assert sleep_calls == [1.0, 2.0]


def test_ingest_scheduler_next_run_after_uses_cron_expression() -> None:
    from scheduler.ingest_scheduler import IngestScheduler

    async def ingest() -> None:
        return None

    scheduler = IngestScheduler(cron="0 * * * *", ingest=ingest)
    base = datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc)
    assert scheduler.next_run_after(base) == datetime(
        2026, 1, 1, 1, 0, tzinfo=timezone.utc
    )


def test_get_scheduler_config_loads_from_digital_earth_config_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scheduler.config import get_scheduler_config

    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))

    (config_dir / "scheduler.yaml").write_text(
        "\n".join(
            [
                "schema_version: 1",
                "enabled: true",
                'cron: "*/5 * * * *"',
                "max_retries: 1",
                "runs:",
                '  storage_path: ".cache/test-runs.json"',
                "  max_entries: 10",
                "",
            ]
        ),
        encoding="utf-8",
    )

    get_scheduler_config.cache_clear()
    cfg = get_scheduler_config()
    assert cfg.enabled is True
    assert cfg.cron == "*/5 * * * *"
    assert cfg.max_retries == 1
    assert cfg.runs.max_entries == 10


def test_get_ingest_run_store_falls_back_when_config_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    from scheduler.config import get_scheduler_config
    from scheduler.runs import get_ingest_run_store, reset_ingest_run_store_for_tests

    get_scheduler_config.cache_clear()
    reset_ingest_run_store_for_tests()

    store = get_ingest_run_store()
    assert store.storage_path == Path(".cache/ingest-runs.json")


def test_factory_helpers_load_config_from_scheduler_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))

    (config_dir / "scheduler.yaml").write_text(
        "\n".join(
            [
                "schema_version: 1",
                "enabled: true",
                'cron: "0 * * * *"',
                "max_retries: 0",
                "alert:",
                "  consecutive_failures: 1",
                "  webhook_url:",
                "",
            ]
        ),
        encoding="utf-8",
    )

    from scheduler.config import get_scheduler_config

    get_scheduler_config.cache_clear()

    from scheduler.alert_manager import create_alert_manager
    from scheduler.ingest_scheduler import create_ingest_scheduler
    from scheduler.runs import IngestRun, IngestRunStore

    alert = create_alert_manager()
    failed_run = IngestRun(
        run_id="r",
        status="failed",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        error="boom",
        attempts=1,
    )
    asyncio.run(alert.record_run(failed_run))
    assert alert.state.alerted_for_streak is True

    async def ingest() -> None:
        raise RuntimeError("boom")

    store = IngestRunStore(storage_path=None, max_entries=10)
    scheduler = create_ingest_scheduler(ingest, run_store=store, alert_manager=alert)
    assert scheduler.cron == "0 * * * *"
    run = asyncio.run(scheduler.run_once())
    assert run.status == "failed"
    assert run.attempts == 1


def test_ingest_scheduler_triggers_on_success_hook(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from scheduler.ingest_scheduler import IngestScheduler
    from scheduler.runs import IngestRunStore

    store = IngestRunStore(storage_path=None, max_entries=10)
    seen: list[str] = []

    async def ingest() -> None:
        return None

    async def on_success(run: Any) -> None:
        seen.append(getattr(run, "run_id", ""))

    scheduler = IngestScheduler(
        cron="0 * * * *",
        ingest=ingest,
        run_store=store,
        max_retries=0,
        on_success=on_success,
        now=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    caplog.set_level(logging.ERROR)
    run = asyncio.run(scheduler.run_once())
    assert run.status == "success"
    assert len(seen) == 1


def test_ingest_scheduler_on_success_errors_are_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from scheduler.ingest_scheduler import IngestScheduler
    from scheduler.runs import IngestRunStore

    store = IngestRunStore(storage_path=None, max_entries=10)

    async def ingest() -> None:
        return None

    async def on_success(run: Any) -> None:
        raise RuntimeError("boom")

    scheduler = IngestScheduler(
        cron="0 * * * *",
        ingest=ingest,
        run_store=store,
        max_retries=0,
        on_success=on_success,
        now=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    caplog.set_level(logging.ERROR)
    run = asyncio.run(scheduler.run_once())
    assert run.status == "success"
    assert any(
        record.getMessage() == "ingest_on_success_failed" for record in caplog.records
    )
