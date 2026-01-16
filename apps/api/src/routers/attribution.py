from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response

from attribution_config import get_attribution_payload

router = APIRouter(tags=["meta"])


def _if_none_match_matches(header: Optional[str], etag: str) -> bool:
    if header is None:
        return False

    text = header.strip()
    if text == "":
        return False
    if text == "*":
        return True

    return any(item.strip() == etag for item in text.split(","))


@router.get("/attribution", response_class=PlainTextResponse)
def attribution(request: Request) -> Response:
    try:
        payload = get_attribution_payload()
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    headers = {
        "Cache-Control": "public, max-age=0, must-revalidate",
        "ETag": payload.etag,
        "X-Attribution-Version": payload.version,
    }

    if _if_none_match_matches(request.headers.get("if-none-match"), payload.etag):
        return Response(status_code=304, headers=headers)

    return PlainTextResponse(payload.text, headers=headers)
