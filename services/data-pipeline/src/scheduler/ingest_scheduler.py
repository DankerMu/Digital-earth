from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from croniter import croniter

from scheduler.alert_manager import AlertManager
from scheduler.config import (
    SchedulerBackoffConfig,
    SchedulerConfig,
    get_scheduler_config,
)
from scheduler.runs import IngestRun, IngestRunStore, get_ingest_run_store

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ExponentialBackoff:
    base_seconds: float = 1.0
    factor: float = 2.0
    max_seconds: float = 300.0

    def delay_seconds(self, retry_number: int) -> float:
        if retry_number <= 0:
            return 0.0
        delay = self.base_seconds * (self.factor ** (retry_number - 1))
        return float(min(delay, self.max_seconds))


class IngestScheduler:
    def __init__(
        self,
        *,
        cron: str,
        ingest: Callable[[], Awaitable[None]],
        run_store: Optional[IngestRunStore] = None,
        alert_manager: Optional[AlertManager] = None,
        max_retries: int = 3,
        backoff: Optional[ExponentialBackoff] = None,
        now: Callable[[], datetime] = _utc_now,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._cron = cron.strip()
        self._ingest = ingest
        self._run_store = run_store or get_ingest_run_store()
        self._alert_manager = alert_manager
        self._max_retries = max_retries
        self._backoff = backoff or ExponentialBackoff()
        self._now = now
        self._sleep = sleep
        self._lock: Optional[asyncio.Lock] = None
        self._lock_init = threading.Lock()

        if self._cron == "":
            raise ValueError("cron must not be empty")
        if self._max_retries < 0:
            raise ValueError("max_retries must be >= 0")

    def _get_lock(self) -> asyncio.Lock:
        lock = self._lock
        if lock is not None:
            return lock
        with self._lock_init:
            lock = self._lock
            if lock is None:
                lock = asyncio.Lock()
                self._lock = lock
            return lock

    @property
    def cron(self) -> str:
        return self._cron

    def next_run_after(self, after: datetime) -> datetime:
        if after.tzinfo is None:
            after = after.replace(tzinfo=timezone.utc)
        itr = croniter(self._cron, after)
        nxt = itr.get_next(datetime)
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=timezone.utc)
        return nxt

    async def run_once(self) -> IngestRun:
        async with self._get_lock():
            run = self._run_store.create_run(start_time=self._now())
            attempts = 0
            try:
                while True:
                    attempts += 1
                    try:
                        await self._ingest()
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        retries_used = attempts - 1
                        if retries_used >= self._max_retries:
                            raise
                        retry_number = retries_used + 1
                        delay = self._backoff.delay_seconds(retry_number)
                        logger.warning(
                            "ingest_run_failed_retrying",
                            extra={
                                "run_id": run.run_id,
                                "attempt": attempts,
                                "max_retries": self._max_retries,
                                "retry_number": retry_number,
                                "delay_seconds": delay,
                                "error": str(exc),
                            },
                        )
                        if delay > 0:
                            await self._sleep(delay)
                        continue

                    updated = self._run_store.update_run(
                        run.run_id,
                        status="success",
                        end_time=self._now(),
                        error=None,
                        attempts=attempts,
                    )
                    if self._alert_manager is not None:
                        await self._alert_manager.record_run(updated)
                    return updated
            except asyncio.CancelledError:
                updated = self._run_store.update_run(
                    run.run_id,
                    status="failed",
                    end_time=self._now(),
                    error="Cancelled",
                    attempts=max(attempts, 1),
                )
                if self._alert_manager is not None:
                    await self._alert_manager.record_run(updated)
                raise
            except Exception as exc:  # noqa: BLE001
                updated = self._run_store.update_run(
                    run.run_id,
                    status="failed",
                    end_time=self._now(),
                    error=str(exc),
                    attempts=max(attempts, 1),
                )
                if self._alert_manager is not None:
                    await self._alert_manager.record_run(updated)
                return updated

    async def run_forever(self, *, stop_event: Optional[asyncio.Event] = None) -> None:
        stop_event = stop_event or asyncio.Event()
        while not stop_event.is_set():
            now = self._now()
            next_run = self.next_run_after(now)
            wait_seconds = max(0.0, (next_run - now).total_seconds())
            if wait_seconds > 0:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=wait_seconds)
                    continue
                except asyncio.TimeoutError:
                    pass
            await self.run_once()


def create_ingest_scheduler(
    ingest: Callable[[], Awaitable[None]],
    *,
    config: Optional[SchedulerConfig] = None,
    run_store: Optional[IngestRunStore] = None,
    alert_manager: Optional[AlertManager] = None,
) -> IngestScheduler:
    cfg = config
    if cfg is None:
        try:
            cfg = get_scheduler_config()
        except FileNotFoundError:
            cfg = SchedulerConfig()
        except ValueError:
            cfg = SchedulerConfig()
    backoff_cfg: SchedulerBackoffConfig = cfg.backoff
    backoff = ExponentialBackoff(
        base_seconds=backoff_cfg.base_seconds,
        factor=backoff_cfg.factor,
        max_seconds=backoff_cfg.max_seconds,
    )
    return IngestScheduler(
        cron=cfg.cron,
        ingest=ingest,
        run_store=run_store,
        alert_manager=alert_manager,
        max_retries=cfg.max_retries,
        backoff=backoff,
    )
