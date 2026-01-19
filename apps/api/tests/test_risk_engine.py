from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from redis_fakes import FakeRedis
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

    assert results[1].level == 1
    assert results[1].score == pytest.approx(0.0)


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


def test_risk_engine_missing_weather_sample_is_skipped_in_parallel_and_serial(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    sampler = _MissingSampleSampler()
    parallel_engine = RiskEvaluationEngine(
        sampler=sampler, batch_size=10, max_workers=4, parallel=True
    )
    serial_engine = RiskEvaluationEngine(
        sampler=sampler, batch_size=10, max_workers=1, parallel=False
    )
    parallel_results = parallel_engine.evaluate_pois(
        product_id=product_id,
        valid_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        bbox=None,
    )
    serial_results = serial_engine.evaluate_pois(
        product_id=product_id,
        valid_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        bbox=None,
    )

    assert [item.poi_id for item in serial_results] == [1]
    assert [item.model_dump() for item in parallel_results] == [
        item.model_dump() for item in serial_results
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
    assert len(payload["results"]) == 2
    assert [item["poi_id"] for item in payload["results"]] == [1, 2]
    assert all(len(item["factors"]) == 4 for item in payload["results"])


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


def test_risk_evaluate_endpoint_gzips_large_payload_when_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    db_url, product_id = _setup_db(monkeypatch, tmp_path)

    from models import Base, RiskPOI

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        extra = 200
        session.add_all(
            [
                RiskPOI(
                    name=f"poi-extra-{idx}",
                    poi_type="fire",
                    lon=100.1 + (idx % 50) * 0.001,
                    lat=10.1 + (idx // 50) * 0.001,
                    alt=None,
                    weight=1.0,
                    tags=None,
                )
                for idx in range(extra)
            ]
        )
        session.commit()
    engine.dispose()

    client = _make_risk_client(redis=None)
    response = client.post(
        "/api/v1/risk/evaluate",
        json={"product_id": product_id, "valid_time": "2024-01-01T00:00:00Z"},
        headers={"Accept-Encoding": "gzip"},
    )
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["vary"] == "Accept-Encoding"
    assert int(response.headers["content-length"]) < len(response.content)
    assert response.json()["summary"]["total"] == 2 + extra


def test_risk_evaluate_endpoint_does_not_gzip_when_qvalue_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    db_url, product_id = _setup_db(monkeypatch, tmp_path)

    from models import Base, RiskPOI

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        extra = 200
        session.add_all(
            [
                RiskPOI(
                    name=f"poi-extra-{idx}",
                    poi_type="fire",
                    lon=100.1 + (idx % 50) * 0.001,
                    lat=10.1 + (idx // 50) * 0.001,
                    alt=None,
                    weight=1.0,
                    tags=None,
                )
                for idx in range(extra)
            ]
        )
        session.commit()
    engine.dispose()

    client = _make_risk_client(redis=None)
    response = client.post(
        "/api/v1/risk/evaluate",
        json={"product_id": product_id, "valid_time": "2024-01-01T00:00:00Z"},
        headers={"Accept-Encoding": "gzip;q=0"},
    )
    assert response.status_code == 200
    assert response.json()["summary"]["total"] == 2 + extra
    assert "content-encoding" not in response.headers
    assert "vary" not in response.headers


def test_risk_engine_parallel_results_match_serial_for_large_batches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    db_url, product_id = _setup_db(monkeypatch, tmp_path)

    from models import Base, RiskPOI

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        extra = 600
        session.add_all(
            [
                RiskPOI(
                    name=f"poi-extra-{idx}",
                    poi_type="fire",
                    lon=100.1 + (idx % 50) * 0.001,
                    lat=10.1 + (idx // 50) * 0.001,
                    alt=None,
                    weight=1.0,
                    tags=None,
                )
                for idx in range(extra)
            ]
        )
        session.commit()
    engine.dispose()

    valid_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

    parallel_engine = RiskEvaluationEngine(
        batch_size=1024, max_workers=4, parallel=True
    )
    serial_engine = RiskEvaluationEngine(batch_size=1024, max_workers=1, parallel=False)

    parallel_results = parallel_engine.evaluate_pois(
        product_id=product_id,
        valid_time=valid_time,
        bbox=None,
    )
    serial_results = serial_engine.evaluate_pois(
        product_id=product_id,
        valid_time=valid_time,
        bbox=None,
    )

    assert [item.model_dump() for item in parallel_results] == [
        item.model_dump() for item in serial_results
    ]


def test_risk_engine_uses_prepare_sampler_when_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    class _PrepareSampler:
        def __init__(self) -> None:
            self.prepare_calls = 0
            self.sample_calls = 0

        def prepare(self, *, product_id: int, valid_time: datetime):  # type: ignore[no-untyped-def]
            self.prepare_calls += 1
            parent = self

            class _Prepared:
                def sample(self, *, pois):  # type: ignore[no-untyped-def]
                    parent.sample_calls += 1
                    return {
                        int(poi.id): {
                            "snowfall": 0.0,
                            "snow_depth": 0.0,
                            "wind": 0.0,
                            "temp": 5.0,
                        }
                        for poi in pois
                    }

            return _Prepared()

        def sample(self, *, product_id: int, valid_time: datetime, pois):  # type: ignore[no-untyped-def]
            raise AssertionError(
                "Sampler.sample should not be called when prepare exists"
            )

    sampler = _PrepareSampler()
    risk_engine = RiskEvaluationEngine(sampler=sampler, batch_size=1, max_workers=1)
    results = risk_engine.evaluate_pois(
        product_id=product_id,
        valid_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        bbox=None,
    )

    assert [item.poi_id for item in results] == [1, 2]
    assert sampler.prepare_calls == 1
    assert sampler.sample_calls == 2


def test_risk_engine_prepare_type_error_falls_back_to_sample(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rules_path = tmp_path / "risk-rules.yaml"
    _write_risk_rules_config(rules_path)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(rules_path))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    _db_url, product_id = _setup_db(monkeypatch, tmp_path)

    class _SamplerWithBadPrepare(_CountingSampler):
        def prepare(self, *, product_id: int, valid_time: datetime):  # type: ignore[no-untyped-def]
            raise TypeError("boom")

    sampler = _SamplerWithBadPrepare()
    risk_engine = RiskEvaluationEngine(sampler=sampler, batch_size=10, max_workers=1)
    results = risk_engine.evaluate_pois(
        product_id=product_id,
        valid_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        bbox=None,
    )

    assert [item.poi_id for item in results] == [1, 2]
    assert sampler.calls == 1
