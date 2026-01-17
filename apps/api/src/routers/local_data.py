from __future__ import annotations

import dataclasses
import logging
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from data_source import DataNotFoundError, DataSourceError
from local_data_service import get_data_source

logger = logging.getLogger("api.error")

router = APIRouter(prefix="/local-data", tags=["local-data"])

LocalKind = Literal["cldas", "ecmwf", "town_forecast"]


def _handle_data_source_error(exc: Exception) -> HTTPException:
    if isinstance(exc, DataNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, DataSourceError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="Internal Server Error")


@router.get("/index")
def get_local_index(
    kind: Optional[LocalKind] = Query(default=None),
    refresh: bool = Query(default=False),
) -> dict:
    ds = get_data_source()
    kinds = {kind} if kind else None
    try:
        index = ds.list_files(kinds=kinds, refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        logger.error("local_data_index_error", extra={"error": str(exc)})
        raise _handle_data_source_error(exc) from exc
    return index.model_dump()


@router.get("/file")
def get_local_file(relative_path: str = Query(..., min_length=1)) -> FileResponse:
    ds = get_data_source()
    try:
        path = ds.open_path(relative_path)
    except Exception as exc:  # noqa: BLE001
        logger.error("local_data_open_error", extra={"error": str(exc)})
        raise _handle_data_source_error(exc) from exc
    return FileResponse(path)


@router.get("/cldas/summary")
def get_cldas_summary(relative_path: str = Query(..., min_length=1)) -> dict:
    ds = get_data_source()
    try:
        summary = ds.load_cldas_summary(relative_path)
    except Exception as exc:  # noqa: BLE001
        logger.error("local_data_cldas_error", extra={"error": str(exc)})
        raise _handle_data_source_error(exc) from exc
    return dataclasses.asdict(summary)


@router.get("/town-forecast")
def get_town_forecast(
    relative_path: str = Query(..., min_length=1),
    max_stations: int = Query(default=50, ge=1, le=500),
) -> dict:
    ds = get_data_source()
    try:
        parsed = ds.load_town_forecast(relative_path, max_stations=max_stations)
    except Exception as exc:  # noqa: BLE001
        logger.error("local_data_town_forecast_error", extra={"error": str(exc)})
        raise _handle_data_source_error(exc) from exc
    return parsed.model_dump()
