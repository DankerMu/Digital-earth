from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from http_cache import if_none_match_matches
from legend_config import (
    LegendConfigItem,
    get_legend_config_payload,
    normalize_layer_type,
)

router = APIRouter(prefix="/legends", tags=["legends"])
logger = logging.getLogger("api.error")


def _legend_response(request: Request, layer_type: str) -> Response:
    try:
        normalized = normalize_layer_type(layer_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        payload = get_legend_config_payload(normalized)
    except FileNotFoundError as exc:
        logger.error("legend_config_missing", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc
    except ValueError as exc:
        logger.error("legend_config_invalid", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("legend_config_error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc

    headers = {
        "Cache-Control": "public, max-age=0, must-revalidate",
        "ETag": payload.etag,
    }
    if if_none_match_matches(request.headers.get("if-none-match"), payload.etag):
        return Response(status_code=304, headers=headers)

    return Response(
        content=payload.body, media_type="application/json", headers=headers
    )


@router.get("", response_model=LegendConfigItem)
def get_legends(
    request: Request,
    layer_type: str = Query(
        ...,
        description="Layer type (temperature, cloud, precipitation, wind)",
    ),
) -> Response:
    return _legend_response(request, layer_type)


@router.get("/{layer_type}", response_model=LegendConfigItem)
def get_legend_by_type(request: Request, layer_type: str) -> Response:
    return _legend_response(request, layer_type)
