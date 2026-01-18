from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from croniter import croniter

from retention.cleanup import RetentionCleanupResult

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


class RetentionCleanupScheduler:
    def __init__(
        self,
        *,
        cron: str,
        cleanup: Callable[[], RetentionCleanupResult],
        max_retries: int = 0,
        backoff: Optional[ExponentialBackoff] = None,
        now: Callable[[], datetime] = _utc_now,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._cron = cron.strip()
        self._cleanup = cleanup
        self._max_retries = max_retries
        self._backoff = backoff or ExponentialBackoff()
        self._now = now
        self._sleep = sleep

        if self._cron == "":
            raise ValueError("cron must not be empty")
        if self._max_retries < 0:
            raise ValueError("max_retries must be >= 0")

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

    async def run_once(self) -> RetentionCleanupResult:
        attempts = 0
        while True:
            attempts += 1
            try:
                return self._cleanup()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                retries_used = attempts - 1
                if retries_used >= self._max_retries:
                    raise
                retry_number = retries_used + 1
                delay = self._backoff.delay_seconds(retry_number)
                logger.warning(
                    "retention_cleanup_failed_retrying",
                    extra={
                        "attempt": attempts,
                        "max_retries": self._max_retries,
                        "retry_number": retry_number,
                        "delay_seconds": delay,
                        "error": str(exc),
                    },
                )
                if delay > 0:
                    await self._sleep(delay)

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

