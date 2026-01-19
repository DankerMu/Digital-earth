from __future__ import annotations

import hashlib
import logging
import math
import os
import time
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy import false, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import db
from models import Product, ProductHazard, RiskPOI
from risk.rules import RiskFactorId, RiskFactorEvaluation, RiskRuleModel
from risk_rules_config import get_risk_rules_payload

BBox = tuple[float, float, float, float]

__all__ = [
    "BBox",
    "POIRiskResult",
    "RiskEngineDatabaseError",
    "RiskEngineInputError",
    "RiskEngineNotFoundError",
    "RiskEvaluationEngine",
    "WeatherSampler",
]

BATCH_EVAL_CHUNK_SIZE_ENV = "DIGITAL_EARTH_RISK_EVAL_CHUNK_SIZE"
MAX_WORKERS_ENV = "DIGITAL_EARTH_RISK_EVAL_MAX_WORKERS"

DEFAULT_BATCH_SIZE = 1024
DEFAULT_EVAL_CHUNK_SIZE = 512
DEFAULT_MAX_WORKERS_CAP = 8

logger = logging.getLogger("api.request")


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


def _resolve_max_workers(value: int | None) -> int:
    if value is not None:
        return max(1, int(value))

    env_value = os.environ.get(MAX_WORKERS_ENV)
    if env_value:
        try:
            parsed = int(env_value.strip())
        except ValueError:
            parsed = 0
        if parsed > 0:
            return parsed

    cpu = os.cpu_count() or 1
    return max(1, min(int(cpu), DEFAULT_MAX_WORKERS_CAP))


def _resolve_eval_chunk_size() -> int:
    env_value = os.environ.get(BATCH_EVAL_CHUNK_SIZE_ENV)
    if env_value:
        try:
            parsed = int(env_value.strip())
        except ValueError:
            parsed = 0
        if parsed > 0:
            return parsed
    return DEFAULT_EVAL_CHUNK_SIZE


class PreparedWeatherSampler(Protocol):
    def sample(
        self,
        *,
        pois: Sequence[RiskPOI],
    ) -> Mapping[int, Mapping[str | RiskFactorId, float]]:
        raise NotImplementedError


class WeatherSampler(Protocol):
    def sample(
        self,
        *,
        product_id: int,
        valid_time: datetime,
        pois: Sequence[RiskPOI],
    ) -> Mapping[int, Mapping[str | RiskFactorId, float]]:
        raise NotImplementedError


@dataclass(frozen=True)
class _MockWeatherSampler:
    def prepare(
        self,
        *,
        product_id: int,
        valid_time: datetime,
    ) -> PreparedWeatherSampler:
        dt = _normalize_time(valid_time)

        @dataclass(frozen=True)
        class _Prepared:
            product_id: int
            valid_time: datetime
            sampler: "_MockWeatherSampler"

            def sample(
                self, *, pois: Sequence[RiskPOI]
            ) -> Mapping[int, Mapping[str | RiskFactorId, float]]:
                return self.sampler.sample(
                    product_id=int(self.product_id),
                    valid_time=self.valid_time,
                    pois=pois,
                )

        return _Prepared(product_id=int(product_id), valid_time=dt, sampler=self)

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


class RiskEvaluationEngine:
    def __init__(
        self,
        *,
        sampler: WeatherSampler | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_workers: int | None = None,
        parallel: bool = True,
    ) -> None:
        self._sampler = sampler or _MockWeatherSampler()
        self._batch_size = int(batch_size)
        self._max_workers = max_workers
        self._parallel = bool(parallel)

    def evaluate_pois(
        self,
        *,
        product_id: int,
        valid_time: datetime,
        bbox: BBox | None = None,
        poi_ids: Sequence[int] | None = None,
        max_workers: int | None = None,
        parallel: bool | None = None,
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

        effective_parallel = self._parallel if parallel is None else bool(parallel)
        resolved_workers = _resolve_max_workers(
            self._max_workers if max_workers is None else max_workers
        )
        started = time.perf_counter()
        return _evaluate_pois(
            rules=rules_payload.model,
            sampler=self._sampler,
            product_id=int(product_id),
            valid_time=dt,
            pois=pois,
            batch_size=self._batch_size,
            max_workers=resolved_workers,
            parallel=effective_parallel,
            started=started,
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
    parallel: bool,
    started: float,
) -> list[POIRiskResult]:
    if batch_size <= 0:
        raise RiskEngineInputError("batch_size must be > 0")

    poi_list = list(pois)
    if not poi_list:
        return []

    prepared: PreparedWeatherSampler | None = None
    prepare = getattr(sampler, "prepare", None)
    if callable(prepare):
        try:
            prepared = prepare(product_id=int(product_id), valid_time=valid_time)
        except TypeError:
            prepared = None

    def _sample(
        batch: Sequence[RiskPOI],
    ) -> Mapping[int, Mapping[str | RiskFactorId, float]]:
        if prepared is not None:
            return prepared.sample(pois=batch)
        return sampler.sample(
            product_id=int(product_id),
            valid_time=valid_time,
            pois=batch,
        )

    def _evaluate_batch(
        batch: Sequence[RiskPOI],
        samples: Mapping[int, Mapping[str | RiskFactorId, float]],
    ) -> list[POIRiskResult]:
        out: list[POIRiskResult] = []
        for poi in batch:
            raw_values = samples.get(int(poi.id))
            if raw_values is None:
                raise RiskEngineInputError(f"Missing weather sample for poi={poi.id}")
            try:
                evaluation = rules.evaluate(raw_values)
            except ValueError as exc:
                raise RiskEngineInputError(str(exc)) from exc

            out.append(
                POIRiskResult.model_construct(
                    poi_id=int(poi.id),
                    level=int(evaluation.level),
                    score=float(evaluation.score),
                    factors=tuple(evaluation.factors),
                )
            )
        return out

    batch_sizes: list[int] = []

    if not parallel or max_workers <= 1 or len(poi_list) <= 1:
        results: list[POIRiskResult] = []
        for batch in _chunked(poi_list, batch_size=batch_size):
            batch_sizes.append(len(batch))
            samples = _sample(batch)
            results.extend(_evaluate_batch(batch, samples))

        duration_ms = (time.perf_counter() - started) * 1000.0
        logger.info(
            "risk_engine.evaluate.completed",
            extra={
                "mode": "serial",
                "sampler_prepared": prepared is not None,
                "total_pois": len(poi_list),
                "batch_size": int(batch_size),
                "batches": len(batch_sizes),
                "eval_tasks": len(batch_sizes),
                "duration_ms": round(duration_ms, 3),
            },
        )
        return results

    eval_chunk_size = _resolve_eval_chunk_size()
    max_in_flight = max(2, int(max_workers) * 4)

    results: list[POIRiskResult | None] = [None] * len(poi_list)
    futures: dict[Future[list[POIRiskResult]], tuple[int, int]] = {}
    eval_tasks = 0

    sampling_batches = (len(poi_list) + batch_size - 1) // batch_size
    split_eval_chunks = sampling_batches < max_workers

    def _drain_completed(*, return_when: str) -> None:
        if not futures:
            return
        done, _pending = wait(futures.keys(), return_when=return_when)
        for future in done:
            start_index, expected_len = futures.pop(future)
            chunk_results = future.result()
            if len(chunk_results) != expected_len:
                raise RuntimeError("Unexpected risk evaluation chunk size")
            results[start_index : start_index + expected_len] = chunk_results

    try:
        with ThreadPoolExecutor(max_workers=int(max_workers)) as executor:
            for batch_start in range(0, len(poi_list), batch_size):
                batch = poi_list[batch_start : batch_start + batch_size]
                batch_sizes.append(len(batch))
                samples = _sample(batch)

                chunk_size = len(batch)
                if split_eval_chunks and len(batch) > eval_chunk_size:
                    chunk_size = min(int(eval_chunk_size), len(batch))

                for chunk_start in range(0, len(batch), chunk_size):
                    chunk = batch[chunk_start : chunk_start + chunk_size]
                    start_index = batch_start + chunk_start
                    future = executor.submit(_evaluate_batch, chunk, samples)
                    futures[future] = (start_index, len(chunk))
                    eval_tasks += 1

                while len(futures) >= max_in_flight:
                    _drain_completed(return_when=FIRST_COMPLETED)

            while futures:
                _drain_completed(return_when=FIRST_COMPLETED)
    except Exception:
        for future in futures:
            future.cancel()
        raise

    finalized = [item for item in results if item is not None]
    if len(finalized) != len(poi_list):
        raise RuntimeError("Missing risk evaluation results")

    duration_ms = (time.perf_counter() - started) * 1000.0
    logger.info(
        "risk_engine.evaluate.completed",
        extra={
            "mode": "parallel",
            "sampler_prepared": prepared is not None,
            "total_pois": len(poi_list),
            "batch_size": int(batch_size),
            "batches": len(batch_sizes),
            "max_workers": int(max_workers),
            "eval_chunk_size": int(eval_chunk_size),
            "eval_tasks": int(eval_tasks),
            "split_eval_chunks": split_eval_chunks,
            "duration_ms": round(duration_ms, 3),
        },
    )

    return finalized
