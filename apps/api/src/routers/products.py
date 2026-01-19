from __future__ import annotations

import hashlib
import logging
import math
from asyncio import to_thread
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from catalog_cache import RedisLike, get_or_compute_cached_bytes
import db
from http_cache import if_none_match_matches
from models import Product, ProductHazard

logger = logging.getLogger("api.error")

router = APIRouter(prefix="/products", tags=["products"])

CACHE_CONTROL_HEADER = "public, max-age=60"
CACHE_FRESH_TTL_SECONDS = 60
CACHE_STALE_TTL_SECONDS = 60 * 60
CACHE_LOCK_TTL_MS = 30_000
CACHE_WAIT_TIMEOUT_MS = 200
CACHE_COOLDOWN_TTL_SECONDS: tuple[int, int] = (5, 30)


def _normalize_time(value: datetime) -> datetime:
    parsed = value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_bbox(value: Optional[str]) -> Optional[tuple[float, float, float, float]]:
    if value is None:
        return None
    raw = value.strip()
    if raw == "":
        return None

    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 4:
        raise HTTPException(
            status_code=400, detail="bbox must be 'min_x,min_y,max_x,max_y'"
        )

    try:
        min_x, min_y, max_x, max_y = (float(part) for part in parts)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="bbox must contain 4 numbers"
        ) from exc

    if not all(math.isfinite(v) for v in (min_x, min_y, max_x, max_y)):
        raise HTTPException(status_code=400, detail="bbox values must be finite")

    if max_x <= min_x or max_y <= min_y:
        raise HTTPException(status_code=400, detail="bbox must have positive area")

    return min_x, min_y, max_x, max_y


def _hazard_matches_filters(
    hazard: ProductHazard,
    *,
    start: datetime | None,
    end: datetime | None,
    bbox: tuple[float, float, float, float] | None,
) -> bool:
    if start is not None or end is not None:
        if start is None:
            start_norm = _normalize_time(end)
            end_norm = start_norm
        elif end is None:
            start_norm = _normalize_time(start)
            end_norm = start_norm
        else:
            start_norm = _normalize_time(start)
            end_norm = _normalize_time(end)

        hazard_from = _normalize_time(hazard.valid_from)
        hazard_to = _normalize_time(hazard.valid_to)
        if hazard_from > end_norm or hazard_to < start_norm:
            return False

    if bbox is not None:
        bbox_min_x, bbox_min_y, bbox_max_x, bbox_max_y = bbox
        if hazard.bbox_min_x > bbox_max_x or hazard.bbox_max_x < bbox_min_x:
            return False
        if hazard.bbox_min_y > bbox_max_y or hazard.bbox_max_y < bbox_min_y:
            return False

    return True


class BBoxResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_x: float
    min_y: float
    max_x: float
    max_y: float


class ProductHazardSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: str
    geometry: Any
    bbox: BBoxResponse


class ProductSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    title: str
    hazards: list[ProductHazardSummaryResponse] = Field(default_factory=list)


class ProductsQueryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int
    page_size: int
    total: int
    items: list[ProductSummaryResponse] = Field(default_factory=list)


def _parse_types(value: str | None) -> list[str] | None:
    if value is None:
        return None
    raw = value.strip()
    if raw == "":
        return None

    parts = [part.strip() for part in raw.split(",")]
    cleaned = sorted({part for part in parts if part})
    return cleaned or None


def _cache_time_key(value: datetime) -> str:
    return _normalize_time(value).strftime("%Y%m%dT%H%M%SZ")


def _query_product_summaries(
    *,
    status: str | None,
    types: list[str] | None,
    valid_time: datetime | None,
    bbox: tuple[float, float, float, float] | None,
    page: int,
    page_size: int,
) -> ProductsQueryResponse:
    offset = (page - 1) * page_size

    stmt = (
        select(Product)
        .options(selectinload(Product.hazards))
        .order_by(desc(Product.issued_at))
    )
    count_stmt = select(func.count()).select_from(Product)

    if status is not None:
        stmt = stmt.where(Product.status == status)
        count_stmt = count_stmt.where(Product.status == status)

    if types is not None:
        stmt = stmt.where(Product.title.in_(types))
        count_stmt = count_stmt.where(Product.title.in_(types))

    hazard_filter_enabled = valid_time is not None or bbox is not None
    hazard_clauses: list[object] = []

    if valid_time is not None:
        time_norm = _normalize_time(valid_time)
        hazard_clauses.append(ProductHazard.valid_from <= time_norm)
        hazard_clauses.append(ProductHazard.valid_to >= time_norm)

    if bbox is not None:
        bbox_min_x, bbox_min_y, bbox_max_x, bbox_max_y = bbox
        hazard_clauses.append(ProductHazard.bbox_min_x <= bbox_max_x)
        hazard_clauses.append(ProductHazard.bbox_max_x >= bbox_min_x)
        hazard_clauses.append(ProductHazard.bbox_min_y <= bbox_max_y)
        hazard_clauses.append(ProductHazard.bbox_max_y >= bbox_min_y)

    if hazard_filter_enabled:
        stmt = stmt.where(Product.hazards.any(and_(*hazard_clauses)))
        count_stmt = count_stmt.where(Product.hazards.any(and_(*hazard_clauses)))

    stmt = stmt.limit(page_size).offset(offset)

    try:
        with Session(db.get_engine()) as session:
            total = int(session.execute(count_stmt).scalar_one())
            products = session.execute(stmt).scalars().unique().all()
    except SQLAlchemyError as exc:
        logger.error("products_db_error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc

    items: list[ProductSummaryResponse] = []
    for product in products:
        hazards = [
            hazard
            for hazard in product.hazards
            if _hazard_matches_filters(
                hazard,
                start=valid_time,
                end=valid_time,
                bbox=bbox,
            )
        ]
        if hazard_filter_enabled and not hazards:
            continue

        items.append(
            ProductSummaryResponse(
                id=product.id,
                title=product.title,
                hazards=[
                    ProductHazardSummaryResponse(
                        severity=hazard.severity,
                        geometry=hazard.geometry,
                        bbox=BBoxResponse(
                            min_x=hazard.bbox_min_x,
                            min_y=hazard.bbox_min_y,
                            max_x=hazard.bbox_max_x,
                            max_y=hazard.bbox_max_y,
                        ),
                    )
                    for hazard in hazards
                ],
            )
        )

    return ProductsQueryResponse(
        page=page,
        page_size=page_size,
        total=total,
        items=items,
    )


@router.get("", response_model=ProductsQueryResponse)
async def list_products(
    request: Request,
    status: Optional[str] = Query(default="published"),
    type: str | None = Query(default=None, description="Filter by product title"),
    valid_time: datetime | None = Query(default=None),
    bbox: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1, le=1000),
    page_size: int = Query(default=50, ge=1, le=200),
) -> Response:
    bbox_tuple = _parse_bbox(bbox)
    types = _parse_types(type)

    redis: RedisLike | None = getattr(request.app.state, "redis_client", None)

    async def _compute() -> bytes:
        def _sync() -> bytes:
            payload = _query_product_summaries(
                status=status,
                types=types,
                valid_time=valid_time,
                bbox=bbox_tuple,
                page=page,
                page_size=page_size,
            )
            return payload.model_dump_json().encode("utf-8")

        return await to_thread(_sync)

    if redis is None:
        body = await _compute()
    else:
        status_identity = status or "all"
        type_identity = "all" if types is None else ",".join(types)
        time_identity = "all" if valid_time is None else _cache_time_key(valid_time)
        bbox_identity = (
            "all"
            if bbox_tuple is None
            else ",".join(f"{value!r}" for value in bbox_tuple)
        )
        identity = (
            f"status={status_identity}:type={type_identity}:time={time_identity}:"
            f"bbox={bbox_identity}:page={page}:size={page_size}"
        )
        identity_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()

        fresh_key = f"products:list:fresh:{identity_hash}"
        stale_key = f"products:list:stale:{identity_hash}"
        lock_key = f"products:list:lock:{identity_hash}"

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
                status_code=503, detail="Products cache warming timed out"
            ) from exc
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("products_cache_unavailable", extra={"error": str(exc)})
            body = await _compute()

    etag = f'"sha256-{hashlib.sha256(body).hexdigest()}"'
    headers = {"Cache-Control": CACHE_CONTROL_HEADER, "ETag": etag}

    if if_none_match_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)

    return Response(content=body, media_type="application/json", headers=headers)


GeoJSONFeatureType = Literal["Feature"]
GeoJSONFeatureCollectionType = Literal["FeatureCollection"]


class ProductHazardPropertiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int
    product_title: str
    product_status: str
    product_issued_at: datetime
    product_valid_from: datetime
    product_valid_to: datetime
    severity: str


class ProductHazardFeatureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: GeoJSONFeatureType = Field(default="Feature")
    id: int
    geometry: Any
    properties: ProductHazardPropertiesResponse


class ProductHazardFeatureCollectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: GeoJSONFeatureCollectionType = Field(default="FeatureCollection")
    features: list[ProductHazardFeatureResponse] = Field(default_factory=list)


@router.get("/hazards", response_model=ProductHazardFeatureCollectionResponse)
def list_product_hazards_geojson(
    status: Optional[str] = Query(default="published"),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    bbox: Optional[str] = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> ProductHazardFeatureCollectionResponse:
    bbox_tuple = _parse_bbox(bbox)

    stmt = (
        select(ProductHazard, Product)
        .join(Product, ProductHazard.product_id == Product.id)
        .order_by(desc(Product.issued_at), ProductHazard.id)
        .limit(limit)
        .offset(offset)
    )
    if status is not None:
        stmt = stmt.where(Product.status == status)

    if start is not None or end is not None:
        if start is None:
            start_norm = _normalize_time(end)
            end_norm = start_norm
        elif end is None:
            start_norm = _normalize_time(start)
            end_norm = start_norm
        else:
            start_norm = _normalize_time(start)
            end_norm = _normalize_time(end)

        stmt = stmt.where(ProductHazard.valid_from <= end_norm).where(
            ProductHazard.valid_to >= start_norm
        )

    if bbox_tuple is not None:
        bbox_min_x, bbox_min_y, bbox_max_x, bbox_max_y = bbox_tuple
        stmt = stmt.where(ProductHazard.bbox_min_x <= bbox_max_x).where(
            ProductHazard.bbox_max_x >= bbox_min_x
        )
        stmt = stmt.where(ProductHazard.bbox_min_y <= bbox_max_y).where(
            ProductHazard.bbox_max_y >= bbox_min_y
        )

    try:
        with Session(db.get_engine()) as session:
            rows = session.execute(stmt).all()
    except SQLAlchemyError as exc:
        logger.error("product_hazards_db_error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc

    features = [
        ProductHazardFeatureResponse(
            id=hazard.id,
            geometry=hazard.geometry,
            properties=ProductHazardPropertiesResponse(
                product_id=product.id,
                product_title=product.title,
                product_status=product.status,
                product_issued_at=_normalize_time(product.issued_at),
                product_valid_from=_normalize_time(product.valid_from),
                product_valid_to=_normalize_time(product.valid_to),
                severity=hazard.severity,
            ),
        )
        for hazard, product in rows
    ]

    return ProductHazardFeatureCollectionResponse(features=features)
