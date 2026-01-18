from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import db
from data_source import DataNotFoundError, DataSourceError
from http_cache import if_none_match_matches
from local_data_service import get_data_source
from models import EcmwfRun

logger = logging.getLogger("api.error")

router = APIRouter(prefix="/catalog", tags=["catalog"])

SHORT_CACHE_CONTROL_HEADER = "public, max-age=60"
ECMWF_RUNS_CACHE_TTL_SECONDS = 60


class CldasTimesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    times: list[str] = Field(default_factory=list)


def _handle_data_source_error(exc: Exception) -> HTTPException:
    if isinstance(exc, DataNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, DataSourceError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="Internal Server Error")


def _time_key_from_index_item(item: Any) -> Optional[str]:
    meta: Any = getattr(item, "meta", None)
    if isinstance(meta, dict):
        ts = meta.get("timestamp")
        if isinstance(ts, str):
            ts = ts.strip()
            if len(ts) == 10 and ts.isdigit():
                return f"{ts[:8]}T{ts[8:]}0000Z"

    time_iso = getattr(item, "time", None)
    if not isinstance(time_iso, str):
        return None
    normalized = time_iso.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _time_key_from_datetime(value: datetime) -> str:
    parsed = value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


EcmwfRunStatus = Literal["complete", "partial"]


class EcmwfRunItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_time: str
    status: EcmwfRunStatus


class EcmwfRunsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runs: list[EcmwfRunItemResponse] = Field(default_factory=list)


@dataclass
class _EcmwfRunsCacheEntry:
    expires_at: float
    etag: str
    body: bytes


_ECMWF_RUNS_CACHE: dict[str, _EcmwfRunsCacheEntry] = {}


def reset_ecmwf_runs_cache_for_tests() -> None:
    _ECMWF_RUNS_CACHE.clear()


def _ecmwf_runs_cache_key(*, limit: int, offset: int) -> str:
    return f"limit={limit}&offset={offset}"


def _get_ecmwf_runs_cached(*, limit: int, offset: int) -> _EcmwfRunsCacheEntry | None:
    key = _ecmwf_runs_cache_key(limit=limit, offset=offset)
    entry = _ECMWF_RUNS_CACHE.get(key)
    if entry is None:
        return None

    if time.monotonic() >= entry.expires_at:
        _ECMWF_RUNS_CACHE.pop(key, None)
        return None

    return entry


def _normalize_ecmwf_run_status(raw: object) -> EcmwfRunStatus:
    value = (str(raw) if raw is not None else "").strip().lower()
    if value == "complete":
        return "complete"
    return "partial"


def _query_ecmwf_runs(*, limit: int, offset: int) -> list[EcmwfRunItemResponse]:
    stmt = (
        select(EcmwfRun.run_time, EcmwfRun.status)
        .order_by(desc(EcmwfRun.run_time))
        .limit(limit)
        .offset(offset)
    )

    try:
        with Session(db.get_engine()) as session:
            rows = session.execute(stmt).all()
    except SQLAlchemyError as exc:
        logger.error("ecmwf_runs_db_error", extra={"error": str(exc)})
        raise HTTPException(
            status_code=503, detail="Catalog database unavailable"
        ) from exc

    runs: list[EcmwfRunItemResponse] = []
    for run_time, status in rows:
        if not isinstance(run_time, datetime):
            continue
        runs.append(
            EcmwfRunItemResponse(
                run_time=_time_key_from_datetime(run_time),
                status=_normalize_ecmwf_run_status(status),
            )
        )

    return runs


@router.get("/cldas/times", response_model=CldasTimesResponse)
def get_cldas_times(
    request: Request,
    response: Response,
    var: Optional[str] = Query(default=None, description="Filter by CLDAS variable"),
) -> Response | CldasTimesResponse:
    ds = get_data_source()
    var_filter = (var or "").strip().upper() or None

    try:
        index = ds.list_files(kinds={"cldas"})
    except Exception as exc:  # noqa: BLE001
        logger.error("cldas_times_error", extra={"error": str(exc)})
        raise _handle_data_source_error(exc) from exc

    times: set[str] = set()
    for item in index.items:
        if var_filter and getattr(item, "variable", None) != var_filter:
            continue
        key = _time_key_from_index_item(item)
        if key:
            times.add(key)

    sorted_times = sorted(times)
    etag_payload = "\n".join([var_filter or "", *sorted_times]).encode("utf-8")
    etag = f'"sha256-{hashlib.sha256(etag_payload).hexdigest()}"'

    headers = {"Cache-Control": SHORT_CACHE_CONTROL_HEADER, "ETag": etag}
    if if_none_match_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)

    response.headers.update(headers)
    return CldasTimesResponse(times=sorted_times)


@router.get("/ecmwf/runs", response_model=EcmwfRunsResponse)
def get_ecmwf_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    latest: int | None = Query(
        default=None,
        ge=1,
        le=500,
        description="Return the latest N runs (alias for limit with offset=0)",
    ),
) -> Response:
    resolved_limit = limit
    resolved_offset = offset
    if latest is not None:
        if offset != 0:
            raise HTTPException(
                status_code=400, detail="offset must be 0 when using latest"
            )
        resolved_limit = latest
        resolved_offset = 0

    cached = _get_ecmwf_runs_cached(limit=resolved_limit, offset=resolved_offset)
    if cached is not None:
        headers = {"Cache-Control": SHORT_CACHE_CONTROL_HEADER, "ETag": cached.etag}
        if if_none_match_matches(request.headers.get("if-none-match"), cached.etag):
            return Response(status_code=304, headers=headers)
        return Response(
            content=cached.body, media_type="application/json", headers=headers
        )

    runs = _query_ecmwf_runs(limit=resolved_limit, offset=resolved_offset)
    body = EcmwfRunsResponse(runs=runs).model_dump_json().encode("utf-8")
    etag = f'"sha256-{hashlib.sha256(body).hexdigest()}"'
    headers = {"Cache-Control": SHORT_CACHE_CONTROL_HEADER, "ETag": etag}

    cache_key = _ecmwf_runs_cache_key(limit=resolved_limit, offset=resolved_offset)
    _ECMWF_RUNS_CACHE[cache_key] = _EcmwfRunsCacheEntry(
        expires_at=time.monotonic() + ECMWF_RUNS_CACHE_TTL_SECONDS,
        etag=etag,
        body=body,
    )

    if if_none_match_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)

    return Response(content=body, media_type="application/json", headers=headers)
