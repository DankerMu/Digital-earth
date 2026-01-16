from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from effect_presets_config import EffectPresetItem, EffectType, get_effect_presets_payload

router = APIRouter(prefix="/effects", tags=["effects"])


def _if_none_match_matches(header: Optional[str], etag: str) -> bool:
    if header is None:
        return False

    text = header.strip()
    if text == "":
        return False
    if text == "*":
        return True

    return any(item.strip() == etag for item in text.split(","))


@router.get("/presets", response_model=list[EffectPresetItem])
def list_effect_presets(
    request: Request,
    response: Response,
    effect_type: Optional[EffectType] = Query(default=None, description="Filter by type"),
) -> Response | list[EffectPresetItem]:
    try:
        payload = get_effect_presets_payload()
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    headers = {
        "Cache-Control": "public, max-age=0, must-revalidate",
        "ETag": payload.etag,
    }

    if _if_none_match_matches(request.headers.get("if-none-match"), payload.etag):
        return Response(status_code=304, headers=headers)

    presets = payload.presets
    if effect_type is not None:
        presets = tuple(preset for preset in presets if preset.effect_type == effect_type)

    response.headers.update(headers)
    return list(presets)
