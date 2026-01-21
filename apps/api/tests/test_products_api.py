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
    assert payload["page"] == 1
    assert payload["page_size"] == 50
    assert payload["total"] == 3
    assert {item["title"] for item in payload["items"]} == {"降雪", "大风", "强降水"}
    assert all(len(item["hazards"]) == 1 for item in payload["items"])
    for item in payload["items"]:
        hazard = item["hazards"][0]
        assert hazard["geometry"]["type"] == "Polygon"
        assert set(hazard["bbox"]) == {"min_x", "min_y", "max_x", "max_y"}


def test_product_detail_endpoint_returns_text_and_hazards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products.db'}"
    _seed_products(db_url)

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    products = client.get("/api/v1/products").json()["items"]
    product_id = next(item["id"] for item in products if item["title"] == "降雪")

    response = client.get(f"/api/v1/products/{product_id}")
    assert response.status_code == 200
    payload = response.json()

    assert payload["id"] == product_id
    assert payload["title"] == "降雪"
    assert payload["text"] == "seeded 降雪"
    assert payload["status"] == "published"
    assert payload["version"] == 1
    assert len(payload["hazards"]) == 1
    hazard = payload["hazards"][0]
    assert hazard["severity"] == "low"
    assert hazard["geometry"]["type"] == "Polygon"
    assert set(hazard["bbox"]) == {"min_x", "min_y", "max_x", "max_y"}


def test_product_detail_endpoint_returns_404_for_missing_product(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products.db'}"
    _seed_products(db_url)

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    response = client.get("/api/v1/products/9999")
    assert response.status_code == 404


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
    payload = response.json()
    assert payload["total"] == 0
    assert payload["items"] == []


def test_products_endpoint_valid_time_filter_excludes_out_of_range_products(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products.db'}"
    _seed_products(db_url)

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    response = client.get(
        "/api/v1/products",
        params={"valid_time": "2026-01-03T00:00:00Z"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 0
    assert payload["items"] == []


def test_products_endpoint_valid_time_filter_includes_in_range_products(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products.db'}"
    _seed_products(db_url)

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    response = client.get(
        "/api/v1/products",
        params={"valid_time": "2026-01-01T12:00:00Z"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert {item["title"] for item in payload["items"]} == {"降雪", "大风", "强降水"}


def test_products_endpoint_type_filter_returns_matching_products(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products.db'}"
    _seed_products(db_url)

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    response = client.get(
        "/api/v1/products",
        params={"type": "降雪"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["title"] == "降雪"


def test_products_endpoint_bbox_filter_can_exclude_by_y_overlap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products.db'}"
    _seed_products(db_url)

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    response = client.get("/api/v1/products", params={"bbox": "126.2,0,126.8,1"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 0
    assert payload["items"] == []


def test_products_endpoint_pagination_slices_results(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products.db'}"
    _seed_products(db_url)

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)

    page_1 = client.get("/api/v1/products", params={"page": 1, "page_size": 2})
    assert page_1.status_code == 200
    payload_1 = page_1.json()
    assert payload_1["page"] == 1
    assert payload_1["page_size"] == 2
    assert payload_1["total"] == 3
    assert len(payload_1["items"]) == 2

    page_2 = client.get("/api/v1/products", params={"page": 2, "page_size": 2})
    assert page_2.status_code == 200
    payload_2 = page_2.json()
    assert payload_2["page"] == 2
    assert payload_2["page_size"] == 2
    assert payload_2["total"] == 3
    assert len(payload_2["items"]) == 1


def test_products_endpoint_is_cached_between_requests(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products.db'}"
    _seed_products(db_url)

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    params = {"type": "降雪", "valid_time": "2026-01-01T12:00:00Z"}

    first = client.get("/api/v1/products", params=params)
    assert first.status_code == 200
    assert first.json()["total"] == 1

    from routers import products as products_router

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("db should not be hit on cache")

    monkeypatch.setattr(products_router, "_query_product_summaries", _boom)

    second = client.get("/api/v1/products", params=params)
    assert second.status_code == 200
    assert second.json()["total"] == 1


def test_products_endpoint_etag_returns_304_on_match(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products.db'}"
    _seed_products(db_url)

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    response = client.get("/api/v1/products")
    assert response.status_code == 200
    etag = response.headers.get("etag")
    assert etag

    cached = client.get("/api/v1/products", headers={"if-none-match": etag})
    assert cached.status_code == 304


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


def test_product_edit_endpoints_require_editor_permissions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products-edit.db'}"
    from models import Base

    Base.metadata.create_all(create_engine(db_url))

    monkeypatch.delenv("ENABLE_EDITOR", raising=False)
    monkeypatch.delenv("EDITOR_TOKEN", raising=False)

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    response = client.post(
        "/api/v1/products",
        json={
            "title": "Draft",
            "issued_at": "2026-01-01T00:00:00Z",
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_to": "2026-01-02T00:00:00Z",
            "hazards": [],
        },
    )
    assert response.status_code == 403


def test_product_edit_flow_creates_versions_and_preserves_snapshots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products-edit.db'}"
    from models import Base

    Base.metadata.create_all(create_engine(db_url))
    monkeypatch.setenv("ENABLE_EDITOR", "1")

    client = _make_client(monkeypatch, tmp_path, db_url=db_url)
    polygon = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 0], [2, 3], [0, 3], [0, 0]]],
    }

    create_payload = {
        "title": "My product",
        "text": "draft text",
        "issued_at": "2026-01-01T00:00:00Z",
        "valid_from": "2026-01-01T00:00:00Z",
        "valid_to": "2026-01-02T00:00:00Z",
        "hazards": [
            {
                "severity": "high",
                "geometry": polygon,
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_to": "2026-01-02T00:00:00Z",
            }
        ],
    }
    created = client.post("/api/v1/products", json=create_payload)
    assert created.status_code == 201
    draft = created.json()
    assert draft["status"] == "draft"
    product_id = draft["id"]

    assert client.get("/api/v1/products").json()["total"] == 0

    published_v1 = client.post(f"/api/v1/products/{product_id}/publish")
    assert published_v1.status_code == 200
    v1 = published_v1.json()
    assert v1["version"] == 1
    assert v1["snapshot"]["status"] == "published"
    assert v1["snapshot"]["text"] == "draft text"

    assert client.get("/api/v1/products").json()["total"] == 1

    versions_v1 = client.get(f"/api/v1/products/{product_id}/versions")
    assert versions_v1.status_code == 200
    items_v1 = versions_v1.json()["items"]
    assert [item["version"] for item in items_v1] == [1]
    assert items_v1[0]["snapshot"]["text"] == "draft text"

    updated = client.put(
        f"/api/v1/products/{product_id}",
        json={"text": "updated text"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "draft"

    assert client.get("/api/v1/products").json()["total"] == 0
    versions_after_update = client.get(
        f"/api/v1/products/{product_id}/versions"
    ).json()["items"]
    assert versions_after_update[-1]["snapshot"]["text"] == "draft text"

    published_v2 = client.post(f"/api/v1/products/{product_id}/publish")
    assert published_v2.status_code == 200
    assert published_v2.json()["version"] == 2

    versions_v2 = client.get(f"/api/v1/products/{product_id}/versions")
    assert versions_v2.status_code == 200
    items_v2 = versions_v2.json()["items"]
    assert [item["version"] for item in items_v2] == [2, 1]
    assert items_v2[1]["snapshot"]["text"] == "draft text"
    assert items_v2[0]["snapshot"]["text"] == "updated text"


def test_product_publish_snapshots_bytes_geometry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products-edit.db'}"
    from models import Base, Product, ProductHazard

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    issued_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with Session(engine) as session:
        product = Product(
            title="Binary hazard",
            text="draft",
            issued_at=issued_at,
            valid_from=issued_at,
            valid_to=issued_at,
            status="draft",
        )
        hazard = ProductHazard(
            severity="low",
            geometry=b"\x01",
            valid_from=issued_at,
            valid_to=issued_at,
            bbox_min_x=1,
            bbox_min_y=1,
            bbox_max_x=1,
            bbox_max_y=1,
        )
        product.hazards.append(hazard)
        session.add(product)
        session.commit()
        product_id = product.id

    monkeypatch.setenv("ENABLE_EDITOR", "1")
    client = _make_client(monkeypatch, tmp_path, db_url=db_url)

    response = client.post(f"/api/v1/products/{product_id}/publish")
    assert response.status_code == 200
    payload = response.json()
    geometry_snapshot = payload["snapshot"]["hazards"][0]["geometry"]
    assert geometry_snapshot["encoding"] == "base64"
    assert geometry_snapshot["data"]


def test_product_create_rejects_invalid_geometry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products-edit.db'}"
    from models import Base

    Base.metadata.create_all(create_engine(db_url))
    monkeypatch.setenv("ENABLE_EDITOR", "1")
    client = _make_client(monkeypatch, tmp_path, db_url=db_url)

    response = client.post(
        "/api/v1/products",
        json={
            "title": "Invalid hazard",
            "issued_at": "2026-01-01T00:00:00Z",
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_to": "2026-01-02T00:00:00Z",
            "hazards": [
                {
                    "severity": "low",
                    "geometry": {"type": "Point"},
                    "valid_from": "2026-01-01T00:00:00Z",
                    "valid_to": "2026-01-02T00:00:00Z",
                }
            ],
        },
    )
    assert response.status_code == 400


def test_product_update_rejects_null_title(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'products-edit.db'}"
    from models import Base

    Base.metadata.create_all(create_engine(db_url))
    monkeypatch.setenv("ENABLE_EDITOR", "1")
    client = _make_client(monkeypatch, tmp_path, db_url=db_url)

    created = client.post(
        "/api/v1/products",
        json={
            "title": "Draft",
            "issued_at": "2026-01-01T00:00:00Z",
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_to": "2026-01-02T00:00:00Z",
            "hazards": [],
        },
    )
    product_id = created.json()["id"]

    updated = client.put(f"/api/v1/products/{product_id}", json={"title": None})
    assert updated.status_code == 400
