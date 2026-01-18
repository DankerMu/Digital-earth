from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from catalog_cache import RedisLike, get_or_compute_cached_bytes
import db
from http_cache import if_none_match_matches
from models import RiskPOI
from risk.intensity_mapping import RiskIntensityMapping
from risk_intensity_config import get_risk_intensity_mappings_payload

router = APIRouter(prefix="/risk", tags=["risk"])
logger = logging.getLogger("api.error")

CACHE_CONTROL_HEADER = "public, max-age=60"
CACHE_FRESH_TTL_SECONDS = 60
CACHE_STALE_TTL_SECONDS = 60 * 60
CACHE_LOCK_TTL_MS = 30_000
CACHE_WAIT_TIMEOUT_MS = 200
CACHE_COOLDOWN_TTL_SECONDS: tuple[int, int] = (5, 30)


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


def _parse_bbox(value: str) -> tuple[float, float, float, float]:
    text = (value or "").strip()
    if text == "":
        raise ValueError("bbox must be provided")

    parts = [item.strip() for item in text.split(",") if item.strip() != ""]
    if len(parts) != 4:
        raise ValueError("bbox must be min_lon,min_lat,max_lon,max_lat")

    try:
        min_lon, min_lat, max_lon, max_lat = (float(item) for item in parts)
    except ValueError as exc:
        raise ValueError("bbox values must be numbers") from exc

    if min_lon > max_lon:
        raise ValueError("bbox min_lon must be <= max_lon")
    if min_lat > max_lat:
        raise ValueError("bbox min_lat must be <= max_lat")

    return min_lon, min_lat, max_lon, max_lat


class RiskPOIItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    type: str
    lon: float
    lat: float
    alt: float | None = None
    weight: float
    tags: list[str] | None = None
    risk_level: int | None = Field(
        default=None,
        description="Risk level (1-5) when evaluated, otherwise null",
    )


class RiskPOIQueryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int
    page_size: int
    total: int
    items: list[RiskPOIItemResponse] = Field(default_factory=list)


def _query_risk_pois(
    *,
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    page: int,
    page_size: int,
) -> RiskPOIQueryResponse:
    offset = (page - 1) * page_size
    bbox_filters = (
        RiskPOI.lon >= min_lon,
        RiskPOI.lon <= max_lon,
        RiskPOI.lat >= min_lat,
        RiskPOI.lat <= max_lat,
    )

    count_stmt = select(func.count()).select_from(RiskPOI).where(*bbox_filters)
    stmt = (
        RiskPOI.select_in_bbox(
            min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat
        )
        .order_by(RiskPOI.id)
        .limit(page_size)
        .offset(offset)
    )

    try:
        with Session(db.get_engine()) as session:
            total = int(session.execute(count_stmt).scalar_one())
            pois = session.scalars(stmt).all()
    except SQLAlchemyError as exc:
        logger.error("risk_pois_db_error", extra={"error": str(exc)})
        raise HTTPException(
            status_code=503, detail="Risk POI database unavailable"
        ) from exc

    items = [
        RiskPOIItemResponse(
            id=item.id,
            name=item.name,
            type=item.poi_type,
            lon=item.lon,
            lat=item.lat,
            alt=item.alt,
            weight=item.weight,
            tags=item.tags,
            risk_level=None,
        )
        for item in pois
    ]
    return RiskPOIQueryResponse(
        page=page, page_size=page_size, total=total, items=items
    )


@router.get("/pois", response_model=RiskPOIQueryResponse)
async def get_risk_pois(
    request: Request,
    bbox: str = Query(description="Bounding box: min_lon,min_lat,max_lon,max_lat"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=1000),
) -> Response:
    try:
        min_lon, min_lat, max_lon, max_lat = _parse_bbox(bbox)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    redis: RedisLike | None = getattr(request.app.state, "redis_client", None)

    async def _compute() -> bytes:
        payload = _query_risk_pois(
            min_lon=min_lon,
            min_lat=min_lat,
            max_lon=max_lon,
            max_lat=max_lat,
            page=page,
            page_size=page_size,
        )
        return payload.model_dump_json().encode("utf-8")

    if redis is None:
        body = await _compute()
    else:
        identity = (
            f"{min_lon!r},{min_lat!r},{max_lon!r},{max_lat!r}"
            f":page={page}:size={page_size}"
        )
        fresh_key = f"risk:pois:fresh:{identity}"
        stale_key = f"risk:pois:stale:{identity}"
        lock_key = f"risk:pois:lock:{identity}"

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
                status_code=503, detail="Risk POI cache warming timed out"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            logger.warning("risk_pois_cache_unavailable", extra={"error": str(exc)})
            body = await _compute()

    etag = f'"sha256-{hashlib.sha256(body).hexdigest()}"'
    headers = {"Cache-Control": CACHE_CONTROL_HEADER, "ETag": etag}

    if if_none_match_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)

    return Response(content=body, media_type="application/json", headers=headers)
