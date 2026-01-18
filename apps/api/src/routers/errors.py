from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger("api.error")

router = APIRouter(tags=["errors"])


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    text = value.isoformat()
    if text.endswith("+00:00"):
        return text[:-6] + "Z"
    return text


class ErrorReport(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    trace_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1)
    stack: Optional[str] = None
    browser_info: Optional[dict[str, Any]] = None
    app_state: Optional[dict[str, Any]] = None
    version: str = Field(min_length=1, max_length=128)
    timestamp: datetime = Field(default_factory=_utc_now)

    @field_validator("timestamp")
    @classmethod
    def _normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


@router.post("/errors", status_code=status.HTTP_204_NO_CONTENT)
def report_frontend_error(report: ErrorReport) -> None:
    logger.error(
        "frontend.error_reported",
        extra={
            "frontend_trace_id": report.trace_id,
            "frontend_version": report.version,
            "error_message": report.message,
            "error_stack": report.stack,
            "browser_info": report.browser_info,
            "app_state": report.app_state,
            "reported_at": _format_timestamp(report.timestamp),
        },
    )
