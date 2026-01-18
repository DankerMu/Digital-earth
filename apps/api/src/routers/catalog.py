from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from catalog_cache import CacheRecord, StaleRedisCache
from data_source import DataNotFoundError, DataSourceError
from http_cache import if_none_match_matches
from local_data_service import get_data_source

logger = logging.getLogger("api.error")

router = APIRouter(prefix="/catalog", tags=["catalog"])

SHORT_CACHE_CONTROL_HEADER = "public, max-age=60"


class CldasTimesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    times: list[str] = Field(default_factory=list)


class EcmwfRunsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runs: list[str] = Field(default_factory=list)


class EcmwfTimesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run: str
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


def _time_key_from_any(value: str | None) -> Optional[str]:
    text = (value or "").strip()
    if not text:
        return None

    if len(text) == 10 and text.isdigit():
        return f"{text[:8]}T{text[8:]}0000Z"

    if len(text) == 16 and text[8] == "T" and text.endswith("Z"):
        candidate = text.replace("T", "").replace("Z", "")
        if candidate.isdigit():
            return text

    normalized = text
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _etag_from_parts(parts: list[str]) -> str:
    payload = "\n".join(parts).encode("utf-8")
    return f'"sha256-{hashlib.sha256(payload).hexdigest()}"'


def _catalog_cache(request: Request) -> StaleRedisCache | None:
    cache: object = getattr(request.app.state, "catalog_cache", None)
    if isinstance(cache, StaleRedisCache):
        return cache
    return None


def _cache_key_suffix(value: str | None, *, default: str) -> str:
    text = (value or "").strip()
    if not text:
        return default
    if text.isascii() and len(text) <= 64 and text.replace("_", "").isalnum():
        return text
    return f"sha256-{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


@router.get("/cldas/times", response_model=CldasTimesResponse)
async def get_cldas_times(
    request: Request,
    response: Response,
    var: Optional[str] = Query(default=None, description="Filter by CLDAS variable"),
) -> Response | CldasTimesResponse:
    var_filter = (var or "").strip().upper() or None
    cache = _catalog_cache(request)

    async def compute() -> CacheRecord:
        ds = get_data_source()
        try:
            index = await run_in_threadpool(ds.list_files, kinds={"cldas"})
        except Exception as exc:  # noqa: BLE001
            logger.error("cldas_times_error", extra={"error": str(exc)})
            raise

        times: set[str] = set()
        for item in index.items:
            if var_filter and getattr(item, "variable", None) != var_filter:
                continue
            key = _time_key_from_index_item(item)
            if key:
                times.add(key)

        sorted_times = sorted(times)
        etag = _etag_from_parts([var_filter or "", *sorted_times])
        return CacheRecord(etag=etag, payload={"times": sorted_times})

    cache_key = (
        f"cldas:times:{_cache_key_suffix(var_filter, default='all')}"
        if cache is not None
        else None
    )
    try:
        if cache is None or cache_key is None:
            record = await compute()
        else:
            record = (await cache.get_or_compute(cache_key, compute=compute)).record
    except Exception as exc:  # noqa: BLE001
        raise _handle_data_source_error(exc) from exc

    sorted_times = record.payload.get("times", [])
    if not isinstance(sorted_times, list):
        sorted_times = []

    headers = {"Cache-Control": SHORT_CACHE_CONTROL_HEADER, "ETag": record.etag}
    if if_none_match_matches(request.headers.get("if-none-match"), record.etag):
        return Response(status_code=304, headers=headers)

    response.headers.update(headers)
    return CldasTimesResponse(times=[str(item) for item in sorted_times])


@router.get("/ecmwf/runs", response_model=EcmwfRunsResponse)
async def get_ecmwf_runs(
    request: Request, response: Response
) -> Response | EcmwfRunsResponse:
    cache = _catalog_cache(request)

    async def compute() -> CacheRecord:
        ds = get_data_source()
        try:
            index = await run_in_threadpool(ds.list_files, kinds={"ecmwf"})
        except Exception as exc:  # noqa: BLE001
            logger.error("ecmwf_runs_error", extra={"error": str(exc)})
            raise

        runs: set[str] = set()
        times_by_run: dict[str, set[str]] = {}
        for item in index.items:
            meta: Any = getattr(item, "meta", None)
            if not isinstance(meta, dict):
                continue
            run_key = _time_key_from_any(meta.get("init_time"))
            if not run_key:
                continue
            runs.add(run_key)
            valid_key = _time_key_from_any(getattr(item, "time", None))
            if valid_key:
                times_by_run.setdefault(run_key, set()).add(valid_key)

        ordered_runs = sorted(runs, reverse=True)
        etag = _etag_from_parts(ordered_runs)
        record = CacheRecord(etag=etag, payload={"runs": ordered_runs})

        if cache is not None and ordered_runs:
            hot_run = ordered_runs[0]
            hot_times = sorted(times_by_run.get(hot_run, set()))
            hot_record = CacheRecord(
                etag=_etag_from_parts([hot_run, *hot_times]),
                payload={"run": hot_run, "times": hot_times},
            )
            await cache.set_record(f"ecmwf:times:{hot_run}", hot_record)

        return record

    try:
        if cache is None:
            record = await compute()
        else:
            record = (await cache.get_or_compute("ecmwf:runs", compute=compute)).record
    except Exception as exc:  # noqa: BLE001
        raise _handle_data_source_error(exc) from exc

    runs = record.payload.get("runs", [])
    if not isinstance(runs, list):
        runs = []

    headers = {"Cache-Control": SHORT_CACHE_CONTROL_HEADER, "ETag": record.etag}
    if if_none_match_matches(request.headers.get("if-none-match"), record.etag):
        return Response(status_code=304, headers=headers)

    response.headers.update(headers)
    return EcmwfRunsResponse(runs=[str(item) for item in runs])


@router.get("/ecmwf/{run}/times", response_model=EcmwfTimesResponse)
async def get_ecmwf_times(
    request: Request, response: Response, run: str
) -> Response | EcmwfTimesResponse:
    cache = _catalog_cache(request)
    run_key = _time_key_from_any(run)
    if run_key is None:
        raise HTTPException(status_code=400, detail="Invalid run")

    async def compute() -> CacheRecord:
        ds = get_data_source()
        try:
            index = await run_in_threadpool(ds.list_files, kinds={"ecmwf"})
        except Exception as exc:  # noqa: BLE001
            logger.error("ecmwf_times_error", extra={"error": str(exc)})
            raise

        times: set[str] = set()
        for item in index.items:
            meta: Any = getattr(item, "meta", None)
            if not isinstance(meta, dict):
                continue
            init_key = _time_key_from_any(meta.get("init_time"))
            if init_key != run_key:
                continue
            valid_key = _time_key_from_any(getattr(item, "time", None))
            if valid_key:
                times.add(valid_key)

        sorted_times = sorted(times)
        etag = _etag_from_parts([run_key, *sorted_times])
        return CacheRecord(etag=etag, payload={"run": run_key, "times": sorted_times})

    cache_key = f"ecmwf:times:{run_key}"
    try:
        if cache is None:
            record = await compute()
        else:
            record = (await cache.get_or_compute(cache_key, compute=compute)).record
    except Exception as exc:  # noqa: BLE001
        raise _handle_data_source_error(exc) from exc

    times = record.payload.get("times", [])
    if not isinstance(times, list):
        times = []

    headers = {"Cache-Control": SHORT_CACHE_CONTROL_HEADER, "ETag": record.etag}
    if if_none_match_matches(request.headers.get("if-none-match"), record.etag):
        return Response(status_code=304, headers=headers)

    response.headers.update(headers)
    return EcmwfTimesResponse(run=run_key, times=[str(item) for item in times])
