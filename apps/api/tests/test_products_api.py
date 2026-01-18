from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from redis_fakes import FakeRedis


def _write_config(dir_path: Path, env: str, data: dict) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{env}.json").write_text(json.dumps(data), encoding="utf-8")


def _base_config() -> dict:
    return {
        "api": {
            "host": "0.0.0.0",
            "port": 8000,
            "debug": True,
            "cors_origins": [],
            "rate_limit": {"enabled": False},
        },
        "pipeline": {"workers": 2, "batch_size": 100},
        "web": {"api_base_url": "http://localhost:8000"},
        "database": {"host": "localhost", "port": 5432, "name": "digital_earth"},
        "redis": {"host": "localhost", "port": 6379},
        "storage": {"tiles_bucket": "tiles", "raw_bucket": "raw"},
    }


def _seed_products(db_url: str) -> None:
    from models import Base, Product, ProductHazard

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    issued_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_from = issued_at
    valid_to = issued_at + timedelta(days=1)

    polygons = {
        "降雪": {
            "type": "Polygon",
            "coordinates": [
                [
                    [126.0, 45.0],
                    [127.0, 45.0],
                    [127.0, 46.0],
                    [126.0, 46.0],
                    [126.0, 45.0],
                ]
            ],
        },
        "大风": {
            "type": "Polygon",
            "coordinates": [
                [
                    [85.0, 42.0],
                    [86.5, 42.0],
                    [86.5, 43.0],
                    [85.0, 43.0],
                    [85.0, 42.0],
                ]
            ],
        },
        "强降水": {
            "type": "Polygon",
            "coordinates": [
                [
                    [112.0, 22.0],
                    [114.0, 22.0],
                    [114.0, 23.5],
                    [112.0, 23.5],
                    [112.0, 22.0],
                ]
            ],
        },
    }

    with Session(engine) as session:
        products: list[Product] = []
        for idx, (title, severity) in enumerate(
            [("降雪", "low"), ("大风", "medium"), ("强降水", "high")]
        ):
            product = Product(
                title=title,
                text=f"seeded {title}",
                issued_at=issued_at + timedelta(minutes=idx),
                valid_from=valid_from,
                valid_to=valid_to,
                status="published",
            )
            hazard = ProductHazard(
                severity=severity,
                valid_from=valid_from,
                valid_to=valid_to,
                bbox_min_x=0,
                bbox_min_y=0,
                bbox_max_x=0,
                bbox_max_y=0,
            )
            hazard.set_geometry_from_geojson(polygons[title])
            product.hazards.append(hazard)
            products.append(product)

        session.add_all(products)
        session.commit()


def _make_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, db_url: str
) -> TestClient:
    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")
    monkeypatch.setenv("DATABASE_URL", db_url)

    from config import get_settings
    from db import get_engine
    import main as main_module

    get_settings.cache_clear()
    get_engine.cache_clear()

    redis = FakeRedis(use_real_time=False)
    monkeypatch.setattr(main_module, "create_redis_client", lambda _url: redis)
    return TestClient(main_module.create_app())


def test_products_endpoint_returns_seeded_products(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products.db'}"
    _seed_products(db_url)

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    response = client.get("/api/v1/products")
    assert response.status_code == 200

    payload = response.json()
    assert {item["title"] for item in payload["items"]} == {"降雪", "大风", "强降水"}
    assert all(len(item["hazards"]) == 1 for item in payload["items"])
    for item in payload["items"]:
        hazard = item["hazards"][0]
        assert hazard["geometry"]["type"] == "Polygon"


def test_products_hazards_geojson_returns_features(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products.db'}"
    _seed_products(db_url)

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    response = client.get("/api/v1/products/hazards")
    assert response.status_code == 200

    payload = response.json()
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == 3
    titles = {feature["properties"]["product_title"] for feature in payload["features"]}
    assert titles == {"降雪", "大风", "强降水"}
    assert all(
        feature["geometry"]["type"] == "Polygon" for feature in payload["features"]
    )


def test_products_hazards_bbox_filter_returns_matching_features(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products.db'}"
    _seed_products(db_url)

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    response = client.get(
        "/api/v1/products/hazards",
        params={"bbox": "125.5,44.5,126.5,45.5"},
    )
    assert response.status_code == 200

    payload = response.json()
    assert len(payload["features"]) == 1
    assert payload["features"][0]["properties"]["product_title"] == "降雪"


def test_products_hazards_invalid_bbox_returns_400(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products.db'}"
    _seed_products(db_url)

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    response = client.get("/api/v1/products/hazards", params={"bbox": "0,0,0"})
    assert response.status_code == 400


def test_products_endpoint_bbox_filter_excludes_non_matching_products(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products.db'}"
    _seed_products(db_url)

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    response = client.get("/api/v1/products", params={"bbox": "0,0,1,1"})
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_products_endpoint_time_filter_supports_start_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products.db'}"
    _seed_products(db_url)

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    response = client.get(
        "/api/v1/products",
        params={"start": "2026-01-03T00:00:00Z"},
    )
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_products_endpoint_time_filter_supports_end_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products.db'}"
    _seed_products(db_url)

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    response = client.get(
        "/api/v1/products",
        params={"end": "2026-01-03T00:00:00Z"},
    )
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_products_endpoint_time_filter_supports_start_and_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products.db'}"
    _seed_products(db_url)

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    response = client.get(
        "/api/v1/products",
        params={
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-01T12:00:00Z",
        },
    )
    assert response.status_code == 200
    assert {item["title"] for item in response.json()["items"]} == {"降雪", "大风", "强降水"}


def test_products_endpoint_bbox_filter_can_exclude_by_y_overlap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products.db'}"
    _seed_products(db_url)

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    response = client.get("/api/v1/products", params={"bbox": "126.2,0,126.8,1"})
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_products_hazards_time_filter_applies_to_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products.db'}"
    _seed_products(db_url)

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    response = client.get(
        "/api/v1/products/hazards",
        params={"start": "2026-01-01T12:00:00Z"},
    )
    assert response.status_code == 200
    assert len(response.json()["features"]) == 3


@pytest.mark.parametrize(
    ("bbox", "expected_status"),
    [
        ("0,0,a,1", 400),
        ("0,0,inf,1", 400),
        ("0,0,0,1", 400),
        ("  ", 200),
    ],
)
def test_products_hazards_bbox_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    bbox: str,
    expected_status: int,
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products.db'}"
    _seed_products(db_url)

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    response = client.get("/api/v1/products/hazards", params={"bbox": bbox})
    assert response.status_code == expected_status


def test_products_endpoints_return_500_on_sqlalchemy_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products.db'}"
    _seed_products(db_url)
    client = _make_client(monkeypatch, tmp_path, db_url=db_url)

    from sqlalchemy.exc import SQLAlchemyError
    from routers import products as products_router

    class _BoomSession:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> "_BoomSession":
            raise SQLAlchemyError("boom")

        def __exit__(
            self,
            _exc_type: object,
            _exc: object,
            _tb: object,
        ) -> None:
            return None

    monkeypatch.setattr(products_router, "Session", _BoomSession)

    assert client.get("/api/v1/products").status_code == 500
    assert client.get("/api/v1/products/hazards").status_code == 500
