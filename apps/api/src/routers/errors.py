from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger("api.error")

router = APIRouter(tags=["errors"])

_MAX_LOG_MESSAGE_LENGTH = 200
_EMAIL_RE = re.compile(r"(?i)\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")


def _sanitize_log_message(value: str) -> str:
    normalized = " ".join((value or "").split())
    normalized = _EMAIL_RE.sub("[redacted-email]", normalized)
    if len(normalized) > _MAX_LOG_MESSAGE_LENGTH:
        return normalized[: _MAX_LOG_MESSAGE_LENGTH - 3] + "..."
    return normalized


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
    error_code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=1000)
    stack: Optional[str] = Field(default=None, max_length=5000)
    browser_info: Optional[dict[str, Any]] = None
    app_state: Optional[dict[str, Any]] = None
    version: str = Field(min_length=1, max_length=128)
    timestamp: datetime = Field(default_factory=_utc_now)

    @field_validator("error_code")
    @classmethod
    def _validate_error_code(cls, value: str) -> str:
        if not value.isascii() or not value.isalnum():
            raise ValueError("error_code must be alphanumeric")
        return value

    @field_validator("timestamp")
    @classmethod
    def _normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


@router.post(
    "/errors",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def report_frontend_error(report: ErrorReport) -> Response:
    logger.error(
        "frontend.error_reported",
        extra={
            "error_code": report.error_code,
            "sanitized_message": _sanitize_log_message(report.message),
            "reported_at": _format_timestamp(report.timestamp),
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
