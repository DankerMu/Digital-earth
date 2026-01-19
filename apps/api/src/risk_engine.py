from __future__ import annotations

import hashlib
import math
import os
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy import false, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import db
from models import Product, ProductHazard, RiskPOI
from risk.rules import (
    RiskFactorEvaluation,
    RiskFactorId,
    RiskFactorRule,
    RiskRuleModel,
    ThresholdDirection,
)
from risk_rules_config import get_risk_rules_payload

BBox = tuple[float, float, float, float]

__all__ = [
    "BBox",
    "POIRiskReason",
    "POIRiskResult",
    "RiskEngineDatabaseError",
    "RiskEngineInputError",
    "RiskEngineNotFoundError",
    "RiskEvaluationEngine",
    "WeatherSampler",
]

_FACTOR_NAME_TRANSLATIONS: dict[str, dict[RiskFactorId, str]] = {
    "en": {
        RiskFactorId.snowfall: "Snowfall",
        RiskFactorId.snow_depth: "Snow depth",
        RiskFactorId.wind: "Wind",
        RiskFactorId.temp: "Temperature",
    },
    "zh": {
        RiskFactorId.snowfall: "降雪量",
        RiskFactorId.snow_depth: "积雪深度",
        RiskFactorId.wind: "风速",
        RiskFactorId.temp: "气温",
    },
}

_DEFAULT_FACTOR_NAMES = _FACTOR_NAME_TRANSLATIONS["en"]


def _factor_name(factor_id: RiskFactorId, *, locale: str | None) -> str:
    language = (locale or "").strip().lower()
    if language in _FACTOR_NAME_TRANSLATIONS:
        return _FACTOR_NAME_TRANSLATIONS[language].get(
            factor_id, _DEFAULT_FACTOR_NAMES.get(factor_id, factor_id.value)
        )
    if language.startswith("zh"):
        return _FACTOR_NAME_TRANSLATIONS["zh"].get(
            factor_id, _DEFAULT_FACTOR_NAMES.get(factor_id, factor_id.value)
        )
    return _DEFAULT_FACTOR_NAMES.get(factor_id, factor_id.value)


def _selected_threshold(rule: RiskFactorRule, value: float) -> float:
    numeric = float(value)
    thresholds = rule.thresholds
    selected = float(thresholds[0].threshold)

    if rule.direction == ThresholdDirection.ascending:
        for item in thresholds[1:]:
            if numeric >= float(item.threshold):
                selected = float(item.threshold)
            else:
                break
    else:
        for item in thresholds[1:]:
            if numeric <= float(item.threshold):
                selected = float(item.threshold)
            else:
                break

    return selected


class POIRiskReason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor_id: RiskFactorId
    factor_name: str
    value: float
    threshold: float
    contribution: float


class RiskEngineInputError(ValueError):
    pass


class RiskEngineNotFoundError(LookupError):
    pass


class RiskEngineDatabaseError(RuntimeError):
    pass


def _normalize_time(value: datetime) -> datetime:
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _validate_bbox(value: BBox) -> BBox:
    min_lon, min_lat, max_lon, max_lat = (float(item) for item in value)

    if not all(map(math.isfinite, (min_lon, min_lat, max_lon, max_lat))):
        raise RiskEngineInputError("bbox values must be finite numbers")

    if not (-180.0 <= min_lon <= 180.0 and -180.0 <= max_lon <= 180.0):
        raise RiskEngineInputError("bbox lon must be between -180 and 180")
    if not (-90.0 <= min_lat <= 90.0 and -90.0 <= max_lat <= 90.0):
        raise RiskEngineInputError("bbox lat must be between -90 and 90")

    if min_lon > max_lon:
        raise RiskEngineInputError("bbox min_lon must be <= max_lon")
    if min_lat > max_lat:
        raise RiskEngineInputError("bbox min_lat must be <= max_lat")

    return min_lon, min_lat, max_lon, max_lat


def _chunked(
    items: Sequence[RiskPOI], *, batch_size: int
) -> Iterable[Sequence[RiskPOI]]:
    if batch_size <= 0:
        raise RiskEngineInputError("batch_size must be > 0")
    for offset in range(0, len(items), batch_size):
        yield items[offset : offset + batch_size]


class WeatherSampler(Protocol):
    def sample(
        self,
        *,
        product_id: int,
        valid_time: datetime,
        pois: Sequence[RiskPOI],
    ) -> Mapping[int, Mapping[str | RiskFactorId, float] | None]:
        raise NotImplementedError


@dataclass(frozen=True)
class _MockWeatherSampler:
    def _hash_to_unit(self, payload: str) -> float:
        digest = hashlib.sha256(payload.encode("utf-8")).digest()
        value = int.from_bytes(digest[:8], "big")
        return value / float(2**64 - 1)

    def _value(self, *, key: str, lo: float, hi: float) -> float:
        unit = self._hash_to_unit(key)
        return float(lo + unit * (hi - lo))

    def sample(
        self,
        *,
        product_id: int,
        valid_time: datetime,
        pois: Sequence[RiskPOI],
    ) -> Mapping[int, Mapping[str | RiskFactorId, float]]:
        dt = _normalize_time(valid_time).strftime("%Y%m%dT%H%M%SZ")
        out: dict[int, dict[str, float]] = {}
        for poi in pois:
            base = f"product={product_id}:time={dt}:poi={poi.id}:lon={poi.lon:.6f}:lat={poi.lat:.6f}"
            out[int(poi.id)] = {
                "snowfall": self._value(key=f"{base}:snowfall", lo=0.0, hi=20.0),
                "snow_depth": self._value(key=f"{base}:snow_depth", lo=0.0, hi=100.0),
                "wind": self._value(key=f"{base}:wind", lo=0.0, hi=30.0),
                "temp": self._value(key=f"{base}:temp", lo=-30.0, hi=10.0),
            }
        return out


class POIRiskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    poi_id: int
    level: int
    score: float
    factors: tuple[RiskFactorEvaluation, ...]
    reasons: tuple[POIRiskReason, ...]


class RiskEvaluationEngine:
    def __init__(
        self,
        *,
        sampler: WeatherSampler | None = None,
        batch_size: int = 256,
        max_workers: int | None = None,
    ) -> None:
        self._sampler = sampler or _MockWeatherSampler()
        self._batch_size = int(batch_size)
        resolved_max_workers = (
            int(max_workers) if max_workers is not None else int(os.cpu_count() or 1)
        )
        if resolved_max_workers <= 0:
            raise RiskEngineInputError("max_workers must be > 0")
        self._max_workers = resolved_max_workers

    def evaluate_pois(
        self,
        *,
        product_id: int,
        valid_time: datetime,
        bbox: BBox | None = None,
        poi_ids: Sequence[int] | None = None,
        locale: str | None = None,
    ) -> list[POIRiskResult]:
        dt = _normalize_time(valid_time)
        requested_bbox = _validate_bbox(bbox) if bbox is not None else None
        rules_payload = get_risk_rules_payload()

        try:
            with Session(db.get_engine()) as session:
                product = session.get(Product, int(product_id))
                if product is None:
                    raise RiskEngineNotFoundError(f"Product not found: {product_id}")

                effective_bbox = requested_bbox
                if effective_bbox is None:
                    effective_bbox = _resolve_product_bbox(
                        session, product_id=int(product_id), valid_time=dt
                    )

                pois = _query_pois(
                    session,
                    bbox=effective_bbox,
                    poi_ids=poi_ids,
                )
        except RiskEngineNotFoundError:
            raise
        except SQLAlchemyError as exc:
            raise RiskEngineDatabaseError("Database unavailable") from exc

        return _evaluate_pois(
            rules=rules_payload.model,
            sampler=self._sampler,
            product_id=int(product_id),
            valid_time=dt,
            pois=pois,
            batch_size=self._batch_size,
            max_workers=self._max_workers,
            locale=locale,
        )


def _resolve_product_bbox(
    session: Session,
    *,
    product_id: int,
    valid_time: datetime,
) -> BBox:
    dt = _normalize_time(valid_time)
    stmt = (
        select(
            ProductHazard.bbox_min_x,
            ProductHazard.bbox_min_y,
            ProductHazard.bbox_max_x,
            ProductHazard.bbox_max_y,
        )
        .where(
            ProductHazard.product_id == int(product_id),
            ProductHazard.valid_from <= dt,
            ProductHazard.valid_to >= dt,
        )
        .order_by(ProductHazard.id)
    )
    rows = session.execute(stmt).all()
    if not rows:
        raise RiskEngineNotFoundError(
            f"No hazards found for product={product_id} at valid_time={dt.isoformat()}"
        )

    mins_x, mins_y, maxs_x, maxs_y = zip(*rows)
    bbox: BBox = (
        float(min(mins_x)),
        float(min(mins_y)),
        float(max(maxs_x)),
        float(max(maxs_y)),
    )
    return _validate_bbox(bbox)


def _query_pois(
    session: Session,
    *,
    bbox: BBox,
    poi_ids: Sequence[int] | None,
) -> list[RiskPOI]:
    min_lon, min_lat, max_lon, max_lat = bbox
    stmt = select(RiskPOI).where(
        RiskPOI.lon >= float(min_lon),
        RiskPOI.lon <= float(max_lon),
        RiskPOI.lat >= float(min_lat),
        RiskPOI.lat <= float(max_lat),
    )

    if poi_ids is not None:
        ids = [int(item) for item in poi_ids if int(item) > 0]
        if ids:
            stmt = stmt.where(RiskPOI.id.in_(ids))
        else:
            stmt = stmt.where(false())

    stmt = stmt.order_by(RiskPOI.id)
    return list(session.scalars(stmt).all())


def _evaluate_pois(
    *,
    rules: RiskRuleModel,
    sampler: WeatherSampler,
    product_id: int,
    valid_time: datetime,
    pois: Sequence[RiskPOI],
    batch_size: int,
    max_workers: int,
    locale: str | None,
) -> list[POIRiskResult]:
    results: list[POIRiskResult] = []
    rule_lookup: dict[RiskFactorId, RiskFactorRule] = {
        factor.id: factor for factor in rules.factors
    }
    factor_order: dict[RiskFactorId, int] = {
        factor_id: idx for idx, factor_id in enumerate(RiskFactorId)
    }

    if max_workers <= 0:
        raise RiskEngineInputError("max_workers must be > 0")

    def _evaluate_one(
        payload: tuple[int, Mapping[str | RiskFactorId, float]],
    ) -> POIRiskResult:
        poi_id, raw_values = payload
        try:
            evaluation = rules.evaluate(raw_values)
        except ValueError as exc:
            raise RiskEngineInputError(str(exc)) from exc

        reasons = [
            POIRiskReason(
                factor_id=factor.id,
                factor_name=_factor_name(factor.id, locale=locale),
                value=float(factor.value),
                threshold=_selected_threshold(rule_lookup[factor.id], factor.value),
                contribution=float(factor.contribution),
            )
            for factor in evaluation.factors
            if float(factor.contribution) > 0.0
        ]
        reasons.sort(
            key=lambda item: (-float(item.contribution), factor_order[item.factor_id])
        )
        return POIRiskResult(
            poi_id=poi_id,
            level=int(evaluation.level),
            score=float(evaluation.score),
            factors=tuple(evaluation.factors),
            reasons=tuple(reasons),
        )

    owns_executor = max_workers > 1
    executor = ThreadPoolExecutor(max_workers=max_workers) if owns_executor else None

    try:
        for batch in _chunked(list(pois), batch_size=batch_size):
            samples = sampler.sample(
                product_id=int(product_id), valid_time=valid_time, pois=batch
            )

            payloads: list[tuple[int, Mapping[str | RiskFactorId, float]]] = []
            for poi in batch:
                raw_values = samples.get(int(poi.id))
                if raw_values is None:
                    continue
                payloads.append((int(poi.id), raw_values))

            if not payloads:
                continue

            if executor is None or len(payloads) == 1:
                results.extend(_evaluate_one(item) for item in payloads)
            else:
                results.extend(executor.map(_evaluate_one, payloads, timeout=None))
    finally:
        if executor is not None:
            executor.shutdown(wait=True)

    return results
