from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from risk_engine import (
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


def test_risk_engine_invalid_bbox_raises_input_error() -> None:
    engine = RiskEvaluationEngine()
    with pytest.raises(RiskEngineInputError):
        engine.evaluate_pois(
            product_id=1,
            valid_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            bbox=(10.0, 0.0, -10.0, 1.0),
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
