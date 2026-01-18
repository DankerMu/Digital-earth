from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _utc_now_iso(now: Optional[datetime] = None) -> str:
    ts = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    if ts.endswith("+00:00"):
        ts = ts[:-6] + "Z"
    return ts


@dataclass(frozen=True)
class AuditEvent:
    event: str
    run_id: str
    timestamp: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            **self.payload,
        }


class AuditLogger:
    def __init__(self, *, log_path: str | Path) -> None:
        self._path = Path(log_path)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def new_run_id(self) -> str:
        return uuid.uuid4().hex

    def record(
        self,
        *,
        event: str,
        run_id: str,
        payload: Optional[dict[str, Any]] = None,
        now: Optional[datetime] = None,
    ) -> AuditEvent:
        data = dict(payload or {})
        audit_event = AuditEvent(
            event=event,
            run_id=run_id,
            timestamp=_utc_now_iso(now),
            payload=data,
        )

        self._path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(audit_event.to_dict(), ensure_ascii=False) + "\n"

        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(encoded)

        logger.info(event, extra={"audit": audit_event.to_dict()})
        return audit_event
