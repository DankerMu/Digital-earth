from __future__ import annotations

import hashlib
import logging
from asyncio import to_thread
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from catalog_cache import RedisLike, get_or_compute_cached_bytes
import db
from data_source import DataNotFoundError, DataSourceError
from http_cache import if_none_match_matches
from local_data_service import get_data_source
from models import EcmwfRun, EcmwfTime

logger = logging.getLogger("api.error")

router = APIRouter(prefix="/catalog", tags=["catalog"])

SHORT_CACHE_CONTROL_HEADER = "public, max-age=60"
CACHE_FRESH_TTL_SECONDS = 60
CACHE_STALE_TTL_SECONDS = 60 * 60
CACHE_LOCK_TTL_MS = 30_000
CACHE_WAIT_TIMEOUT_MS = 200
CACHE_COOLDOWN_TTL_SECONDS: tuple[int, int] = (5, 30)
HOT_ECMWF_RUNS_LIMIT = 20


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


def _parse_time(value: str, *, label: str) -> datetime:
    raw = (value or "").strip()
    if raw == "":
        raise ValueError(f"{label} must not be empty")

    candidate = raw
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        try:
            parsed = datetime.strptime(raw, "%Y%m%dT%H%M%SZ")
        except ValueError as exc:
            raise ValueError(
                f"{label} must be an ISO8601 timestamp or YYYYMMDDTHHMMSSZ"
            ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@router.get("/cldas/times", response_model=CldasTimesResponse)
async def get_cldas_times(
    request: Request,
    var: Optional[str] = Query(default=None, description="Filter by CLDAS variable"),
) -> Response:
    ds = get_data_source()
    var_filter = (var or "").strip().upper() or None

    redis: RedisLike | None = getattr(request.app.state, "redis_client", None)

    async def _compute() -> bytes:
        try:
            index = await to_thread(ds.list_files, kinds={"cldas"})
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
        return CldasTimesResponse(times=sorted_times).model_dump_json().encode("utf-8")

    if redis is None:
        body = await _compute()
    else:
        identity = var_filter or "all"
        fresh_key = f"catalog:cldas:times:fresh:{identity}"
        stale_key = f"catalog:cldas:times:stale:{identity}"
        lock_key = f"catalog:cldas:times:lock:{identity}"
        try:
            result = await get_or_compute_cached_bytes(
                redis,
                fresh_key=fresh_key,
                stale_key=stale_key,
                lock_key=lock_key,
                fresh_ttl_seconds=CACHE_FRESH_TTL_SECONDS,
                stale_ttl_seconds=CACHE_STALE_TTL_SECONDS,
                lock_ttl_ms=CACHE_LOCK_TTL_MS,
                wait_timeout_ms=CACHE_WAIT_TIMEOUT_MS,
                compute=_compute,
                cooldown_ttl_seconds=CACHE_COOLDOWN_TTL_SECONDS,
            )
            body = result.body
        except TimeoutError as exc:
            raise HTTPException(
                status_code=503, detail="Catalog cache warming timed out"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            logger.warning("catalog_cache_unavailable", extra={"error": str(exc)})
            body = await _compute()

    etag = f'"sha256-{hashlib.sha256(body).hexdigest()}"'
    headers = {"Cache-Control": SHORT_CACHE_CONTROL_HEADER, "ETag": etag}
    if if_none_match_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)

    return Response(content=body, media_type="application/json", headers=headers)


@router.get("/ecmwf/runs", response_model=EcmwfRunsResponse)
async def get_ecmwf_runs(
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

    redis: RedisLike | None = getattr(request.app.state, "redis_client", None)

    async def _compute() -> bytes:
        query_limit = resolved_limit
        if resolved_offset == 0:
            query_limit = max(resolved_limit, HOT_ECMWF_RUNS_LIMIT)

        runs = await to_thread(
            _query_ecmwf_runs, limit=query_limit, offset=resolved_offset
        )

        if resolved_offset == 0:
            hot_runs = runs[:HOT_ECMWF_RUNS_LIMIT]
            hot_body = (
                EcmwfRunsResponse(runs=hot_runs).model_dump_json().encode("utf-8")
            )
            if redis is not None:
                hot_fresh = (
                    f"catalog:ecmwf:runs:fresh:limit={HOT_ECMWF_RUNS_LIMIT}&offset=0"
                )
                hot_stale = (
                    f"catalog:ecmwf:runs:stale:limit={HOT_ECMWF_RUNS_LIMIT}&offset=0"
                )
                try:
                    await redis.set(hot_fresh, hot_body, ex=CACHE_FRESH_TTL_SECONDS)
                    await redis.set(hot_stale, hot_body, ex=CACHE_STALE_TTL_SECONDS)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "catalog_cache_prewarm_failed", extra={"error": str(exc)}
                    )

        payload_runs = runs
        if resolved_offset == 0 and query_limit != resolved_limit:
            payload_runs = runs[:resolved_limit]

        return EcmwfRunsResponse(runs=payload_runs).model_dump_json().encode("utf-8")

    if redis is None:
        body = await _compute()
    else:
        fresh_key = (
            f"catalog:ecmwf:runs:fresh:limit={resolved_limit}&offset={resolved_offset}"
        )
        stale_key = (
            f"catalog:ecmwf:runs:stale:limit={resolved_limit}&offset={resolved_offset}"
        )
        lock_key = (
            f"catalog:ecmwf:runs:lock:limit={resolved_limit}&offset={resolved_offset}"
        )
        try:
            result = await get_or_compute_cached_bytes(
                redis,
                fresh_key=fresh_key,
                stale_key=stale_key,
                lock_key=lock_key,
                fresh_ttl_seconds=CACHE_FRESH_TTL_SECONDS,
                stale_ttl_seconds=CACHE_STALE_TTL_SECONDS,
                lock_ttl_ms=CACHE_LOCK_TTL_MS,
                wait_timeout_ms=CACHE_WAIT_TIMEOUT_MS,
                compute=_compute,
                cooldown_ttl_seconds=CACHE_COOLDOWN_TTL_SECONDS,
            )
            body = result.body
        except TimeoutError as exc:
            raise HTTPException(
                status_code=503, detail="Catalog cache warming timed out"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            logger.warning("catalog_cache_unavailable", extra={"error": str(exc)})
            body = await _compute()

    etag = f'"sha256-{hashlib.sha256(body).hexdigest()}"'
    headers = {"Cache-Control": SHORT_CACHE_CONTROL_HEADER, "ETag": etag}
    if if_none_match_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)

    return Response(content=body, media_type="application/json", headers=headers)


class EcmwfRunTimesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    times: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


def _expected_ecmwf_lead_hours_std() -> list[int]:
    early = range(0, 72 + 1, 3)
    late = range(72, 240 + 1, 6)
    return sorted(set(early).union(late))


def _expected_time_keys_for_run(*, run_time: datetime, policy: str) -> list[str]:
    if policy != "std":
        raise ValueError(f"Unsupported policy: {policy}")

    normalized = run_time
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    normalized = normalized.astimezone(timezone.utc)

    expected: list[str] = []
    for lead_hours in _expected_ecmwf_lead_hours_std():
        expected.append(
            _time_key_from_datetime(normalized + timedelta(hours=lead_hours))
        )
    return expected


def _query_ecmwf_run_times(*, run_time: datetime) -> tuple[datetime, list[datetime]]:
    stmt_run = select(EcmwfRun.id, EcmwfRun.run_time).where(
        EcmwfRun.run_time == run_time
    )
    try:
        with Session(db.get_engine()) as session:
            row = session.execute(stmt_run).first()
            if row is None or not isinstance(row[0], int):
                raise HTTPException(status_code=404, detail="Run not found")

            run_id = row[0]
            stored_run_time = row[1]
            if not isinstance(stored_run_time, datetime):
                stored_run_time = run_time

            stmt_times = (
                select(EcmwfTime.valid_time)
                .where(EcmwfTime.run_id == run_id)
                .order_by(EcmwfTime.valid_time)
            )
            rows = session.execute(stmt_times).all()
    except SQLAlchemyError as exc:
        logger.error("ecmwf_run_times_db_error", extra={"error": str(exc)})
        raise HTTPException(
            status_code=503, detail="Catalog database unavailable"
        ) from exc

    times: list[datetime] = []
    for (valid_time,) in rows:
        if isinstance(valid_time, datetime):
            times.append(valid_time)

    return stored_run_time, times


@router.get("/ecmwf/runs/{run}/times", response_model=EcmwfRunTimesResponse)
async def get_ecmwf_run_times(
    request: Request,
    run: str,
    policy: str = Query(default="std", description="Sampling policy (std)"),
) -> Response:
    try:
        parsed_run = _parse_time(run, label="run")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    normalized_policy = (policy or "").strip().lower() or "std"
    if normalized_policy != "std":
        raise HTTPException(
            status_code=400, detail=f"Unsupported policy: {normalized_policy}"
        )

    run_key = _time_key_from_datetime(parsed_run)

    redis: RedisLike | None = getattr(request.app.state, "redis_client", None)

    async def _compute() -> bytes:
        stored_run_time, valid_times = await to_thread(
            _query_ecmwf_run_times, run_time=parsed_run
        )

        expected_keys = _expected_time_keys_for_run(
            run_time=stored_run_time, policy=normalized_policy
        )
        available: set[str] = set()
        for dt in valid_times:
            available.add(_time_key_from_datetime(dt))

        sampled = [key for key in expected_keys if key in available]
        missing = [key for key in expected_keys if key not in available]

        return (
            EcmwfRunTimesResponse(times=sampled, missing=missing)
            .model_dump_json()
            .encode("utf-8")
        )

    if redis is None:
        body = await _compute()
    else:
        fresh_key = (
            f"catalog:ecmwf:run-times:fresh:run={run_key}&policy={normalized_policy}"
        )
        stale_key = (
            f"catalog:ecmwf:run-times:stale:run={run_key}&policy={normalized_policy}"
        )
        lock_key = (
            f"catalog:ecmwf:run-times:lock:run={run_key}&policy={normalized_policy}"
        )
        try:
            result = await get_or_compute_cached_bytes(
                redis,
                fresh_key=fresh_key,
                stale_key=stale_key,
                lock_key=lock_key,
                fresh_ttl_seconds=CACHE_FRESH_TTL_SECONDS,
                stale_ttl_seconds=CACHE_STALE_TTL_SECONDS,
                lock_ttl_ms=CACHE_LOCK_TTL_MS,
                wait_timeout_ms=CACHE_WAIT_TIMEOUT_MS,
                compute=_compute,
                cooldown_ttl_seconds=CACHE_COOLDOWN_TTL_SECONDS,
            )
            body = result.body
        except TimeoutError as exc:
            raise HTTPException(
                status_code=503, detail="Catalog cache warming timed out"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            logger.warning("catalog_cache_unavailable", extra={"error": str(exc)})
            body = await _compute()

    etag = f'"sha256-{hashlib.sha256(body).hexdigest()}"'
    headers = {"Cache-Control": SHORT_CACHE_CONTROL_HEADER, "ETag": etag}
    if if_none_match_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)

    return Response(content=body, media_type="application/json", headers=headers)


class EcmwfRunVarsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vars: list[str] = Field(default_factory=list)
    levels: list[str] = Field(default_factory=list)
    units: dict[str, str] = Field(default_factory=dict)
    legend_version: int


ECMWF_RUN_CATALOG_VARS = ["cloud", "precip", "wind", "temp"]
ECMWF_RUN_CATALOG_LEVELS = ["sfc", "850", "700", "500", "300"]
ECMWF_RUN_CATALOG_UNITS: dict[str, str] = {
    "cloud": "%",
    "precip": "mm",
    "wind": "m/s",
    "temp": "°C",
}
ECMWF_RUN_CATALOG_LEGEND_VERSION = 2


def _assert_ecmwf_run_exists(*, run_time: datetime) -> None:
    stmt = select(EcmwfRun.id).where(EcmwfRun.run_time == run_time).limit(1)

    try:
        with Session(db.get_engine()) as session:
            row = session.execute(stmt).first()
    except SQLAlchemyError as exc:
        logger.error("ecmwf_run_vars_db_error", extra={"error": str(exc)})
        raise HTTPException(
            status_code=503, detail="Catalog database unavailable"
        ) from exc

    if row is None or not isinstance(row[0], int):
        raise HTTPException(status_code=404, detail="Run not found")


@router.get("/ecmwf/runs/{run}/vars", response_model=EcmwfRunVarsResponse)
async def get_ecmwf_run_vars(
    request: Request,
    run: str,
) -> Response:
    try:
        parsed_run = _parse_time(run, label="run")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    run_key = _time_key_from_datetime(parsed_run)

    redis: RedisLike | None = getattr(request.app.state, "redis_client", None)

    async def _compute() -> bytes:
        await to_thread(_assert_ecmwf_run_exists, run_time=parsed_run)
        return (
            EcmwfRunVarsResponse(
                vars=ECMWF_RUN_CATALOG_VARS,
                levels=ECMWF_RUN_CATALOG_LEVELS,
                units=ECMWF_RUN_CATALOG_UNITS,
                legend_version=ECMWF_RUN_CATALOG_LEGEND_VERSION,
            )
            .model_dump_json()
            .encode("utf-8")
        )

    if redis is None:
        body = await _compute()
    else:
        fresh_key = f"catalog:ecmwf:run-vars:fresh:run={run_key}"
        stale_key = f"catalog:ecmwf:run-vars:stale:run={run_key}"
        lock_key = f"catalog:ecmwf:run-vars:lock:run={run_key}"
        try:
            result = await get_or_compute_cached_bytes(
                redis,
                fresh_key=fresh_key,
                stale_key=stale_key,
                lock_key=lock_key,
                fresh_ttl_seconds=CACHE_FRESH_TTL_SECONDS,
                stale_ttl_seconds=CACHE_STALE_TTL_SECONDS,
                lock_ttl_ms=CACHE_LOCK_TTL_MS,
                wait_timeout_ms=CACHE_WAIT_TIMEOUT_MS,
                compute=_compute,
                cooldown_ttl_seconds=CACHE_COOLDOWN_TTL_SECONDS,
            )
            body = result.body
        except TimeoutError as exc:
            raise HTTPException(
                status_code=503, detail="Catalog cache warming timed out"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            logger.warning("catalog_cache_unavailable", extra={"error": str(exc)})
            body = await _compute()

    etag = f'"sha256-{hashlib.sha256(body).hexdigest()}"'
    headers = {"Cache-Control": SHORT_CACHE_CONTROL_HEADER, "ETag": etag}
    if if_none_match_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)

    return Response(content=body, media_type="application/json", headers=headers)
