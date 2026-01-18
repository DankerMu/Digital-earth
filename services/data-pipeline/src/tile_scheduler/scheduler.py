from __future__ import annotations

import logging
import time
from concurrent.futures import Executor, Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from tile_scheduler.worker import TileJob, TileJobResult, TileWorker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TileSchedulerSummary:
    run_id: str
    total_jobs: int
    succeeded: int
    failed: int
    duration_s: float
    results: Sequence[TileJobResult]


class TileScheduler:
    def __init__(
        self,
        *,
        worker: TileWorker,
        max_workers: int = 4,
        progress_log_every: int = 1,
        executor: Optional[Executor] = None,
    ) -> None:
        if max_workers <= 0:
            raise ValueError("max_workers must be > 0")
        if progress_log_every <= 0:
            raise ValueError("progress_log_every must be > 0")

        self._worker = worker
        self._max_workers = int(max_workers)
        self._progress_log_every = int(progress_log_every)
        self._executor = executor

    @property
    def max_workers(self) -> int:
        return self._max_workers

    def run(self, *, run_id: str, jobs: Iterable[TileJob]) -> TileSchedulerSummary:
        jobs_list = list(jobs)
        total = len(jobs_list)
        if total == 0:
            return TileSchedulerSummary(
                run_id=run_id,
                total_jobs=0,
                succeeded=0,
                failed=0,
                duration_s=0.0,
                results=[],
            )

        t0 = time.perf_counter()
        logger.info(
            "tile_scheduler_started",
            extra={
                "run_id": run_id,
                "total_jobs": total,
                "max_workers": self._max_workers,
                "max_retries": self._worker.max_retries,
            },
        )

        succeeded = 0
        failed = 0
        completed = 0
        results: list[TileJobResult] = []

        def submit_all(executor: Executor) -> dict[Future[TileJobResult], TileJob]:
            return {executor.submit(self._worker.process, job): job for job in jobs_list}

        owns_executor = self._executor is None
        executor = self._executor or ThreadPoolExecutor(max_workers=self._max_workers)

        try:
            futures = submit_all(executor)
            for future in as_completed(futures):
                _ = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # pragma: no cover - defensive isolation
                    result = TileJobResult(
                        job=TileJob(
                            run_id=run_id,
                            variable="<unknown>",
                            level="<unknown>",
                            time="<unknown>",
                        ),
                        status="failed",
                        attempts=0,
                        error=str(exc),
                        metadata={},
                    )

                results.append(result)
                completed += 1
                if result.status == "success":
                    succeeded += 1
                else:
                    failed += 1

                should_log_progress = (
                    completed == total
                    or completed % self._progress_log_every == 0
                )
                if should_log_progress:
                    logger.info(
                        "tile_scheduler_progress",
                        extra={
                            "run_id": run_id,
                            "completed": completed,
                            "total_jobs": total,
                            "succeeded": succeeded,
                            "failed": failed,
                        },
                    )
        finally:
            if owns_executor:
                executor.shutdown(wait=True)

        duration_s = time.perf_counter() - t0
        logger.info(
            "tile_scheduler_finished",
            extra={
                "run_id": run_id,
                "total_jobs": total,
                "succeeded": succeeded,
                "failed": failed,
                "duration_s": duration_s,
            },
        )

        return TileSchedulerSummary(
            run_id=run_id,
            total_jobs=total,
            succeeded=succeeded,
            failed=failed,
            duration_s=duration_s,
            results=results,
        )

