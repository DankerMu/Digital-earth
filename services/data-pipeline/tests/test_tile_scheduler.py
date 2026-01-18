from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


def test_tile_scheduler_config_loads_from_config_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))

    (config_dir / "tile-scheduler.yaml").write_text(
        "\n".join(
            [
                "schema_version: 1",
                "enabled: true",
                "max_workers: 8",
                "max_retries: 5",
                "progress_log_every: 2",
                "backoff:",
                "  base_seconds: 0.5",
                "  factor: 2.0",
                "  max_seconds: 5.0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    from tile_scheduler.config import get_tile_scheduler_config

    get_tile_scheduler_config.cache_clear()
    cfg = get_tile_scheduler_config()
    assert cfg.enabled is True
    assert cfg.max_workers == 8
    assert cfg.max_retries == 5
    assert cfg.progress_log_every == 2
    assert cfg.backoff.base_seconds == 0.5
    assert cfg.backoff.factor == 2.0
    assert cfg.backoff.max_seconds == 5.0


def test_tile_scheduler_config_reports_yaml_errors(tmp_path: Path) -> None:
    from tile_scheduler.config import load_tile_scheduler_config

    path = tmp_path / "tile-scheduler.yaml"
    path.write_text("schema_version: [", encoding="utf-8")
    with pytest.raises(ValueError, match="Failed to load tile scheduler YAML"):
        load_tile_scheduler_config(path)

    path.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="tile scheduler config must be a mapping"):
        load_tile_scheduler_config(path)

    path.write_text("schema_version: 999\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid tile scheduler config"):
        load_tile_scheduler_config(path)


def test_get_tile_scheduler_config_raises_when_missing(tmp_path: Path) -> None:
    from tile_scheduler.config import get_tile_scheduler_config

    get_tile_scheduler_config.cache_clear()
    with pytest.raises(FileNotFoundError, match="tile scheduler config file not found"):
        get_tile_scheduler_config(tmp_path / "missing.yaml")


def test_tile_worker_retries_and_succeeds(caplog: pytest.LogCaptureFixture) -> None:
    from tile_scheduler.worker import ExponentialBackoff, TileWorker, build_tile_job

    sleep_calls: list[float] = []

    def sleep(delay: float) -> None:
        sleep_calls.append(delay)

    attempts = {"count": 0}

    def handler(job: object) -> dict[str, object]:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("transient")
        return {"ok": True}

    worker = TileWorker(
        handler,  # type: ignore[arg-type]
        max_retries=5,
        backoff=ExponentialBackoff(base_seconds=1.0, factor=2.0, max_seconds=10.0),
        sleep=sleep,
    )
    job = build_tile_job(run_id="run", variable="TMP", level="surface", time="t0")

    caplog.set_level(logging.INFO)
    result = worker.process(job)
    assert result.status == "success"
    assert result.attempts == 3
    assert result.metadata == {"ok": True}
    assert sleep_calls == [1.0, 2.0]
    assert any(
        record.getMessage() == "tile_job_failed_retrying" for record in caplog.records
    )


def test_tile_worker_returns_failure_after_max_retries() -> None:
    from tile_scheduler.worker import ExponentialBackoff, TileWorker, build_tile_job

    sleep_calls: list[float] = []

    def sleep(delay: float) -> None:
        sleep_calls.append(delay)

    def handler(job: object) -> dict[str, object]:
        raise RuntimeError("permanent")

    worker = TileWorker(
        handler,  # type: ignore[arg-type]
        max_retries=2,
        backoff=ExponentialBackoff(base_seconds=1.0, factor=2.0, max_seconds=10.0),
        sleep=sleep,
    )
    job = build_tile_job(run_id="run", variable="TMP", level="surface", time="t0")
    result = worker.process(job)

    assert result.status == "failed"
    assert result.attempts == 3
    assert "permanent" in (result.error or "")
    assert sleep_calls == [1.0, 2.0]


def test_tile_worker_build_tile_job_validates_fields() -> None:
    from tile_scheduler.worker import build_tile_job

    with pytest.raises(ValueError, match="run_id"):
        build_tile_job(run_id="", variable="TMP", level="surface", time="t0")
    with pytest.raises(ValueError, match="variable"):
        build_tile_job(run_id="r", variable="", level="surface", time="t0")
    with pytest.raises(ValueError, match="level"):
        build_tile_job(run_id="r", variable="TMP", level="", time="t0")
    with pytest.raises(ValueError, match="time"):
        build_tile_job(run_id="r", variable="TMP", level="surface", time="")


def test_exponential_backoff_caps_delay() -> None:
    from tile_scheduler.worker import ExponentialBackoff

    backoff = ExponentialBackoff(base_seconds=1.0, factor=2.0, max_seconds=5.0)
    assert backoff.delay_seconds(0) == 0.0
    assert backoff.delay_seconds(1) == 1.0
    assert backoff.delay_seconds(2) == 2.0
    assert backoff.delay_seconds(3) == 4.0
    assert backoff.delay_seconds(4) == 5.0


def test_tile_scheduler_runs_jobs_and_logs_progress(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from tile_scheduler.scheduler import TileScheduler
    from tile_scheduler.worker import TileWorker, build_tile_job

    def handler(job: object) -> dict[str, object]:
        job_dict = getattr(job, "__dict__", {})
        variable = job_dict.get("variable")
        if variable == "BAD":
            raise RuntimeError("boom")
        return {"ok": True}

    worker = TileWorker(handler, max_retries=0)  # type: ignore[arg-type]
    scheduler = TileScheduler(worker=worker, max_workers=2, progress_log_every=2)

    jobs = [
        build_tile_job(run_id="run", variable="A", level="surface", time="t0"),
        build_tile_job(run_id="run", variable="B", level="surface", time="t0"),
        build_tile_job(run_id="run", variable="BAD", level="surface", time="t0"),
    ]

    caplog.set_level(logging.INFO)
    summary = scheduler.run(run_id="run", jobs=jobs)
    assert summary.total_jobs == 3
    assert summary.succeeded == 2
    assert summary.failed == 1

    progress = [
        record
        for record in caplog.records
        if record.getMessage() == "tile_scheduler_progress"
    ]
    assert {record.completed for record in progress} == {2, 3}
    assert any(
        record.getMessage() == "tile_scheduler_started" for record in caplog.records
    )
    assert any(
        record.getMessage() == "tile_scheduler_finished" for record in caplog.records
    )


def test_tile_scheduler_uses_provided_executor() -> None:
    from tile_scheduler.scheduler import TileScheduler
    from tile_scheduler.worker import TileWorker, build_tile_job

    worker = TileWorker(lambda job: {"ok": True}, max_retries=0)
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        scheduler = TileScheduler(worker=worker, max_workers=99, executor=executor)
        summary = scheduler.run(
            run_id="run",
            jobs=[
                build_tile_job(run_id="run", variable="TMP", level="surface", time="t0")
            ],
        )
        assert summary.succeeded == 1
        assert executor.submit(lambda: 41 + 1).result() == 42
    finally:
        executor.shutdown(wait=True)


def test_tile_scheduler_empty_jobs_returns_immediately() -> None:
    from tile_scheduler.scheduler import TileScheduler
    from tile_scheduler.worker import TileWorker

    scheduler = TileScheduler(worker=TileWorker(lambda job: None))
    summary = scheduler.run(run_id="run", jobs=[])
    assert summary.total_jobs == 0
    assert summary.succeeded == 0
    assert summary.failed == 0
