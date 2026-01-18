from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from data_source import DataNotFoundError, DataSourceError
from http_cache import if_none_match_matches
from local_data_service import get_data_source

logger = logging.getLogger("api.error")

router = APIRouter(prefix="/catalog", tags=["catalog"])

SHORT_CACHE_CONTROL_HEADER = "public, max-age=60"


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

