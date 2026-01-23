from __future__ import annotations

from sqlalchemy import create_engine, inspect

from models import Base


def test_risk_poi_evaluation_model_creates_expected_indexes() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    indexes = {idx["name"]: idx for idx in inspector.get_indexes("risk_poi_evaluations")}

    assert "ix_risk_poi_evaluations_poi_id" in indexes
    assert indexes["ix_risk_poi_evaluations_poi_id"]["column_names"] == ["poi_id"]

    assert "ix_risk_poi_evaluations_product_time" in indexes
    assert indexes["ix_risk_poi_evaluations_product_time"]["column_names"] == [
        "product_id",
        "valid_time",
    ]

    assert "ix_risk_poi_evaluations_product_time_poi" in indexes
    assert indexes["ix_risk_poi_evaluations_product_time_poi"]["column_names"] == [
        "product_id",
        "valid_time",
        "poi_id",
    ]

    assert "ix_risk_poi_evaluations_valid_time" in indexes
    assert indexes["ix_risk_poi_evaluations_valid_time"]["column_names"] == ["valid_time"]

