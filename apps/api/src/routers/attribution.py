from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response

from attribution_config import get_attribution_payload
from http_cache import if_none_match_matches

router = APIRouter(tags=["meta"])
logger = logging.getLogger("api.error")


@router.get("/attribution", response_class=PlainTextResponse)
def attribution(request: Request) -> Response:
    try:
        payload = get_attribution_payload()
    except (FileNotFoundError, ValueError) as exc:
        logger.error("attribution_config_error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc

    headers = {
        "Cache-Control": "public, max-age=0, must-revalidate",
        "ETag": payload.etag,
        "X-Attribution-Version": payload.version,
    }

    if if_none_match_matches(request.headers.get("if-none-match"), payload.etag):
        return Response(status_code=304, headers=headers)

    return PlainTextResponse(payload.text, headers=headers)
