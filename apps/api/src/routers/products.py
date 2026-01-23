from __future__ import annotations

import hashlib
import json
import logging
import math
import uuid
from asyncio import to_thread
from base64 import b64encode
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
from models import Product, ProductHazard, ProductVersion

logger = logging.getLogger("api.error")

router = APIRouter(prefix="/products", tags=["products"])

CACHE_CONTROL_PUBLIC_HEADER = "public, max-age=60"
CACHE_CONTROL_PRIVATE_HEADER = "private, max-age=60"
CACHE_FRESH_TTL_SECONDS = 60
CACHE_STALE_TTL_SECONDS = 60 * 60
CACHE_LOCK_TTL_MS = 30_000
CACHE_WAIT_TIMEOUT_MS = 200
CACHE_COOLDOWN_TTL_SECONDS: tuple[int, int] = (5, 30)

PRODUCTS_LIST_CACHE_EPOCH_KEY = "products:list:epoch"
PRODUCTS_LIST_CACHE_EPOCH_TTL_SECONDS = 60 * 60 * 24

PRODUCT_DETAIL_CACHE_EPOCH_KEY_PREFIX = "products:detail:epoch"
PRODUCT_DETAIL_CACHE_EPOCH_TTL_SECONDS = 60 * 60 * 24


def _cache_control_for_product_status(status: str | None) -> str:
    if status == "published":
        return CACHE_CONTROL_PUBLIC_HEADER
    return CACHE_CONTROL_PRIVATE_HEADER


def _parse_status_from_detail_body(body: bytes) -> str | None:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    if not isinstance(status, str):
        return None
    return status


def _make_etag(body: bytes) -> str:
    return f'"sha256-{hashlib.sha256(body).hexdigest()}"'


def _pack_cached_http_response(*, body: bytes, etag: str, cache_control: str) -> bytes:
    etag_text = etag.replace("\n", "").strip()
    cache_control_text = cache_control.replace("\n", "").strip()
    return (
        etag_text.encode("utf-8")
        + b"\n"
        + cache_control_text.encode("utf-8")
        + b"\n"
        + body
    )


def _unpack_cached_http_response(payload: bytes) -> tuple[bytes, str | None, str | None]:
    if not payload.startswith(b'"sha256-'):
        return payload, None, None

    etag_line, sep, remainder = payload.partition(b"\n")
    if not sep:
        return payload, None, None
    etag = etag_line.decode("utf-8", errors="ignore").strip() or None

    cache_control_line, sep2, body = remainder.partition(b"\n")
    if not sep2:
        return remainder, etag, None

    cache_control = cache_control_line.decode("utf-8", errors="ignore").strip() or None
    return body, etag, cache_control


def _normalize_time(value: datetime) -> datetime:
    parsed = value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _isoformat(dt: datetime) -> str:
    normalized = _normalize_time(dt)
    text = normalized.isoformat()
    if text.endswith("+00:00"):
        return text[:-6] + "Z"
    return text


def _serialize_geometry_for_snapshot(geometry: object) -> object:
    if isinstance(geometry, memoryview):
        geometry = geometry.tobytes()
    if isinstance(geometry, (bytes, bytearray)):
        encoded = b64encode(bytes(geometry)).decode("ascii")
        return {"encoding": "base64", "data": encoded}
    return geometry


def _build_product_snapshot(product: Product, *, version: int) -> dict[str, object]:
    return {
        "id": int(product.id),
        "title": product.title,
        "text": product.text,
        "issued_at": _isoformat(product.issued_at),
        "valid_from": _isoformat(product.valid_from),
        "valid_to": _isoformat(product.valid_to),
        "status": "published",
        "version": int(version),
        "hazards": [
            {
                "id": int(hazard.id),
                "severity": hazard.severity,
                "geometry": _serialize_geometry_for_snapshot(hazard.geometry),
                "valid_from": _isoformat(hazard.valid_from),
                "valid_to": _isoformat(hazard.valid_to),
                "bbox": {
                    "min_x": float(hazard.bbox_min_x),
                    "min_y": float(hazard.bbox_min_y),
                    "max_x": float(hazard.bbox_max_x),
                    "max_y": float(hazard.bbox_max_y),
                },
            }
            for hazard in product.hazards
        ],
    }


async def _get_products_list_cache_epoch(redis: RedisLike) -> str:
    try:
        cached = await redis.get(PRODUCTS_LIST_CACHE_EPOCH_KEY)
    except Exception:  # noqa: BLE001
        return "0"

    if cached:
        decoded = cached.decode("utf-8", errors="ignore").strip()
        return decoded or "0"

    token = uuid.uuid4().hex
    try:
        await redis.set(
            PRODUCTS_LIST_CACHE_EPOCH_KEY,
            token.encode("utf-8"),
            ex=PRODUCTS_LIST_CACHE_EPOCH_TTL_SECONDS,
        )
    except Exception:  # noqa: BLE001
        return token

    return token


async def _bump_products_list_cache_epoch(redis: RedisLike | None) -> None:
    if redis is None:
        return

    token = uuid.uuid4().hex
    try:
        await redis.set(
            PRODUCTS_LIST_CACHE_EPOCH_KEY,
            token.encode("utf-8"),
            ex=PRODUCTS_LIST_CACHE_EPOCH_TTL_SECONDS,
        )
    except Exception:  # noqa: BLE001
        logger.warning("products_cache_epoch_bump_failed")


def _product_detail_cache_epoch_key(product_id: int) -> str:
    return f"{PRODUCT_DETAIL_CACHE_EPOCH_KEY_PREFIX}:{int(product_id)}"


async def _get_product_detail_cache_epoch(redis: RedisLike, product_id: int) -> str:
    key = _product_detail_cache_epoch_key(product_id)
    try:
        cached = await redis.get(key)
    except Exception:  # noqa: BLE001
        return "0"

    if cached:
        decoded = cached.decode("utf-8", errors="ignore").strip()
        return decoded or "0"

    token = uuid.uuid4().hex
    try:
        await redis.set(
            key,
            token.encode("utf-8"),
            ex=PRODUCT_DETAIL_CACHE_EPOCH_TTL_SECONDS,
        )
    except Exception:  # noqa: BLE001
        return token

    return token


async def _bump_product_detail_cache_epoch(
    redis: RedisLike | None, product_id: int
) -> None:
    if redis is None:
        return

    token = uuid.uuid4().hex
    key = _product_detail_cache_epoch_key(product_id)
    try:
        await redis.set(
            key,
            token.encode("utf-8"),
            ex=PRODUCT_DETAIL_CACHE_EPOCH_TTL_SECONDS,
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "product_detail_cache_epoch_bump_failed",
            extra={"product_id": int(product_id)},
        )


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


ProductStatus = Literal["draft", "published"]


class ProductHazardUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: str
    geometry: Any
    valid_from: datetime
    valid_to: datetime


class ProductUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    text: str | None = None
    issued_at: datetime
    valid_from: datetime
    valid_to: datetime
    hazards: list[ProductHazardUpsertRequest] = Field(default_factory=list)


class ProductUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    text: str | None = None
    issued_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    hazards: list[ProductHazardUpsertRequest] | None = None


class ProductHazardDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    severity: str
    geometry: Any
    bbox: BBoxResponse
    valid_from: datetime
    valid_to: datetime


class ProductDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    title: str
    text: str | None = None
    issued_at: datetime
    valid_from: datetime
    valid_to: datetime
    version: int
    status: ProductStatus
    hazards: list[ProductHazardDetailResponse] = Field(default_factory=list)


class ProductVersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    product_id: int
    version: int
    published_at: datetime
    snapshot: dict[str, Any]


class ProductVersionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProductVersionResponse] = Field(default_factory=list)


def _hazard_from_request(payload: ProductHazardUpsertRequest) -> ProductHazard:
    hazard = ProductHazard(
        severity=payload.severity,
        valid_from=_normalize_time(payload.valid_from),
        valid_to=_normalize_time(payload.valid_to),
        bbox_min_x=0,
        bbox_min_y=0,
        bbox_max_x=0,
        bbox_max_y=0,
    )
    try:
        hazard.set_geometry_from_geojson(payload.geometry)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return hazard


def _product_detail_response(product: Product) -> ProductDetailResponse:
    return ProductDetailResponse(
        id=product.id,
        title=product.title,
        text=product.text,
        issued_at=_normalize_time(product.issued_at),
        valid_from=_normalize_time(product.valid_from),
        valid_to=_normalize_time(product.valid_to),
        version=product.version,
        status=product.status,  # type: ignore[arg-type]
        hazards=[
            ProductHazardDetailResponse(
                id=hazard.id,
                severity=hazard.severity,
                geometry=hazard.geometry,
                bbox=BBoxResponse(
                    min_x=hazard.bbox_min_x,
                    min_y=hazard.bbox_min_y,
                    max_x=hazard.bbox_max_x,
                    max_y=hazard.bbox_max_y,
                ),
                valid_from=_normalize_time(hazard.valid_from),
                valid_to=_normalize_time(hazard.valid_to),
            )
            for hazard in product.hazards
        ],
    )


def _product_version_response(version: ProductVersion) -> ProductVersionResponse:
    snapshot = version.snapshot
    if not isinstance(snapshot, dict):
        snapshot = {"data": snapshot}

    return ProductVersionResponse(
        id=version.id,
        product_id=version.product_id,
        version=version.version,
        published_at=_normalize_time(version.published_at),
        snapshot=snapshot,  # type: ignore[arg-type]
    )


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


def _query_product_detail(product_id: int) -> ProductDetailResponse:
    try:
        with Session(db.get_engine()) as session:
            product = session.execute(
                select(Product)
                .options(selectinload(Product.hazards))
                .where(Product.id == product_id)
            ).scalar_one_or_none()
            if product is None:
                raise HTTPException(status_code=404, detail="Product not found")
            return _product_detail_response(product)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("products_db_error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc


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
            body = payload.model_dump_json().encode("utf-8")
            cache_control = _cache_control_for_product_status(status)
            etag = _make_etag(body)
            return _pack_cached_http_response(
                body=body, etag=etag, cache_control=cache_control
            )

        return await to_thread(_sync)

    if redis is None:
        cached_payload = await _compute()
    else:
        epoch = await _get_products_list_cache_epoch(redis)
        status_identity = status or "all"
        type_identity = "all" if types is None else ",".join(types)
        time_identity = "all" if valid_time is None else _cache_time_key(valid_time)
        bbox_identity = (
            "all"
            if bbox_tuple is None
            else ",".join(f"{value!r}" for value in bbox_tuple)
        )
        identity = (
            f"epoch={epoch}:status={status_identity}:type={type_identity}:"
            f"time={time_identity}:bbox={bbox_identity}:page={page}:size={page_size}"
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
            cached_payload = result.body
        except TimeoutError as exc:
            raise HTTPException(
                status_code=503, detail="Products cache warming timed out"
            ) from exc
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("products_cache_unavailable", extra={"error": str(exc)})
            cached_payload = await _compute()

    body, etag, cache_control = _unpack_cached_http_response(cached_payload)
    if etag is None:
        etag = _make_etag(body)
    if cache_control is None:
        cache_control = _cache_control_for_product_status(status)
    headers = {"Cache-Control": cache_control, "ETag": etag}

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


@router.post("", response_model=ProductDetailResponse, status_code=201)
async def create_product(
    request: Request,
    payload: ProductUpsertRequest,
) -> ProductDetailResponse:
    redis: RedisLike | None = getattr(request.app.state, "redis_client", None)

    try:
        with Session(db.get_engine()) as session:
            product = Product(
                title=payload.title,
                text=payload.text,
                issued_at=_normalize_time(payload.issued_at),
                valid_from=_normalize_time(payload.valid_from),
                valid_to=_normalize_time(payload.valid_to),
                status="draft",
            )
            product.hazards.extend(
                _hazard_from_request(hazard) for hazard in payload.hazards
            )

            session.add(product)
            session.commit()

            loaded = session.execute(
                select(Product)
                .options(selectinload(Product.hazards))
                .where(Product.id == product.id)
            ).scalar_one()
            response = _product_detail_response(loaded)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("products_db_error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc

    await _bump_products_list_cache_epoch(redis)
    await _bump_product_detail_cache_epoch(redis, response.id)
    return response


@router.put("/{product_id}", response_model=ProductDetailResponse)
async def update_product(
    request: Request,
    product_id: int,
    payload: ProductUpdateRequest,
) -> ProductDetailResponse:
    redis: RedisLike | None = getattr(request.app.state, "redis_client", None)

    try:
        with Session(db.get_engine()) as session:
            product = session.execute(
                select(Product)
                .options(selectinload(Product.hazards))
                .where(Product.id == product_id)
            ).scalar_one_or_none()
            if product is None:
                raise HTTPException(status_code=404, detail="Product not found")

            update_data = payload.model_dump(exclude_unset=True)
            if "title" in update_data:
                title = update_data["title"]
                if title is None:
                    raise HTTPException(
                        status_code=400, detail="title must not be null"
                    )
                product.title = str(title)
            if "text" in update_data:
                product.text = update_data["text"]
            if "issued_at" in update_data:
                issued_at = update_data["issued_at"]
                if issued_at is None:
                    raise HTTPException(
                        status_code=400, detail="issued_at must not be null"
                    )
                product.issued_at = _normalize_time(issued_at)
            if "valid_from" in update_data:
                valid_from = update_data["valid_from"]
                if valid_from is None:
                    raise HTTPException(
                        status_code=400, detail="valid_from must not be null"
                    )
                product.valid_from = _normalize_time(valid_from)
            if "valid_to" in update_data:
                valid_to = update_data["valid_to"]
                if valid_to is None:
                    raise HTTPException(
                        status_code=400, detail="valid_to must not be null"
                    )
                product.valid_to = _normalize_time(valid_to)

            if "hazards" in update_data:
                product.hazards.clear()
                hazards = payload.hazards or []
                product.hazards.extend(
                    _hazard_from_request(hazard) for hazard in hazards
                )

            product.status = "draft"

            session.commit()

            loaded = session.execute(
                select(Product)
                .options(selectinload(Product.hazards))
                .where(Product.id == product_id)
            ).scalar_one()
            response = _product_detail_response(loaded)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("products_db_error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc

    await _bump_products_list_cache_epoch(redis)
    await _bump_product_detail_cache_epoch(redis, product_id)
    return response


@router.post("/{product_id}/publish", response_model=ProductVersionResponse)
async def publish_product(
    request: Request,
    product_id: int,
) -> ProductVersionResponse:
    redis: RedisLike | None = getattr(request.app.state, "redis_client", None)

    try:
        with Session(db.get_engine()) as session:
            product = session.execute(
                select(Product)
                .options(selectinload(Product.hazards))
                .where(Product.id == product_id)
            ).scalar_one_or_none()
            if product is None:
                raise HTTPException(status_code=404, detail="Product not found")

            last_version = session.execute(
                select(func.max(ProductVersion.version)).where(
                    ProductVersion.product_id == product_id
                )
            ).scalar_one()
            next_version = int(last_version or 0) + 1

            snapshot = _build_product_snapshot(product, version=next_version)
            version_row = ProductVersion(
                product_id=product_id,
                version=next_version,
                snapshot=snapshot,
            )
            session.add(version_row)

            product.status = "published"
            product.version = next_version

            session.commit()

            session.refresh(version_row)
            response = _product_version_response(version_row)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("products_db_error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc

    await _bump_products_list_cache_epoch(redis)
    await _bump_product_detail_cache_epoch(redis, product_id)
    return response


@router.get("/{product_id}", response_model=ProductDetailResponse)
async def get_product(request: Request, product_id: int) -> Response:
    redis: RedisLike | None = getattr(request.app.state, "redis_client", None)

    async def _compute() -> bytes:
        def _sync() -> bytes:
            payload = _query_product_detail(product_id)
            body = payload.model_dump_json().encode("utf-8")
            cache_control = _cache_control_for_product_status(payload.status)
            etag = _make_etag(body)
            return _pack_cached_http_response(
                body=body, etag=etag, cache_control=cache_control
            )

        return await to_thread(_sync)

    if redis is None:
        cached_payload = await _compute()
    else:
        epoch = await _get_product_detail_cache_epoch(redis, product_id)
        identity = f"epoch={epoch}:product={int(product_id)}"
        identity_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()

        fresh_key = f"products:detail:fresh:{identity_hash}"
        stale_key = f"products:detail:stale:{identity_hash}"
        lock_key = f"products:detail:lock:{identity_hash}"

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
            cached_payload = result.body
        except TimeoutError as exc:
            raise HTTPException(
                status_code=503, detail="Product cache warming timed out"
            ) from exc
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("product_cache_unavailable", extra={"error": str(exc)})
            cached_payload = await _compute()

    body, etag, cache_control = _unpack_cached_http_response(cached_payload)
    if etag is None:
        etag = _make_etag(body)
    if cache_control is None:
        product_status = _parse_status_from_detail_body(body)
        cache_control = _cache_control_for_product_status(product_status)
    headers = {"Cache-Control": cache_control, "ETag": etag}

    if if_none_match_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)

    return Response(content=body, media_type="application/json", headers=headers)


@router.get("/{product_id}/versions", response_model=ProductVersionsResponse)
def list_product_versions(product_id: int) -> ProductVersionsResponse:
    try:
        with Session(db.get_engine()) as session:
            product = session.get(Product, product_id)
            if product is None:
                raise HTTPException(status_code=404, detail="Product not found")

            versions = (
                session.execute(
                    select(ProductVersion)
                    .where(ProductVersion.product_id == product_id)
                    .order_by(desc(ProductVersion.version))
                )
                .scalars()
                .all()
            )
            return ProductVersionsResponse(
                items=[_product_version_response(item) for item in versions]
            )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("products_db_error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc
