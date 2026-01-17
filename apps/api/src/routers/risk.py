from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from http_cache import if_none_match_matches
from risk.intensity_mapping import RiskIntensityMapping
from risk_intensity_config import get_risk_intensity_mappings_payload

router = APIRouter(prefix="/risk", tags=["risk"])
logger = logging.getLogger("api.error")


class RiskIntensityMappingsResponse(BaseModel):
    merge_strategy: str = Field(
        description="Rule for merging risk level with product severity"
    )
    mappings: list[RiskIntensityMapping]


@router.get("/intensity-mapping", response_model=RiskIntensityMappingsResponse)
def get_risk_intensity_mapping(
    request: Request,
    response: Response,
) -> Response | RiskIntensityMappingsResponse:
    try:
        payload = get_risk_intensity_mappings_payload()
    except (FileNotFoundError, ValueError) as exc:
        logger.error("risk_intensity_config_error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc

    headers = {
        "Cache-Control": "public, max-age=0, must-revalidate",
        "ETag": payload.etag,
    }

    if if_none_match_matches(request.headers.get("if-none-match"), payload.etag):
        return Response(status_code=304, headers=headers)

    response.headers.update(headers)
    return RiskIntensityMappingsResponse(
        merge_strategy="max",
        mappings=list(payload.mappings),
    )
