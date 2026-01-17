from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Mapping, Optional

import httpx

from scheduler.config import SchedulerAlertConfig, SchedulerConfig, get_scheduler_config
from scheduler.runs import IngestRun

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def _default_send_webhook(
    url: str, payload: Mapping[str, Any], headers: Mapping[str, str]
) -> None:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.post(url, json=dict(payload), headers=dict(headers))
        resp.raise_for_status()


@dataclass(frozen=True)
class AlertState:
    consecutive_failures: int
    alerted_for_streak: bool


class AlertManager:
    def __init__(
        self,
        *,
        consecutive_failures_threshold: int,
        webhook_url: Optional[str] = None,
        webhook_headers: Optional[Mapping[str, str]] = None,
        send_webhook: Optional[
            Callable[[str, Mapping[str, Any], Mapping[str, str]], Awaitable[None]]
        ] = None,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        if consecutive_failures_threshold <= 0:
            raise ValueError("consecutive_failures_threshold must be > 0")

        self._threshold = consecutive_failures_threshold
        self._webhook_url = (webhook_url or "").strip() or None
        self._webhook_headers = dict(webhook_headers or {})
        self._send_webhook = send_webhook or _default_send_webhook
        self._now = now

        self._lock: Optional[asyncio.Lock] = None
        self._lock_init = threading.Lock()
        self._consecutive_failures = 0
        self._alerted_for_streak = False

    @property
    def state(self) -> AlertState:
        return AlertState(
            consecutive_failures=self._consecutive_failures,
            alerted_for_streak=self._alerted_for_streak,
        )

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

    async def record_run(self, run: IngestRun) -> None:
        if run.status not in {"success", "failed"}:
            return

        async with self._get_lock():
            if run.status == "success":
                self._consecutive_failures = 0
                self._alerted_for_streak = False
                return

            self._consecutive_failures += 1
            should_alert = (
                self._consecutive_failures >= self._threshold
                and not self._alerted_for_streak
            )
            if not should_alert:
                return
            self._alerted_for_streak = True

        if self._webhook_url is None:
            logger.warning(
                "ingest_alert_triggered_no_webhook",
                extra={
                    "threshold": self._threshold,
                    "consecutive_failures": self._consecutive_failures,
                    "run_id": run.run_id,
                },
            )
            return

        payload: dict[str, Any] = {
            "event": "ingest.consecutive_failures",
            "timestamp": self._now().isoformat(),
            "threshold": self._threshold,
            "consecutive_failures": self._consecutive_failures,
            "latest_run": run.model_dump(mode="json"),
        }

        try:
            await self._send_webhook(self._webhook_url, payload, self._webhook_headers)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ingest_alert_webhook_failed",
                extra={
                    "url": self._webhook_url,
                    "threshold": self._threshold,
                    "consecutive_failures": self._consecutive_failures,
                    "run_id": run.run_id,
                    "error": str(exc),
                },
            )


def create_alert_manager(config: Optional[SchedulerConfig] = None) -> AlertManager:
    cfg = config
    if cfg is None:
        try:
            cfg = get_scheduler_config()
        except FileNotFoundError:
            cfg = SchedulerConfig()
        except ValueError:
            cfg = SchedulerConfig()

    alert_cfg: SchedulerAlertConfig = cfg.alert
    return AlertManager(
        consecutive_failures_threshold=alert_cfg.consecutive_failures,
        webhook_url=alert_cfg.webhook_url,
        webhook_headers=alert_cfg.webhook_headers,
    )
