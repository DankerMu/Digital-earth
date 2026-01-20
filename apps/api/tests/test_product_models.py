from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from models import Base, Product, ProductHazard
from models.products import bbox_from_geojson


def test_product_models_define_expected_tables() -> None:
    tables = Base.metadata.tables
    assert set(tables) >= {"products", "product_hazards", "product_versions"}

    assert set(tables["products"].columns.keys()) >= {
        "id",
        "title",
        "text",
        "issued_at",
        "valid_from",
        "valid_to",
        "status",
        "version",
        "created_at",
    }

    assert set(tables["product_hazards"].columns.keys()) >= {
        "id",
        "product_id",
        "severity",
        "geometry",
        "valid_from",
        "valid_to",
        "bbox_min_x",
        "bbox_min_y",
        "bbox_max_x",
        "bbox_max_y",
        "created_at",
    }

    assert set(tables["product_versions"].columns.keys()) >= {
        "id",
        "product_id",
        "version",
        "snapshot",
        "published_at",
    }


def test_product_models_create_indexes_and_constraints() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    product_indexes = {idx["name"]: idx for idx in inspector.get_indexes("products")}
    assert product_indexes["ix_products_issued_at"]["column_names"] == ["issued_at"]
    assert product_indexes["ix_products_valid_from"]["column_names"] == ["valid_from"]
    assert product_indexes["ix_products_valid_to"]["column_names"] == ["valid_to"]
    assert product_indexes["ix_products_status"]["column_names"] == ["status"]

    hazard_indexes = {
        idx["name"]: idx for idx in inspector.get_indexes("product_hazards")
    }
    assert hazard_indexes["ix_product_hazards_product_id"]["column_names"] == [
        "product_id"
    ]
    assert hazard_indexes["ix_product_hazards_valid_from"]["column_names"] == [
        "valid_from"
    ]
    assert hazard_indexes["ix_product_hazards_valid_to"]["column_names"] == ["valid_to"]
    assert hazard_indexes["ix_product_hazards_bbox"]["column_names"] == [
        "bbox_min_x",
        "bbox_max_x",
        "bbox_min_y",
        "bbox_max_y",
    ]

    fks = inspector.get_foreign_keys("product_hazards")
    assert any(fk["referred_table"] == "products" for fk in fks)

    version_indexes = {
        idx["name"]: idx for idx in inspector.get_indexes("product_versions")
    }
    assert version_indexes["ix_product_versions_product_id"]["column_names"] == [
        "product_id"
    ]
    assert version_indexes["ix_product_versions_published_at"]["column_names"] == [
        "published_at"
    ]

    version_fks = inspector.get_foreign_keys("product_versions")
    assert any(fk["referred_table"] == "products" for fk in version_fks)

    uniques = inspector.get_unique_constraints("product_versions")
    assert any(
        set(constraint["column_names"]) == {"product_id", "version"}
        for constraint in uniques
    )


def test_products_default_version_and_publish_status() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with Session(engine) as session:
        product = Product(
            title="Test product",
            text="Some text",
            issued_at=now,
            valid_from=now,
            valid_to=now,
        )
        session.add(product)
        session.commit()

        session.refresh(product)
        assert product.version == 1
        assert product.status == "draft"


def test_geometry_blob_round_trips_geojson_and_sets_bbox() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    polygon = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 0], [2, 3], [0, 3], [0, 0]]],
    }

    with Session(engine) as session:
        product = Product(
            title="Hazards",
            issued_at=now,
            valid_from=now,
            valid_to=now,
        )
        hazard = ProductHazard(
            severity="high",
            valid_from=now,
            valid_to=now,
            bbox_min_x=0,
            bbox_min_y=0,
            bbox_max_x=0,
            bbox_max_y=0,
        )
        hazard.set_geometry_from_geojson(polygon)
        product.hazards.append(hazard)

        session.add(product)
        session.commit()

        loaded = session.get(ProductHazard, hazard.id)
        assert loaded is not None
        assert loaded.geometry == polygon
        assert (
            loaded.bbox_min_x,
            loaded.bbox_min_y,
            loaded.bbox_max_x,
            loaded.bbox_max_y,
        ) == (
            0.0,
            0.0,
            2.0,
            3.0,
        )


def test_geometry_blob_round_trips_wkb_bytes() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    wkb_point = (
        b"\x01\x01\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\xf0?"
        b"\x00\x00\x00\x00\x00\x00\xf0?"
    )

    with Session(engine) as session:
        product = Product(
            title="WKB hazards",
            issued_at=now,
            valid_from=now,
            valid_to=now,
        )
        hazard = ProductHazard(
            severity="low",
            geometry=wkb_point,
            valid_from=now,
            valid_to=now,
            bbox_min_x=1,
            bbox_min_y=1,
            bbox_max_x=1,
            bbox_max_y=1,
        )
        product.hazards.append(hazard)
        session.add(product)
        session.commit()

        loaded = session.get(ProductHazard, hazard.id)
        assert loaded is not None
        assert loaded.geometry == wkb_point


def test_bbox_from_geojson_handles_feature_collections() -> None:
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Point", "coordinates": [1, 2]},
            },
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "GeometryCollection",
                    "geometries": [{"type": "Point", "coordinates": [3, 4]}],
                },
            },
        ],
    }

    assert bbox_from_geojson(geojson) == (1.0, 2.0, 3.0, 4.0)


def test_bbox_from_geojson_raises_for_missing_coordinates() -> None:
    try:
        bbox_from_geojson({"type": "Point"})
    except ValueError as exc:
        assert "no coordinates" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected bbox_from_geojson to raise ValueError")


def test_product_hazard_bbox_and_time_filters_support_queries() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    with Session(engine) as session:
        product = Product(
            title="Query hazards",
            issued_at=t0,
            valid_from=t0,
            valid_to=t1,
        )
        product.hazards.extend(
            [
                ProductHazard(
                    severity="high",
                    geometry=b"\x01",
                    valid_from=t0,
                    valid_to=t1,
                    bbox_min_x=0,
                    bbox_min_y=0,
                    bbox_max_x=10,
                    bbox_max_y=10,
                ),
                ProductHazard(
                    severity="low",
                    geometry=b"\x01",
                    valid_from=t0,
                    valid_to=t1,
                    bbox_min_x=20,
                    bbox_min_y=20,
                    bbox_max_x=30,
                    bbox_max_y=30,
                ),
            ]
        )

        session.add(product)
        session.commit()

        bbox_min_x, bbox_min_y, bbox_max_x, bbox_max_y = 5, 5, 15, 15
        start, end = t0, t1

        matches = (
            session.query(ProductHazard)
            .filter(ProductHazard.valid_from <= end)
            .filter(ProductHazard.valid_to >= start)
            .filter(ProductHazard.bbox_min_x <= bbox_max_x)
            .filter(ProductHazard.bbox_max_x >= bbox_min_x)
            .filter(ProductHazard.bbox_min_y <= bbox_max_y)
            .filter(ProductHazard.bbox_max_y >= bbox_min_y)
            .all()
        )

        assert [hazard.severity for hazard in matches] == ["high"]
