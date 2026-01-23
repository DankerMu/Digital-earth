from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from asyncio import to_thread
from datetime import datetime, timezone
from typing import Literal, TypeAlias, TypedDict

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from catalog_cache import RedisLike, get_or_compute_cached_bytes
import db
from http_cache import if_none_match_matches
from models import RiskPOI, RiskPOIEvaluation
from risk.intensity_mapping import RiskIntensityMapping
from risk.rules import RiskEvaluationResult, RiskRuleModel
from risk_intensity_config import get_risk_intensity_mappings_payload
from risk_rules_config import get_risk_rules_payload
from risk_engine import (
    POIRiskResult,
    RiskEngineDatabaseError,
    RiskEngineInputError,
    RiskEngineNotFoundError,
    RiskEvaluationEngine,
)

router = APIRouter(prefix="/risk", tags=["risk"])
logger = logging.getLogger("api.error")

CACHE_CONTROL_HEADER = "public, max-age=60"
CACHE_FRESH_TTL_SECONDS = 60
CACHE_STALE_TTL_SECONDS = 60 * 60
CACHE_LOCK_TTL_MS = 30_000
CACHE_WAIT_TIMEOUT_MS = 200
CACHE_COOLDOWN_TTL_SECONDS: tuple[int, int] = (5, 30)


RiskLevelValue: TypeAlias = Literal["unknown"] | int


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


@router.get("/rules", response_model=RiskRuleModel)
def get_risk_rules(
    request: Request,
    response: Response,
) -> Response | RiskRuleModel:
    try:
        payload = get_risk_rules_payload()
    except (FileNotFoundError, ValueError) as exc:
        logger.error("risk_rules_config_error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc

    headers = {
        "Cache-Control": "public, max-age=0, must-revalidate",
        "ETag": payload.etag,
    }

    if if_none_match_matches(request.headers.get("if-none-match"), payload.etag):
        return Response(status_code=304, headers=headers)

    response.headers.update(headers)
    return payload.model


class RiskRulesEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snowfall: float
    snow_depth: float
    wind: float
    temp: float


@router.post("/rules/evaluate", response_model=RiskEvaluationResult)
def evaluate_risk_rules(
    payload: RiskRulesEvaluateRequest,
    response: Response,
) -> RiskEvaluationResult:
    try:
        rules_payload = get_risk_rules_payload()
    except (FileNotFoundError, ValueError) as exc:
        logger.error("risk_rules_config_error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc

    try:
        result = rules_payload.model.evaluate(
            {
                "snowfall": payload.snowfall,
                "snow_depth": payload.snow_depth,
                "wind": payload.wind,
                "temp": payload.temp,
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response.headers["X-Risk-Rules-Etag"] = rules_payload.etag
    return result


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

    if not all(map(math.isfinite, (min_lon, min_lat, max_lon, max_lat))):
        raise ValueError("bbox values must be finite numbers")

    if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
        raise ValueError("bbox lon must be between -180 and 180")
    if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
        raise ValueError("bbox lat must be between -90 and 90")

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
    risk_level: RiskLevelValue = Field(
        default="unknown",
        description="Risk level (1-5) when evaluated, otherwise 'unknown'",
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
    product_id: int | None = None,
    valid_time: datetime | None = None,
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
            risk_levels: dict[int, int] = {}
            if product_id is not None and valid_time is not None:
                poi_ids = [int(item.id) for item in pois]
                if poi_ids:
                    levels_stmt = (
                        select(RiskPOIEvaluation.poi_id, RiskPOIEvaluation.risk_level)
                        .where(
                            RiskPOIEvaluation.poi_id.in_(poi_ids),
                            RiskPOIEvaluation.product_id == int(product_id),
                            RiskPOIEvaluation.valid_time == _normalize_time(valid_time),
                        )
                        .order_by(RiskPOIEvaluation.poi_id)
                    )
                    risk_levels = {
                        int(poi_id): int(level)
                        for poi_id, level in session.execute(levels_stmt).all()
                    }
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
            risk_level=risk_levels.get(int(item.id), "unknown")
            if product_id is not None and valid_time is not None
            else "unknown",
        )
        for item in pois
    ]
    return RiskPOIQueryResponse(
        page=page, page_size=page_size, total=total, items=items
    )


RISK_POI_MAX_ZOOM = 22
RISK_POI_CLUSTER_GRID_SIZE_PX = 64
RISK_POI_UNCLUSTER_ZOOM = 14
RISK_POI_MAX_MERCATOR_LAT = 85.05112878


class RiskPOIClusterItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lon: float
    lat: float
    count: int = Field(ge=1)
    poi_ids: list[int] = Field(default_factory=list)


class RiskPOIClusterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clusters: list[RiskPOIClusterItemResponse] = Field(default_factory=list)


def _query_risk_poi_points(
    *,
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
) -> list[tuple[int, float, float]]:
    stmt = (
        select(RiskPOI.id, RiskPOI.lon, RiskPOI.lat)
        .where(
            RiskPOI.lon >= min_lon,
            RiskPOI.lon <= max_lon,
            RiskPOI.lat >= min_lat,
            RiskPOI.lat <= max_lat,
        )
        .order_by(RiskPOI.id)
    )
    try:
        with Session(db.get_engine()) as session:
            rows = session.execute(stmt).all()
    except SQLAlchemyError as exc:
        logger.error("risk_pois_db_error", extra={"error": str(exc)})
        raise HTTPException(
            status_code=503, detail="Risk POI database unavailable"
        ) from exc

    return [(int(poi_id), float(lon), float(lat)) for poi_id, lon, lat in rows]


def _mercator_normalized(lon: float, lat: float) -> tuple[float, float]:
    lat = max(min(lat, RISK_POI_MAX_MERCATOR_LAT), -RISK_POI_MAX_MERCATOR_LAT)
    x = (lon + 180.0) / 360.0

    lat_rad = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0

    epsilon = 1e-12
    x = min(max(x, 0.0), 1.0 - epsilon)
    y = min(max(y, 0.0), 1.0 - epsilon)
    return x, y


def _cluster_risk_poi_points(
    points: list[tuple[int, float, float]],
    *,
    zoom: int,
) -> list[RiskPOIClusterItemResponse]:
    if not points:
        return []

    if zoom >= RISK_POI_UNCLUSTER_ZOOM:
        return [
            RiskPOIClusterItemResponse(
                lon=float(lon),
                lat=float(lat),
                count=1,
                poi_ids=[int(poi_id)],
            )
            for poi_id, lon, lat in points
        ]

    class _Bucket(TypedDict):
        count: int
        sum_lon: float
        sum_lat: float
        poi_ids: list[int]

    world_px = 256 * (2**zoom)
    cell_size = float(RISK_POI_CLUSTER_GRID_SIZE_PX) / float(world_px)
    buckets: dict[tuple[int, int], _Bucket] = {}

    for poi_id, lon, lat in points:
        x, y = _mercator_normalized(lon, lat)
        cell_x = int(x / cell_size)
        cell_y = int(y / cell_size)
        key = (cell_x, cell_y)

        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "count": 0,
                "sum_lon": 0.0,
                "sum_lat": 0.0,
                "poi_ids": [],
            }
            buckets[key] = bucket

        bucket["count"] += 1
        bucket["sum_lon"] += float(lon)
        bucket["sum_lat"] += float(lat)
        bucket["poi_ids"].append(int(poi_id))

    clusters: list[RiskPOIClusterItemResponse] = []
    for bucket in buckets.values():
        count = bucket["count"]
        sum_lon = bucket["sum_lon"]
        sum_lat = bucket["sum_lat"]
        poi_ids = sorted(bucket["poi_ids"])
        clusters.append(
            RiskPOIClusterItemResponse(
                lon=sum_lon / count,
                lat=sum_lat / count,
                count=count,
                poi_ids=poi_ids,
            )
        )

    clusters.sort(
        key=lambda item: (
            -int(item.count),
            float(item.lon),
            float(item.lat),
            int(item.poi_ids[0]) if item.poi_ids else 0,
        )
    )
    return clusters


@router.get("/pois", response_model=RiskPOIQueryResponse)
async def get_risk_pois(
    request: Request,
    bbox: str = Query(description="Bounding box: min_lon,min_lat,max_lon,max_lat"),
    page: int = Query(default=1, ge=1, le=1000),
    page_size: int = Query(default=100, ge=1, le=1000),
    product_id: int | None = Query(
        default=None, gt=0, description="Product id for risk evaluation lookup"
    ),
    valid_time: datetime | None = Query(
        default=None, description="Valid time (ISO8601) for risk evaluation lookup"
    ),
) -> Response:
    try:
        min_lon, min_lat, max_lon, max_lat = _parse_bbox(bbox)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if (product_id is None) != (valid_time is None):
        raise HTTPException(
            status_code=400, detail="product_id and valid_time must be provided together"
        )

    valid_dt = _normalize_time(valid_time) if valid_time is not None else None

    redis: RedisLike | None = getattr(request.app.state, "redis_client", None)

    async def _compute() -> bytes:
        def _sync() -> bytes:
            payload = _query_risk_pois(
                min_lon=min_lon,
                min_lat=min_lat,
                max_lon=max_lon,
                max_lat=max_lat,
                page=page,
                page_size=page_size,
                product_id=product_id,
                valid_time=valid_dt,
            )
            return payload.model_dump_json().encode("utf-8")

        return await to_thread(_sync)

    if redis is None:
        body = await _compute()
    else:
        product_key = str(int(product_id)) if product_id is not None else "none"
        time_key = (
            valid_dt.strftime("%Y%m%dT%H%M%SZ") if valid_dt is not None else "none"
        )
        identity = (
            f"{min_lon!r},{min_lat!r},{max_lon!r},{max_lat!r}"
            f":page={page}:size={page_size}:product={product_key}:time={time_key}"
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
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("risk_pois_cache_unavailable", extra={"error": str(exc)})
            body = await _compute()

    etag = f'"sha256-{hashlib.sha256(body).hexdigest()}"'
    headers = {"Cache-Control": CACHE_CONTROL_HEADER, "ETag": etag}

    if if_none_match_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)

    return Response(content=body, media_type="application/json", headers=headers)


@router.get("/pois/cluster", response_model=RiskPOIClusterResponse)
async def get_risk_poi_clusters(
    request: Request,
    bbox: str = Query(description="Bounding box: min_lon,min_lat,max_lon,max_lat"),
    zoom: int = Query(ge=0, le=RISK_POI_MAX_ZOOM, description="Map zoom level"),
) -> Response:
    try:
        min_lon, min_lat, max_lon, max_lat = _parse_bbox(bbox)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    redis: RedisLike | None = getattr(request.app.state, "redis_client", None)

    async def _compute() -> bytes:
        def _sync() -> bytes:
            points = _query_risk_poi_points(
                min_lon=min_lon,
                min_lat=min_lat,
                max_lon=max_lon,
                max_lat=max_lat,
            )
            clusters = _cluster_risk_poi_points(points, zoom=int(zoom))
            payload = RiskPOIClusterResponse(clusters=clusters)
            return payload.model_dump_json().encode("utf-8")

        return await to_thread(_sync)

    if redis is None:
        body = await _compute()
    else:
        identity = f"{min_lon!r},{min_lat!r},{max_lon!r},{max_lat!r}:zoom={zoom}"
        fresh_key = f"risk:pois:cluster:fresh:{identity}"
        stale_key = f"risk:pois:cluster:stale:{identity}"
        lock_key = f"risk:pois:cluster:lock:{identity}"

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
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("risk_pois_cache_unavailable", extra={"error": str(exc)})
            body = await _compute()

    etag = f'"sha256-{hashlib.sha256(body).hexdigest()}"'
    headers = {"Cache-Control": CACHE_CONTROL_HEADER, "ETag": etag}

    if if_none_match_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)

    return Response(content=body, media_type="application/json", headers=headers)


class RiskEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(gt=0, description="Product id")
    valid_time: datetime = Field(description="Valid time (ISO8601)")
    bbox: tuple[float, float, float, float] | None = Field(
        default=None,
        description="Bounding box [min_lon,min_lat,max_lon,max_lat]; defaults to product hazards at valid_time",
    )
    poi_ids: list[int] | None = Field(
        default=None,
        description="Optional POI ids to evaluate (filtered within bbox when provided)",
    )


class RiskEvaluateSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    level_counts: dict[str, int] = Field(default_factory=dict)
    reasons: dict[str, int] = Field(
        default_factory=dict,
        description="Summary of dominant risk factors across evaluated POIs",
    )
    max_level: int | None = None
    avg_score: float | None = None
    duration_ms: float


class RiskEvaluateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[POIRiskResult] = Field(default_factory=list)
    summary: RiskEvaluateSummary


def _normalize_time(value: datetime) -> datetime:
    parsed = value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolve_reasons_locale(request: Request) -> str:
    header = (request.headers.get("accept-language") or "").strip().lower()
    primary = header.split(",", 1)[0].strip()
    if primary.startswith("zh"):
        return "zh"
    if primary.startswith("en"):
        return "en"
    return "en"


def _summarize_results(
    results: list[POIRiskResult],
    *,
    duration_ms: float,
) -> RiskEvaluateSummary:
    total = len(results)
    level_counts: dict[str, int] = {}
    reasons: dict[str, int] = {}
    scores: list[float] = []

    for item in results:
        level_key = str(int(item.level))
        level_counts[level_key] = level_counts.get(level_key, 0) + 1
        top_factor_id: str | None = None
        top_contribution: float | None = None
        for factor in item.factors:
            contribution = float(factor.contribution)
            factor_id = str(factor.id.value)
            if top_factor_id is None:
                top_factor_id = factor_id
                top_contribution = contribution
                continue

            assert top_contribution is not None
            if contribution > top_contribution:
                top_factor_id = factor_id
                top_contribution = contribution
            elif contribution == top_contribution and factor_id < top_factor_id:
                top_factor_id = factor_id
        scores.append(float(item.score))

        if top_factor_id is not None:
            reasons[top_factor_id] = reasons.get(top_factor_id, 0) + 1

    max_level = max((item.level for item in results), default=None)
    avg_score = None
    if scores:
        avg_score = float(sum(scores) / len(scores))

    return RiskEvaluateSummary(
        total=total,
        level_counts=level_counts,
        reasons=reasons,
        max_level=max_level,
        avg_score=avg_score,
        duration_ms=float(duration_ms),
    )


def _poi_ids_cache_identity(poi_ids: list[int] | None) -> str | list[int]:
    if poi_ids is None:
        return "all"
    ids = sorted({int(item) for item in poi_ids if int(item) > 0})
    if not ids:
        return "empty"
    return ids


@router.post("/evaluate", response_model=RiskEvaluateResponse)
async def evaluate_risk(
    request: Request,
    payload: RiskEvaluateRequest,
) -> Response:
    try:
        rules_payload = get_risk_rules_payload()
    except (FileNotFoundError, ValueError) as exc:
        logger.error("risk_rules_config_error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc

    valid_dt = _normalize_time(payload.valid_time)
    locale = _resolve_reasons_locale(request)

    identity_payload = {
        "product_id": int(payload.product_id),
        "valid_time": valid_dt.strftime("%Y%m%dT%H%M%SZ"),
        "bbox": list(payload.bbox) if payload.bbox is not None else None,
        "poi_ids": _poi_ids_cache_identity(payload.poi_ids),
        "rules_etag": rules_payload.etag,
        "reasons_locale": locale,
    }
    identity = json.dumps(identity_payload, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()

    redis: RedisLike | None = getattr(request.app.state, "redis_client", None)

    async def _compute() -> bytes:
        def _sync() -> bytes:
            started = time.perf_counter()
            engine = RiskEvaluationEngine()
            results = engine.evaluate_pois(
                product_id=int(payload.product_id),
                valid_time=valid_dt,
                bbox=payload.bbox,
                poi_ids=payload.poi_ids,
                locale=locale,
            )

            try:
                with Session(db.get_engine()) as session:
                    rows = [
                        {
                            "poi_id": int(item.poi_id),
                            "product_id": int(payload.product_id),
                            "valid_time": valid_dt,
                            "risk_level": int(item.level),
                        }
                        for item in results
                    ]
                    if rows:
                        dialect = session.bind.dialect.name if session.bind else ""
                        if dialect == "postgresql":
                            from sqlalchemy.dialects.postgresql import (
                                insert as dialect_insert,
                            )
                        else:
                            from sqlalchemy.dialects.sqlite import insert as dialect_insert

                        stmt = dialect_insert(RiskPOIEvaluation).values(rows)
                        stmt = stmt.on_conflict_do_update(
                            index_elements=[
                                RiskPOIEvaluation.poi_id,
                                RiskPOIEvaluation.product_id,
                                RiskPOIEvaluation.valid_time,
                            ],
                            set_={
                                "risk_level": stmt.excluded.risk_level,
                                "evaluated_at": func.now(),
                            },
                        )
                        session.execute(stmt)
                        session.commit()
            except SQLAlchemyError as exc:
                logger.warning(
                    "risk_poi_evaluations_write_failed",
                    extra={"error": str(exc)},
                )

            duration_ms = (time.perf_counter() - started) * 1000.0
            response_payload = RiskEvaluateResponse(
                results=results,
                summary=_summarize_results(results, duration_ms=duration_ms),
            )
            return response_payload.model_dump_json().encode("utf-8")

        return await to_thread(_sync)

    if redis is None:
        try:
            body = await _compute()
        except RiskEngineInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RiskEngineNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RiskEngineDatabaseError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    else:
        fresh_key = f"risk:evaluate:fresh:{digest}"
        stale_key = f"risk:evaluate:stale:{digest}"
        lock_key = f"risk:evaluate:lock:{digest}"
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
            if result.status == "fresh":
                logger.info(
                    "risk_evaluate_cache_hit",
                    extra={
                        "cache_key": digest,
                        "product_id": int(payload.product_id),
                        "valid_time": identity_payload["valid_time"],
                    },
                )
            body = result.body
        except TimeoutError as exc:
            raise HTTPException(
                status_code=503, detail="Risk evaluation cache warming timed out"
            ) from exc
        except RiskEngineInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RiskEngineNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RiskEngineDatabaseError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("risk_evaluate_cache_unavailable", extra={"error": str(exc)})
            try:
                body = await _compute()
            except RiskEngineInputError as exc2:
                raise HTTPException(status_code=400, detail=str(exc2)) from exc2
            except RiskEngineNotFoundError as exc2:
                raise HTTPException(status_code=404, detail=str(exc2)) from exc2
            except RiskEngineDatabaseError as exc2:
                raise HTTPException(status_code=503, detail=str(exc2)) from exc2

    etag = f'"sha256-{hashlib.sha256(body).hexdigest()}"'
    headers = {
        "Cache-Control": CACHE_CONTROL_HEADER,
        "ETag": etag,
        "X-Risk-Rules-Etag": rules_payload.etag,
    }
    if if_none_match_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)
