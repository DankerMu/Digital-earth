from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from scheduler.config import SchedulerRunsConfig, get_scheduler_config

IngestRunStatus = Literal["running", "success", "failed"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IngestRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: IngestRunStatus
    start_time: datetime
    end_time: Optional[datetime] = None
    error: Optional[str] = None
    attempts: int = Field(default=1, ge=1)


class IngestRunStore:
    def __init__(
        self,
        *,
        storage_path: Optional[Union[str, Path]] = None,
        max_entries: int = 200,
    ) -> None:
        self._storage_path = Path(storage_path) if storage_path is not None else None
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._runs: list[IngestRun] = []
        self._loaded = False

    @property
    def storage_path(self) -> Optional[Path]:
        return self._storage_path

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self._storage_path is None:
            return
        path = self._storage_path
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        if not isinstance(payload, list):
            return
        parsed: list[IngestRun] = []
        for item in payload:
            try:
                parsed.append(IngestRun.model_validate(item))
            except ValidationError:
                continue
        self._runs = parsed[-self._max_entries :]

    def _persist(self) -> None:
        if self._storage_path is None:
            return
        path = self._storage_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps([run.model_dump(mode="json") for run in self._runs]) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)

    def list_runs(self, *, limit: int = 50) -> list[IngestRun]:
        if limit <= 0:
            return []
        with self._lock:
            self._ensure_loaded()
            return list(reversed(self._runs[-limit:]))

    def create_run(self, *, start_time: Optional[datetime] = None) -> IngestRun:
        run = IngestRun(
            run_id=uuid.uuid4().hex,
            status="running",
            start_time=start_time or _utc_now(),
            end_time=None,
            error=None,
            attempts=1,
        )
        with self._lock:
            self._ensure_loaded()
            self._runs.append(run)
            self._runs = self._runs[-self._max_entries :]
            self._persist()
        return run

    def update_run(
        self,
        run_id: str,
        *,
        status: Optional[IngestRunStatus] = None,
        end_time: Optional[datetime] = None,
        error: Optional[str] = None,
        attempts: Optional[int] = None,
    ) -> IngestRun:
        with self._lock:
            self._ensure_loaded()
            for idx, run in enumerate(self._runs):
                if run.run_id != run_id:
                    continue
                updated = run.model_copy(
                    update={
                        **({} if status is None else {"status": status}),
                        **({} if end_time is None else {"end_time": end_time}),
                        **({"error": error} if error is not None else {}),
                        **({} if attempts is None else {"attempts": attempts}),
                    }
                )
                self._runs[idx] = updated
                self._persist()
                return updated
        raise KeyError(f"run_id not found: {run_id}")


def _runs_config_from_settings() -> SchedulerRunsConfig:
    try:
        config = get_scheduler_config()
    except FileNotFoundError:
        return SchedulerRunsConfig()
    except ValueError:
        return SchedulerRunsConfig()
    return config.runs


_STORE: Optional[IngestRunStore] = None
_STORE_LOCK = threading.Lock()


def get_ingest_run_store() -> IngestRunStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is not None:
            return _STORE
        runs_config = _runs_config_from_settings()
        _STORE = IngestRunStore(
            storage_path=runs_config.storage_path,
            max_entries=runs_config.max_entries,
        )
        return _STORE


def reset_ingest_run_store_for_tests() -> None:
    global _STORE
    with _STORE_LOCK:
        _STORE = None
