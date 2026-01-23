from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from redis_fakes import FakeRedis
from risk.rules import RiskFactorId
from risk_engine import (
    RiskEngineDatabaseError,
    RiskEngineInputError,
    RiskEngineNotFoundError,
    RiskEvaluationEngine,
)


def _write_risk_rules_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(
        [
            "schema_version: 1",
            "",
            "factors:",
            "  - id: snowfall",
            "    weight: 1.0",
            "    direction: ascending",
            "    thresholds:",
            "      - threshold: 0",
            "        score: 0",
            "      - threshold: 10",
            "        score: 4",
            "",
            "  - id: snow_depth",
            "    weight: 1.0",
            "    direction: ascending",
            "    thresholds:",
            "      - threshold: 0",
            "        score: 0",
            "      - threshold: 1",
            "        score: 4",
            "",
            "  - id: wind",
            "    weight: 1.0",
            "    direction: ascending",
            "    thresholds:",
            "      - threshold: 0",
            "        score: 0",
            "      - threshold: 5",
            "        score: 4",
            "",
            "  - id: temp",
            "    weight: 1.0",
            "    direction: descending",
            "    thresholds:",
            "      - threshold: 5",
            "        score: 0",
            "      - threshold: 0",
            "        score: 4",
            "",
            "final_levels:",
            "  - min_score: 0",
            "    level: 1",
            "  - min_score: 1",
            "    level: 2",
            "  - min_score: 2",
            "    level: 3",
            "  - min_score: 3",
            "    level: 4",
            "  - min_score: 4",
            "    level: 5",
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")


def _write_risk_rules_config_all_positive(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(
        [
            "schema_version: 1",
            "",
            "factors:",
            "  - id: snowfall",
            "    weight: 1.0",
            "    direction: ascending",
            "    thresholds:",
            "      - threshold: 0",
            "        score: 1",
            "",
            "  - id: snow_depth",
            "    weight: 1.0",
            "    direction: ascending",
            "    thresholds:",
            "      - threshold: 0",
            "        score: 1",
            "",
            "  - id: wind",
            "    weight: 1.0",
            "    direction: ascending",
            "    thresholds:",
            "      - threshold: 0",
            "        score: 1",
            "",
            "  - id: temp",
            "    weight: 1.0",
            "    direction: descending",
            "    thresholds:",
            "      - threshold: 5",
            "        score: 1",
            "",
            "final_levels:",
            "  - min_score: 0",
            "    level: 1",
            "  - min_score: 1",
            "    level: 2",
            "  - min_score: 2",
            "    level: 3",
            "  - min_score: 3",
            "    level: 4",
            "  - min_score: 4",
            "    level: 5",
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")


def _write_risk_rules_config_intermediate_thresholds(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(
        [
            "schema_version: 1",
            "",
            "factors:",
            "  - id: snowfall",
            "    weight: 1.0",
            "    direction: ascending",
            "    thresholds:",
            "      - threshold: 0",
            "        score: 0",
            "      - threshold: 5",
            "        score: 1",
            "      - threshold: 10",
            "        score: 2",
            "",
            "  - id: snow_depth",
            "    weight: 1.0",
            "    direction: ascending",
            "    thresholds:",
            "      - threshold: 0",
            "        score: 0",
            "",
            "  - id: wind",
            "    weight: 1.0",
            "    direction: ascending",
            "    thresholds:",
            "      - threshold: 0",
            "        score: 0",
            "",
            "  - id: temp",
            "    weight: 1.0",
            "    direction: descending",
            "    thresholds:",
            "      - threshold: 5",
            "        score: 0",
            "      - threshold: 0",
            "        score: 1",
            "      - threshold: -10",
            "        score: 2",
            "",
            "final_levels:",
            "  - min_score: 0",
            "    level: 1",
            "  - min_score: 1",
            "    level: 2",
            "  - min_score: 2",
            "    level: 3",
            "  - min_score: 3",
            "    level: 4",
            "  - min_score: 4",
            "    level: 5",
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")


def _setup_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[str, int]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk_engine.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    from db import get_engine
    from models import Base, Product, ProductHazard, RiskPOI

    get_engine.cache_clear()
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    issued_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    valid_from = issued_at
    valid_to = issued_at + timedelta(hours=6)

    product = Product(
        title="seeded",
        text="seeded product",
        issued_at=issued_at,
        valid_from=valid_from,
        valid_to=valid_to,
        status="published",
    )
    hazard = ProductHazard(
        severity="high",
        valid_from=valid_from,
        valid_to=valid_to,
        bbox_min_x=0,
        bbox_min_y=0,
        bbox_max_x=0,
        bbox_max_y=0,
    )
    hazard.set_geometry_from_geojson(
        {
            "type": "Polygon",
            "coordinates": [
                [
                    [100.0, 10.0],
                    [101.0, 10.0],
                    [101.0, 11.0],
                    [100.0, 11.0],
                    [100.0, 10.0],
                ]
            ],
        }
    )
    product.hazards.append(hazard)

    with Session(engine) as session:
        session.add(product)
        session.flush()
        product_id = int(product.id)

        session.add_all(
            [
                RiskPOI(
                    name="poi-a",
                    poi_type="fire",
                    lon=100.1,
                    lat=10.1,
                    alt=None,
                    weight=1.0,
                    tags=None,
                ),
                RiskPOI(
                    name="poi-b",
                    poi_type="fire",
                    lon=100.2,
                    lat=10.2,
                    alt=None,
                    weight=1.0,
                    tags=None,
                ),
                RiskPOI(
                    name="poi-outside",
                    poi_type="fire",
                    lon=130.0,
                    lat=30.0,
                    alt=None,
                    weight=1.0,
                    tags=None,
                ),
            ]
        )
        session.commit()

    engine.dispose()
    return db_url, product_id


class _StaticSampler:
    def __init__(self, values: dict[int, dict[str, float]]) -> None:
        self._values = values

    def sample(self, *, product_id: int, valid_time: datetime, pois):  # type: ignore[no-untyped-def]
        return {int(poi.id): dict(self._values[int(poi.id)]) for poi in pois}


class _CountingSampler:
    def __init__(self) -> None:
        self.calls = 0
        self.batch_sizes: list[int] = []

    def sample(self, *, product_id: int, valid_time: datetime, pois):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.batch_sizes.append(len(pois))
        return {
            int(poi.id): {
                "snowfall": 0.0,
                "snow_depth": 0.0,
                "wind": 0.0,
                "temp": 5.0,
            }
            for poi in pois
        }


class _MissingSampleSampler:
    def sample(self, *, product_id: int, valid_time: datetime, pois):  # type: ignore[no-untyped-def]
        if not pois:
            return {}
        first = pois[0]
        return {
            int(first.id): {
                "snowfall": 0.0,
                "snow_depth": 0.0,
                "wind": 0.0,
                "temp": 5.0,
            }
        }


class _InvalidSampleSampler:
    def sample(self, *, product_id: int, valid_time: datetime, pois):  # type: ignore[no-untyped-def]
        return {int(poi.id): {"snowfall": 0.0} for poi in pois}


class _SkipAllSampler:
    def sample(self, *, product_id: int, valid_time: datetime, pois):  # type: ignore[no-untyped-def]
        return {}


def _make_risk_client(*, redis: FakeRedis | None = None) -> TestClient:
    from routers.risk import router as risk_router

    app = FastAPI()
    app.include_router(risk_router, prefix="/api/v1")
    if redis is not None:
        app.state.redis_client = redis
    return TestClient(app)


def test_risk_engine_evaluates_pois_with_mock_weather(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    sampler = _StaticSampler(
        {
            1: {"snowfall": 10, "snow_depth": 1, "wind": 5, "temp": 0},
            2: {"snowfall": 0, "snow_depth": 0, "wind": 0, "temp": 5},
        }
    )
    engine = RiskEvaluationEngine(sampler=sampler, batch_size=2)
    valid_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

    results = engine.evaluate_pois(
        product_id=product_id,
        valid_time=valid_time,
        bbox=None,
    )

    assert [item.poi_id for item in results] == [1, 2]
    assert results[0].level == 5
    assert results[0].score == pytest.approx(4.0)
    assert len(results[0].factors) == 4
    assert [item.factor_id for item in results[0].reasons] == [
        RiskFactorId.snowfall,
        RiskFactorId.snow_depth,
        RiskFactorId.wind,
        RiskFactorId.temp,
    ]
    assert results[0].reasons[0].factor_name == "Snowfall"
    assert results[0].reasons[0].value == pytest.approx(10.0)
    assert results[0].reasons[0].threshold == pytest.approx(10.0)
    assert results[0].reasons[0].contribution == pytest.approx(1.0)

    assert results[1].level == 1
    assert results[1].score == pytest.approx(0.0)
    assert results[1].reasons == ()


def test_risk_engine_batches_sampling_for_1000_pois(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from db import get_engine
    from models import Base, Product, ProductHazard, RiskPOI
    from risk_rules_config import get_risk_rules_payload

    get_engine.cache_clear()
    get_risk_rules_payload.cache_clear()

    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk_engine_many.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    issued_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    product = Product(
        title="seeded",
        text="seeded product",
        issued_at=issued_at,
        valid_from=issued_at,
        valid_to=issued_at + timedelta(hours=6),
        status="published",
    )
    hazard = ProductHazard(
        severity="high",
        valid_from=issued_at,
        valid_to=issued_at + timedelta(hours=6),
        bbox_min_x=0,
        bbox_min_y=0,
        bbox_max_x=0,
        bbox_max_y=0,
    )
    hazard.set_geometry_from_geojson(
        {
            "type": "Polygon",
            "coordinates": [
                [
                    [100.0, 10.0],
                    [110.0, 10.0],
                    [110.0, 20.0],
                    [100.0, 20.0],
                    [100.0, 10.0],
                ]
            ],
        }
    )
    product.hazards.append(hazard)

    with Session(engine) as session:
        session.add(product)
        session.flush()
        product_id = int(product.id)

        session.add_all(
            [
                RiskPOI(
                    name=f"poi-{idx}",
                    poi_type="fire",
                    lon=100.0 + (idx % 100) * 0.01,
                    lat=10.0 + (idx // 100) * 0.01,
                    alt=None,
                    weight=1.0,
                    tags=None,
                )
                for idx in range(1000)
            ]
        )
        session.commit()

    sampler = _CountingSampler()
    risk_engine = RiskEvaluationEngine(sampler=sampler, batch_size=128)
    results = risk_engine.evaluate_pois(
        product_id=product_id,
        valid_time=issued_at,
        bbox=None,
    )

    assert len(results) == 1000
    expected_calls = int(math.ceil(1000 / 128))
    assert sampler.calls == expected_calls
    assert sum(sampler.batch_sizes) == 1000
    assert max(sampler.batch_sizes) <= 128


@pytest.mark.parametrize(
    "bbox",
    [
        (10.0, 0.0, -10.0, 1.0),
        (-181.0, 0.0, 0.0, 1.0),
        (0.0, -91.0, 1.0, 0.0),
        (0.0, 0.0, 1.0, float("nan")),
        (0.0, 1.0, 1.0, 0.0),
    ],
)
def test_risk_engine_invalid_bbox_raises_input_error(
    bbox: tuple[float, float, float, float],
) -> None:
    engine = RiskEvaluationEngine()
    with pytest.raises(RiskEngineInputError):
        engine.evaluate_pois(
            product_id=1,
            valid_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            bbox=bbox,
        )


def test_risk_engine_default_sampler_is_deterministic_and_accepts_naive_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    engine = RiskEvaluationEngine()
    first = engine.evaluate_pois(
        product_id=product_id,
        valid_time=datetime(2024, 1, 1),
        bbox=None,
    )
    second = engine.evaluate_pois(
        product_id=product_id,
        valid_time=datetime(2024, 1, 1),
        bbox=None,
    )
    assert [item.model_dump() for item in first] == [
        item.model_dump() for item in second
    ]


def test_risk_engine_missing_hazard_for_time_raises_not_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    engine = RiskEvaluationEngine()
    with pytest.raises(RiskEngineNotFoundError):
        engine.evaluate_pois(
            product_id=product_id,
            valid_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
            bbox=None,
        )


def test_risk_engine_batch_size_must_be_positive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    engine = RiskEvaluationEngine(batch_size=0, sampler=_CountingSampler())
    with pytest.raises(RiskEngineInputError):
        engine.evaluate_pois(
            product_id=product_id,
            valid_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            bbox=None,
        )


def test_risk_engine_max_workers_must_be_positive() -> None:
    with pytest.raises(RiskEngineInputError):
        RiskEvaluationEngine(max_workers=0)


def test_risk_engine_poi_ids_filters_results_and_handles_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    sampler = _StaticSampler(
        {
            2: {"snowfall": 0, "snow_depth": 0, "wind": 0, "temp": 5},
        }
    )
    engine = RiskEvaluationEngine(sampler=sampler, batch_size=10)
    filtered = engine.evaluate_pois(
        product_id=product_id,
        valid_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        bbox=None,
        poi_ids=[2],
    )
    assert [item.poi_id for item in filtered] == [2]

    empty = engine.evaluate_pois(
        product_id=product_id,
        valid_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        bbox=None,
        poi_ids=[0, -1],
    )
    assert empty == []


def test_risk_engine_missing_weather_sample_is_skipped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    engine = RiskEvaluationEngine(sampler=_MissingSampleSampler(), batch_size=10)
    results = engine.evaluate_pois(
        product_id=product_id,
        valid_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        bbox=None,
    )
    assert [item.poi_id for item in results] == [1]


def test_risk_engine_sampler_can_skip_all_pois(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    engine = RiskEvaluationEngine(sampler=_SkipAllSampler(), batch_size=10)
    results = engine.evaluate_pois(
        product_id=product_id,
        valid_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        bbox=None,
    )
    assert results == []


def test_risk_engine_parallel_results_match_serial(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)
    valid_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

    serial_engine = RiskEvaluationEngine(batch_size=10, max_workers=1)
    parallel_engine = RiskEvaluationEngine(batch_size=10, max_workers=4)

    serial = serial_engine.evaluate_pois(
        product_id=product_id,
        valid_time=valid_time,
        bbox=None,
    )
    parallel = parallel_engine.evaluate_pois(
        product_id=product_id,
        valid_time=valid_time,
        bbox=None,
    )

    assert [item.model_dump() for item in parallel] == [
        item.model_dump() for item in serial
    ]


def test_risk_engine_invalid_weather_payload_raises_input_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    engine = RiskEvaluationEngine(sampler=_InvalidSampleSampler(), batch_size=10)
    with pytest.raises(RiskEngineInputError, match="Missing factor values"):
        engine.evaluate_pois(
            product_id=product_id,
            valid_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            bbox=None,
        )


def test_risk_engine_unknown_product_raises_not_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk_engine_empty.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    from db import get_engine
    from models import Base
    from risk_rules_config import get_risk_rules_payload

    get_engine.cache_clear()
    get_risk_rules_payload.cache_clear()

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    risk_engine = RiskEvaluationEngine()
    with pytest.raises(RiskEngineNotFoundError):
        risk_engine.evaluate_pois(
            product_id=999,
            valid_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            bbox=(100.0, 10.0, 101.0, 11.0),
        )


def test_risk_evaluate_endpoint_without_redis_returns_results_and_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    client = _make_risk_client(redis=None)
    response = client.post(
        "/api/v1/risk/evaluate",
        json={"product_id": product_id, "valid_time": "2024-01-01T00:00:00"},
    )
    assert response.status_code == 200
    assert response.headers.get("etag", "").startswith('"sha256-')
    assert response.headers.get("x-risk-rules-etag", "").startswith('"sha256-')

    payload = response.json()
    assert payload["summary"]["total"] == 2
    assert payload["summary"]["duration_ms"] >= 0
    assert sum(payload["summary"]["reasons"].values()) == payload["summary"]["total"]
    assert set(payload["summary"]["reasons"]).issubset(
        {"snowfall", "snow_depth", "wind", "temp"}
    )
    assert len(payload["results"]) == 2
    assert [item["poi_id"] for item in payload["results"]] == [1, 2]
    assert all(len(item["factors"]) == 4 for item in payload["results"])
    assert all("reasons" in item for item in payload["results"])
    assert all(isinstance(item["reasons"], list) for item in payload["results"])


def test_risk_evaluate_persists_levels_for_risk_pois_lookup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config_all_positive(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    client = _make_risk_client(redis=None)

    evaluation = client.post(
        "/api/v1/risk/evaluate",
        json={"product_id": product_id, "valid_time": "2024-01-01T00:00:00Z"},
    )
    assert evaluation.status_code == 200
    evaluation_payload = evaluation.json()
    assert [item["poi_id"] for item in evaluation_payload["results"]] == [1, 2]
    levels_by_poi_id = {
        int(item["poi_id"]): int(item["level"]) for item in evaluation_payload["results"]
    }

    pois = client.get(
        "/api/v1/risk/pois",
        params={
            "bbox": "100,10,101,11",
            "product_id": product_id,
            "valid_time": "2024-01-01T00:00:00Z",
        },
    )
    assert pois.status_code == 200
    pois_payload = pois.json()
    assert pois_payload["total"] == 2
    assert [item["id"] for item in pois_payload["items"]] == [1, 2]
    for item in pois_payload["items"]:
        assert item["risk_level"] == levels_by_poi_id[int(item["id"])]


def test_risk_evaluate_endpoint_uses_locale_in_cache_key_for_reasons(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config_all_positive(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    redis = FakeRedis(use_real_time=False)
    client = _make_risk_client(redis=redis)

    en = client.post(
        "/api/v1/risk/evaluate",
        json={"product_id": product_id, "valid_time": "2024-01-01T00:00:00Z"},
        headers={"Accept-Language": "en"},
    )
    assert en.status_code == 200
    en_payload = en.json()
    assert en_payload["summary"]["total"] == 2
    assert en_payload["results"][0]["reasons"][0]["factor_id"] == "snowfall"
    assert en_payload["results"][0]["reasons"][0]["factor_name"] == "Snowfall"

    zh = client.post(
        "/api/v1/risk/evaluate",
        json={"product_id": product_id, "valid_time": "2024-01-01T00:00:00Z"},
        headers={"Accept-Language": "zh-CN"},
    )
    assert zh.status_code == 200
    zh_payload = zh.json()
    assert zh_payload["summary"]["total"] == 2
    assert zh_payload["results"][0]["reasons"][0]["factor_id"] == "snowfall"
    assert zh_payload["results"][0]["reasons"][0]["factor_name"] == "降雪量"


def test_risk_engine_reasons_select_intermediate_threshold_and_supports_zh_cn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config_intermediate_thresholds(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    sampler = _StaticSampler(
        {
            1: {"snowfall": 7, "snow_depth": 0, "wind": 0, "temp": -5},
            2: {"snowfall": 0, "snow_depth": 0, "wind": 0, "temp": 5},
        }
    )
    engine = RiskEvaluationEngine(sampler=sampler, batch_size=2)

    results = engine.evaluate_pois(
        product_id=product_id,
        valid_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        bbox=None,
        locale="zh-CN",
    )
    assert [item.poi_id for item in results] == [1, 2]
    assert [item.factor_id for item in results[0].reasons] == [
        RiskFactorId.snowfall,
        RiskFactorId.temp,
    ]
    assert results[0].reasons[0].factor_name == "降雪量"
    assert results[0].reasons[0].threshold == pytest.approx(5.0)
    assert results[0].reasons[1].factor_name == "气温"
    assert results[0].reasons[1].threshold == pytest.approx(0.0)


def test_risk_engine_sqlalchemy_errors_are_wrapped_as_database_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()

    import db as db_module

    def _boom() -> None:
        raise SQLAlchemyError("boom")

    monkeypatch.setattr(db_module, "get_engine", _boom)

    engine = RiskEvaluationEngine()
    with pytest.raises(RiskEngineDatabaseError, match="Database unavailable"):
        engine.evaluate_pois(
            product_id=1,
            valid_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            bbox=(100.0, 10.0, 101.0, 11.0),
        )


def test_risk_evaluate_endpoint_with_redis_uses_cache_on_repeat_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    redis = FakeRedis(use_real_time=False)
    client = _make_risk_client(redis=redis)
    first = client.post(
        "/api/v1/risk/evaluate",
        json={"product_id": product_id, "valid_time": "2024-01-01T00:00:00"},
    )
    assert first.status_code == 200
    first_payload = first.json()

    import routers.risk as risk_router_module

    class _BoomEngine:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("RiskEvaluationEngine should not run on cache hit")

    monkeypatch.setattr(risk_router_module, "RiskEvaluationEngine", _BoomEngine)

    second = client.post(
        "/api/v1/risk/evaluate",
        json={"product_id": product_id, "valid_time": "2024-01-01T00:00:00"},
    )
    assert second.status_code == 200
    assert second.json() == first_payload


def test_risk_evaluate_endpoint_cache_key_distinguishes_empty_poi_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    redis = FakeRedis(use_real_time=False)
    client = _make_risk_client(redis=redis)

    all_pois = client.post(
        "/api/v1/risk/evaluate",
        json={"product_id": product_id, "valid_time": "2024-01-01T00:00:00"},
    )
    assert all_pois.status_code == 200
    assert all_pois.json()["summary"]["total"] == 2

    empty_pois = client.post(
        "/api/v1/risk/evaluate",
        json={
            "product_id": product_id,
            "valid_time": "2024-01-01T00:00:00",
            "poi_ids": [],
        },
    )
    assert empty_pois.status_code == 200
    payload = empty_pois.json()
    assert payload["summary"]["total"] == 0
    assert payload["results"] == []


def test_risk_evaluate_endpoint_cache_timeout_returns_503(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    import routers.risk as risk_router_module

    async def _timeout(*args: object, **kwargs: object) -> object:
        raise TimeoutError("boom")

    monkeypatch.setattr(risk_router_module, "get_or_compute_cached_bytes", _timeout)

    redis = FakeRedis(use_real_time=False)
    client = _make_risk_client(redis=redis)
    response = client.post(
        "/api/v1/risk/evaluate",
        json={"product_id": product_id, "valid_time": "2024-01-01T00:00:00"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Risk evaluation cache warming timed out"


def test_risk_evaluate_endpoint_cache_error_falls_back_to_compute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    import routers.risk as risk_router_module

    async def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(risk_router_module, "get_or_compute_cached_bytes", _boom)

    redis = FakeRedis(use_real_time=False)
    client = _make_risk_client(redis=redis)
    response = client.post(
        "/api/v1/risk/evaluate",
        json={"product_id": product_id, "valid_time": "2024-01-01T00:00:00"},
    )
    assert response.status_code == 200
    assert response.json()["summary"]["total"] == 2


def test_risk_evaluate_endpoint_with_redis_returns_400_for_invalid_bbox(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    redis = FakeRedis(use_real_time=False)
    client = _make_risk_client(redis=redis)
    response = client.post(
        "/api/v1/risk/evaluate",
        json={
            "product_id": product_id,
            "valid_time": "2024-01-01T00:00:00Z",
            "bbox": [10.0, 0.0, -10.0, 1.0],
        },
    )
    assert response.status_code == 400


def test_risk_evaluate_endpoint_returns_503_on_database_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    import routers.risk as risk_router_module

    class _FailingEngine:
        def evaluate_pois(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            raise RiskEngineDatabaseError("Database unavailable")

    monkeypatch.setattr(
        risk_router_module,
        "RiskEvaluationEngine",
        lambda *args, **kwargs: _FailingEngine(),
    )

    client = _make_risk_client(redis=None)
    response = client.post(
        "/api/v1/risk/evaluate",
        json={"product_id": product_id, "valid_time": "2024-01-01T00:00:00Z"},
    )
    assert response.status_code == 503


def _risk_evaluate_cache_digest(
    *,
    product_id: int,
    valid_time: datetime,
    bbox: list[float] | None,
    poi_ids: list[int] | None,
    rules_etag: str,
    reasons_locale: str = "en",
) -> str:
    if poi_ids is None:
        poi_identity: str | list[int] = "all"
    else:
        ids = sorted({int(item) for item in poi_ids if int(item) > 0})
        poi_identity = ids if ids else "empty"

    dt = valid_time
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)

    identity_payload = {
        "product_id": int(product_id),
        "valid_time": dt.strftime("%Y%m%dT%H%M%SZ"),
        "bbox": list(bbox) if bbox is not None else None,
        "poi_ids": poi_identity,
        "rules_etag": rules_etag,
        "reasons_locale": reasons_locale,
    }
    identity = json.dumps(identity_payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def test_risk_evaluate_endpoint_if_none_match_returns_304(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    redis = FakeRedis(use_real_time=False)
    client = _make_risk_client(redis=redis)
    first = client.post(
        "/api/v1/risk/evaluate",
        json={"product_id": product_id, "valid_time": "2024-01-01T00:00:00"},
    )
    assert first.status_code == 200
    etag = first.headers["etag"]
    rules_etag = first.headers["x-risk-rules-etag"]

    cached = client.post(
        "/api/v1/risk/evaluate",
        json={"product_id": product_id, "valid_time": "2024-01-01T00:00:00"},
        headers={"If-None-Match": etag},
    )
    assert cached.status_code == 304
    assert cached.headers["etag"] == etag
    assert cached.headers["x-risk-rules-etag"] == rules_etag
    assert cached.text == ""


def test_risk_evaluate_endpoint_cache_hit_emits_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    redis = FakeRedis(use_real_time=False)
    client = _make_risk_client(redis=redis)
    first = client.post(
        "/api/v1/risk/evaluate",
        json={"product_id": product_id, "valid_time": "2024-01-01T00:00:00"},
    )
    assert first.status_code == 200

    caplog.set_level(logging.INFO, logger="api.error")
    caplog.clear()

    second = client.post(
        "/api/v1/risk/evaluate",
        json={"product_id": product_id, "valid_time": "2024-01-01T00:00:00"},
    )
    assert second.status_code == 200
    assert any(record.message == "risk_evaluate_cache_hit" for record in caplog.records)


def test_risk_evaluate_endpoint_cache_key_includes_bbox_and_valid_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    redis = FakeRedis(use_real_time=False)
    client = _make_risk_client(redis=redis)

    base = client.post(
        "/api/v1/risk/evaluate",
        json={"product_id": product_id, "valid_time": "2024-01-01T00:00:00"},
    )
    assert base.status_code == 200
    rules_etag = base.headers["x-risk-rules-etag"]

    with_bbox = client.post(
        "/api/v1/risk/evaluate",
        json={
            "product_id": product_id,
            "valid_time": "2024-01-01T00:00:00",
            "bbox": [100.0, 10.0, 101.0, 11.0],
        },
    )
    assert with_bbox.status_code == 200

    with_time = client.post(
        "/api/v1/risk/evaluate",
        json={"product_id": product_id, "valid_time": "2024-01-01T01:00:00"},
    )
    assert with_time.status_code == 200

    digest_base = _risk_evaluate_cache_digest(
        product_id=product_id,
        valid_time=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
        bbox=None,
        poi_ids=None,
        rules_etag=rules_etag,
    )
    digest_bbox = _risk_evaluate_cache_digest(
        product_id=product_id,
        valid_time=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
        bbox=[100.0, 10.0, 101.0, 11.0],
        poi_ids=None,
        rules_etag=rules_etag,
    )
    digest_time = _risk_evaluate_cache_digest(
        product_id=product_id,
        valid_time=datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc),
        bbox=None,
        poi_ids=None,
        rules_etag=rules_etag,
    )

    assert len({digest_base, digest_bbox, digest_time}) == 3
    assert f"risk:evaluate:fresh:{digest_base}" in redis.values
    assert f"risk:evaluate:stale:{digest_base}" in redis.values
    assert f"risk:evaluate:fresh:{digest_bbox}" in redis.values
    assert f"risk:evaluate:stale:{digest_bbox}" in redis.values
    assert f"risk:evaluate:fresh:{digest_time}" in redis.values
    assert f"risk:evaluate:stale:{digest_time}" in redis.values


def test_risk_evaluate_endpoint_cache_key_includes_rules_etag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_v1 = tmp_path / "risk-rules-v1.yaml"
    _write_risk_rules_config(rules_v1)

    rules_v2 = tmp_path / "risk-rules-v2.yaml"
    rules_v2.write_text(
        rules_v1.read_text(encoding="utf-8").replace("threshold: 10", "threshold: 11"),
        encoding="utf-8",
    )

    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_v1))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    redis = FakeRedis(use_real_time=False)
    client = _make_risk_client(redis=redis)

    v1 = client.post(
        "/api/v1/risk/evaluate",
        json={"product_id": product_id, "valid_time": "2024-01-01T00:00:00"},
    )
    assert v1.status_code == 200
    etag_v1 = v1.headers["x-risk-rules-etag"]

    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_v2))
    get_risk_rules_payload.cache_clear()

    v2 = client.post(
        "/api/v1/risk/evaluate",
        json={"product_id": product_id, "valid_time": "2024-01-01T00:00:00"},
    )
    assert v2.status_code == 200
    etag_v2 = v2.headers["x-risk-rules-etag"]
    assert etag_v2 != etag_v1

    digest_v1 = _risk_evaluate_cache_digest(
        product_id=product_id,
        valid_time=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
        bbox=None,
        poi_ids=None,
        rules_etag=etag_v1,
    )
    digest_v2 = _risk_evaluate_cache_digest(
        product_id=product_id,
        valid_time=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
        bbox=None,
        poi_ids=None,
        rules_etag=etag_v2,
    )
    assert digest_v1 != digest_v2
    assert f"risk:evaluate:fresh:{digest_v1}" in redis.values
    assert f"risk:evaluate:fresh:{digest_v2}" in redis.values
