from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, desc, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

import db
from models import Product, ProductHazard

logger = logging.getLogger("api.error")

router = APIRouter(prefix="/products", tags=["products"])


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


class ProductHazardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    severity: str
    geometry: Any
    valid_from: datetime
    valid_to: datetime
    bbox: BBoxResponse


class ProductResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    title: str
    text: Optional[str] = None
    issued_at: datetime
    valid_from: datetime
    valid_to: datetime
    version: int
    status: str
    hazards: list[ProductHazardResponse] = Field(default_factory=list)


class ProductsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProductResponse] = Field(default_factory=list)


@router.get("", response_model=ProductsResponse)
def list_products(
    status: Optional[str] = Query(default="published"),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    bbox: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ProductsResponse:
    bbox_tuple = _parse_bbox(bbox)

    stmt = (
        select(Product)
        .options(selectinload(Product.hazards))
        .order_by(desc(Product.issued_at))
    )
    if status is not None:
        stmt = stmt.where(Product.status == status)

    hazard_filter_enabled = (
        start is not None or end is not None or bbox_tuple is not None
    )
    if hazard_filter_enabled:
        hazard_clauses: list[object] = []

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

            hazard_clauses.append(ProductHazard.valid_from <= end_norm)
            hazard_clauses.append(ProductHazard.valid_to >= start_norm)

        if bbox_tuple is not None:
            bbox_min_x, bbox_min_y, bbox_max_x, bbox_max_y = bbox_tuple
            hazard_clauses.append(ProductHazard.bbox_min_x <= bbox_max_x)
            hazard_clauses.append(ProductHazard.bbox_max_x >= bbox_min_x)
            hazard_clauses.append(ProductHazard.bbox_min_y <= bbox_max_y)
            hazard_clauses.append(ProductHazard.bbox_max_y >= bbox_min_y)

        stmt = stmt.where(Product.hazards.any(and_(*hazard_clauses)))

    stmt = stmt.limit(limit).offset(offset)

    try:
        with Session(db.get_engine()) as session:
            products = session.execute(stmt).scalars().unique().all()
    except SQLAlchemyError as exc:
        logger.error("products_db_error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc

    items: list[ProductResponse] = []
    for product in products:
        hazards = [
            hazard
            for hazard in product.hazards
            if _hazard_matches_filters(
                hazard,
                start=start,
                end=end,
                bbox=bbox_tuple,
            )
        ]
        if hazard_filter_enabled and not hazards:
            continue

        items.append(
            ProductResponse(
                id=product.id,
                title=product.title,
                text=product.text,
                issued_at=_normalize_time(product.issued_at),
                valid_from=_normalize_time(product.valid_from),
                valid_to=_normalize_time(product.valid_to),
                version=product.version,
                status=product.status,
                hazards=[
                    ProductHazardResponse(
                        id=hazard.id,
                        severity=hazard.severity,
                        geometry=hazard.geometry,
                        valid_from=_normalize_time(hazard.valid_from),
                        valid_to=_normalize_time(hazard.valid_to),
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

    return ProductsResponse(items=items)


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
