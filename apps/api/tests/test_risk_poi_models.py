from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from models import Base, RiskPOI


def test_risk_poi_model_defines_expected_table_columns() -> None:
    tables = Base.metadata.tables
    assert "risk_pois" in tables

    assert set(tables["risk_pois"].columns.keys()) >= {
        "id",
        "name",
        "type",
        "lon",
        "lat",
        "alt",
        "weight",
        "tags",
    }


def test_risk_poi_model_creates_expected_indexes() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    indexes = {idx["name"]: idx for idx in inspector.get_indexes("risk_pois")}

    assert "ix_risk_pois_geom" in indexes
    assert indexes["ix_risk_pois_geom"]["column_names"] == ["lon", "lat"]

    assert "ix_risk_pois_type" in indexes
    assert indexes["ix_risk_pois_type"]["column_names"] == ["type"]


def test_risk_poi_bbox_and_type_query_returns_expected_rows() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                RiskPOI(
                    name="poi-a",
                    poi_type="fire",
                    lon=110.0,
                    lat=35.0,
                    alt=None,
                    weight=1.0,
                    tags=["hot"],
                ),
                RiskPOI(
                    name="poi-b",
                    poi_type="flood",
                    lon=111.0,
                    lat=35.0,
                    alt=12.0,
                    weight=0.5,
                    tags=["river"],
                ),
                RiskPOI(
                    name="poi-c",
                    poi_type="fire",
                    lon=140.0,
                    lat=10.0,
                    alt=0.0,
                    weight=2.0,
                    tags=None,
                ),
            ]
        )
        session.commit()

        stmt = RiskPOI.select_in_bbox(
            min_lon=109.0,
            min_lat=34.0,
            max_lon=112.0,
            max_lat=36.0,
            poi_types=["fire"],
        )
        assert [item.name for item in session.scalars(stmt).all()] == ["poi-a"]

        bbox_only = RiskPOI.select_in_bbox(
            min_lon=109.0,
            min_lat=34.0,
            max_lon=112.0,
            max_lat=36.0,
        )
        assert sorted([item.name for item in session.scalars(bbox_only).all()]) == [
            "poi-a",
            "poi-b",
        ]


def test_risk_poi_geom_and_type_indexes_are_usable_in_sqlite() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                RiskPOI(name="poi-a", poi_type="fire", lon=110.0, lat=35.0, weight=1.0),
                RiskPOI(
                    name="poi-b", poi_type="flood", lon=111.0, lat=35.0, weight=1.0
                ),
                RiskPOI(name="poi-c", poi_type="fire", lon=140.0, lat=10.0, weight=1.0),
            ]
        )
        session.commit()

        geom_names = session.execute(
            text(
                """
                SELECT name
                FROM risk_pois INDEXED BY ix_risk_pois_geom
                WHERE lon >= :min_lon AND lon <= :max_lon
                  AND lat >= :min_lat AND lat <= :max_lat
                ORDER BY id
                """
            ),
            {"min_lon": 109.0, "max_lon": 112.0, "min_lat": 34.0, "max_lat": 36.0},
        ).scalars()
        assert list(geom_names) == ["poi-a", "poi-b"]

        type_names = session.execute(
            text(
                """
                SELECT name
                FROM risk_pois INDEXED BY ix_risk_pois_type
                WHERE "type" = :poi_type
                ORDER BY id
                """
            ),
            {"poi_type": "fire"},
        ).scalars()
        assert list(type_names) == ["poi-a", "poi-c"]
