from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Final, Mapping, MutableMapping, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExponentialBackoff:
    base_seconds: float = 1.0
    factor: float = 2.0
    max_seconds: float = 60.0

    def delay_seconds(self, retry_number: int) -> float:
        if retry_number <= 0:
            return 0.0
        delay = self.base_seconds * (self.factor ** (retry_number - 1))
        return float(min(delay, self.max_seconds))


@dataclass(frozen=True)
class TileJob:
    """A single tile job shard.

    Sharding dimensions are intentionally explicit: variable/level/time.
    """

    run_id: str
    variable: str
    level: str
    time: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def key(self) -> str:
        return f"{self.variable}/{self.level}/{self.time}"


TileJobStatus = Final[set[str]]
TileJobStatus = {"success", "failed"}


@dataclass(frozen=True)
class TileJobResult:
    job: TileJob
    status: str
    attempts: int
    error: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


TileJobHandler = Callable[[TileJob], Mapping[str, Any] | None]


class TileWorker:
    def __init__(
        self,
        handler: TileJobHandler,
        *,
        max_retries: int = 2,
        backoff: Optional[ExponentialBackoff] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")

        self._handler = handler
        self._max_retries = max_retries
        self._backoff = backoff or ExponentialBackoff()
        self._sleep = sleep

    @property
    def max_retries(self) -> int:
        return self._max_retries

    def process(self, job: TileJob) -> TileJobResult:
        attempts = 0
        last_error: Optional[str] = None

        while True:
            attempts += 1
            try:
                logger.info(
                    "tile_job_started",
                    extra={
                        "run_id": job.run_id,
                        "job_key": job.key(),
                        "variable": job.variable,
                        "level": job.level,
                        "time": job.time,
                        "attempt": attempts,
                    },
                )
                metadata = self._handler(job) or {}
                return TileJobResult(
                    job=job,
                    status="success",
                    attempts=attempts,
                    error=None,
                    metadata=dict(metadata),
                )
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                retries_used = attempts - 1
                if retries_used >= self._max_retries:
                    logger.error(
                        "tile_job_failed",
                        extra={
                            "run_id": job.run_id,
                            "job_key": job.key(),
                            "variable": job.variable,
                            "level": job.level,
                            "time": job.time,
                            "attempt": attempts,
                            "max_retries": self._max_retries,
                            "error": last_error,
                        },
                    )
                    return TileJobResult(
                        job=job,
                        status="failed",
                        attempts=attempts,
                        error=last_error,
                        metadata={},
                    )

                retry_number = retries_used + 1
                delay = self._backoff.delay_seconds(retry_number)
                logger.warning(
                    "tile_job_failed_retrying",
                    extra={
                        "run_id": job.run_id,
                        "job_key": job.key(),
                        "variable": job.variable,
                        "level": job.level,
                        "time": job.time,
                        "attempt": attempts,
                        "max_retries": self._max_retries,
                        "retry_number": retry_number,
                        "delay_seconds": delay,
                        "error": last_error,
                    },
                )
                if delay > 0:
                    self._sleep(delay)


def build_tile_job(
    *,
    run_id: str,
    variable: str,
    level: str,
    time: str,
    payload: Optional[Mapping[str, Any]] = None,
) -> TileJob:
    run_id_norm = (run_id or "").strip()
    if run_id_norm == "":
        raise ValueError("run_id must not be empty")

    variable_norm = (variable or "").strip()
    if variable_norm == "":
        raise ValueError("variable must not be empty")

    level_norm = (level or "").strip()
    if level_norm == "":
        raise ValueError("level must not be empty")

    time_norm = (time or "").strip()
    if time_norm == "":
        raise ValueError("time must not be empty")

    payload_map: MutableMapping[str, Any] = dict(payload or {})
    return TileJob(
        run_id=run_id_norm,
        variable=variable_norm,
        level=level_norm,
        time=time_norm,
        payload=payload_map,
    )

