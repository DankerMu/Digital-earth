from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from config import get_settings
import db
from effect_presets_config import (
    EffectPresetItem,
    EffectType,
    get_effect_presets_payload,
)
from http_cache import if_none_match_matches
from models import EffectTriggerLog

router = APIRouter(prefix="/effects", tags=["effects"])
logger = logging.getLogger("api.error")


@router.get("/presets", response_model=list[EffectPresetItem])
def list_effect_presets(
    request: Request,
    response: Response,
    effect_type: Optional[EffectType] = Query(
        default=None, description="Filter by type"
    ),
) -> Response | list[EffectPresetItem]:
    try:
        payload = get_effect_presets_payload()
    except (FileNotFoundError, ValueError) as exc:
        logger.error("effect_presets_config_error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc

    headers = {
        "Cache-Control": "public, max-age=0, must-revalidate",
        "ETag": payload.etag,
    }

    if if_none_match_matches(request.headers.get("if-none-match"), payload.etag):
        return Response(status_code=304, headers=headers)

    presets = payload.presets
    if effect_type is not None:
        presets = tuple(
            preset for preset in presets if preset.effect_type == effect_type
        )

    response.headers.update(headers)
    return list(presets)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _should_sample(
    *,
    sample_rate: float,
    client_id: str | None,
    effect_type: str,
    triggered_at: datetime,
) -> bool:
    if sample_rate <= 0.0:
        return False
    if sample_rate >= 1.0:
        return True

    sample_key = f"{client_id or '-'}:{effect_type}:{triggered_at.isoformat()}"
    digest = hashlib.sha256(sample_key.encode("utf-8")).digest()
    sample_value = int.from_bytes(digest[:8], "big") / 2**64
    return sample_value < sample_rate


class EffectTriggerEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    effect_type: EffectType
    timestamp: datetime | None = Field(
        default=None, description="Client-side timestamp for the trigger event."
    )
    client_id: str | None = Field(default=None, max_length=128)
    client: str | None = Field(default=None, max_length=64)
    fps: float | None = Field(default=None, ge=0, le=1000)

    @field_validator("timestamp")
    @classmethod
    def _normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _normalize_utc(value)

    @field_validator("client_id", "client", mode="before")
    @classmethod
    def _coerce_optional_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            if stripped == "":
                return None
            return stripped
        return value


class EffectTriggerLogsIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[EffectTriggerEvent] = Field(min_length=1, max_length=1000)


@router.post(
    "/trigger-logs",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def ingest_effect_trigger_logs(payload: EffectTriggerLogsIngestRequest) -> Response:
    settings = get_settings()
    config = settings.api.effect_trigger_logging
    if not config.enabled:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    if len(payload.events) > config.max_events_per_request:
        raise HTTPException(status_code=413, detail="Too many events in request")

    received_at = _utc_now()
    sample_rate = float(config.sample_rate)

    records: list[EffectTriggerLog] = []
    for event in payload.events:
        triggered_at = event.timestamp or received_at
        effect_type = event.effect_type.value
        if not _should_sample(
            sample_rate=sample_rate,
            client_id=event.client_id,
            effect_type=effect_type,
            triggered_at=triggered_at,
        ):
            continue

        records.append(
            EffectTriggerLog(
                effect_type=effect_type,
                triggered_at=triggered_at,
                received_at=received_at,
                client_id=event.client_id,
                client=event.client,
                fps=event.fps,
            )
        )

    if not records:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        with Session(db.get_engine()) as session:
            session.add_all(records)
            session.commit()
    except SQLAlchemyError as exc:
        logger.error("effect_trigger_logs_db_error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class EffectTriggerLogItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    effect_type: EffectType
    triggered_at: datetime
    received_at: datetime
    client_id: str | None = None
    client: str | None = None
    fps: float | None = None


class EffectTriggerLogsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int
    page_size: int
    total: int
    items: list[EffectTriggerLogItem] = Field(default_factory=list)


@router.get("/trigger-logs", response_model=EffectTriggerLogsResponse)
def list_effect_trigger_logs(
    effect_type: Optional[EffectType] = Query(default=None),
    client_id: str | None = Query(default=None, max_length=128),
    page: int = Query(default=1, ge=1, le=1000),
    page_size: int = Query(default=50, ge=1, le=200),
) -> EffectTriggerLogsResponse:
    offset = (page - 1) * page_size

    stmt = select(EffectTriggerLog).order_by(
        desc(EffectTriggerLog.received_at), desc(EffectTriggerLog.id)
    )
    count_stmt = select(func.count()).select_from(EffectTriggerLog)

    if effect_type is not None:
        stmt = stmt.where(EffectTriggerLog.effect_type == effect_type.value)
        count_stmt = count_stmt.where(EffectTriggerLog.effect_type == effect_type.value)

    if client_id is not None:
        normalized_client_id = client_id.strip()
        if normalized_client_id == "":
            raise HTTPException(status_code=400, detail="client_id must not be empty")
        stmt = stmt.where(EffectTriggerLog.client_id == normalized_client_id)
        count_stmt = count_stmt.where(
            EffectTriggerLog.client_id == normalized_client_id
        )

    stmt = stmt.limit(page_size).offset(offset)

    try:
        with Session(db.get_engine()) as session:
            total = int(session.execute(count_stmt).scalar_one())
            logs = session.execute(stmt).scalars().all()
    except SQLAlchemyError as exc:
        logger.error("effect_trigger_logs_db_error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc

    items = [
        EffectTriggerLogItem(
            id=log.id,
            effect_type=EffectType(log.effect_type),
            triggered_at=_normalize_utc(log.triggered_at),
            received_at=_normalize_utc(log.received_at),
            client_id=log.client_id,
            client=log.client,
            fps=log.fps,
        )
        for log in logs
    ]

    return EffectTriggerLogsResponse(
        page=page,
        page_size=page_size,
        total=total,
        items=items,
    )
