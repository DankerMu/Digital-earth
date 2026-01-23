from __future__ import annotations

import json
from datetime import datetime, timezone
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


def _make_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, db_url: str
) -> tuple[TestClient, FakeRedis]:
    monkeypatch.chdir(tmp_path)

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

    from models import Base

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    redis = FakeRedis(use_real_time=False)
    monkeypatch.setattr(main_module, "create_redis_client", lambda _url: redis)
    return TestClient(main_module.create_app()), redis


def _seed_risk_pois(db_url: str) -> None:
    from models import Base, RiskPOI

    engine = create_engine(db_url)
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
                    lat=35.5,
                    alt=12.0,
                    weight=0.5,
                    tags=None,
                ),
                RiskPOI(
                    name="poi-c",
                    poi_type="fire",
                    lon=112.0,
                    lat=36.0,
                    alt=0.0,
                    weight=2.0,
                    tags=["edge"],
                ),
                RiskPOI(
                    name="poi-outside",
                    poi_type="fire",
                    lon=140.0,
                    lat=10.0,
                    alt=0.0,
                    weight=1.0,
                    tags=None,
                ),
            ]
        )
        session.commit()
    engine.dispose()


def _seed_many_risk_pois(db_url: str, *, count: int) -> None:
    from models import Base, RiskPOI

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                RiskPOI(
                    name=f"poi-{idx:04d}",
                    poi_type="fire",
                    lon=109.1 + idx * 1e-4,
                    lat=34.1,
                    alt=None,
                    weight=1.0,
                    tags=None,
                )
                for idx in range(1, int(count) + 1)
            ]
        )
        session.commit()
    engine.dispose()


def _seed_risk_pois_for_clustering(db_url: str) -> None:
    from models import Base, RiskPOI

    engine = create_engine(db_url)
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
                    tags=None,
                ),
                RiskPOI(
                    name="poi-b",
                    poi_type="fire",
                    lon=110.0001,
                    lat=35.0001,
                    alt=None,
                    weight=1.0,
                    tags=None,
                ),
                RiskPOI(
                    name="poi-c",
                    poi_type="fire",
                    lon=110.0002,
                    lat=35.0002,
                    alt=None,
                    weight=1.0,
                    tags=None,
                ),
                RiskPOI(
                    name="poi-d",
                    poi_type="flood",
                    lon=111.0,
                    lat=36.0,
                    alt=None,
                    weight=1.0,
                    tags=None,
                ),
            ]
        )
        session.commit()
    engine.dispose()


def _seed_products_and_risk_poi_evaluations(db_url: str) -> int:
    from models import Base, Product, RiskPOIEvaluation

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        product = Product(
            title="test-product",
            text=None,
            issued_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            valid_from=datetime(2024, 1, 1, tzinfo=timezone.utc),
            valid_to=datetime(2024, 1, 2, tzinfo=timezone.utc),
            version=1,
            status="published",
        )
        session.add(product)
        session.flush()

        session.add_all(
            [
                RiskPOIEvaluation(
                    poi_id=1,
                    product_id=int(product.id),
                    valid_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    risk_level=4,
                ),
                RiskPOIEvaluation(
                    poi_id=3,
                    product_id=int(product.id),
                    valid_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    risk_level=2,
                ),
            ]
        )
        session.commit()

        product_id = int(product.id)

    engine.dispose()
    return product_id


def test_risk_pois_bbox_filter_and_pagination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_risk_pois(db_url)
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    params = {"bbox": "109,34,112,36", "page": 1, "page_size": 2}
    first = client.get("/api/v1/risk/pois", params=params)
    assert first.status_code == 200

    payload = first.json()
    assert payload["page"] == 1
    assert payload["page_size"] == 2
    assert payload["total"] == 3
    assert [item["name"] for item in payload["items"]] == ["poi-a", "poi-b"]
    assert all(item["risk_level"] is None for item in payload["items"])

    second = client.get(
        "/api/v1/risk/pois",
        params={"bbox": "109,34,112,36", "page": 2, "page_size": 2},
    )
    assert second.status_code == 200
    payload2 = second.json()
    assert payload2["total"] == 3
    assert [item["name"] for item in payload2["items"]] == ["poi-c"]


def test_risk_pois_product_and_valid_time_lookup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_risk_pois(db_url)
    product_id = _seed_products_and_risk_poi_evaluations(db_url)
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    response = client.get(
        "/api/v1/risk/pois",
        params={
            "bbox": "109,34,112,36",
            "product_id": product_id,
            "valid_time": "2024-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3

    by_name = {item["name"]: item for item in payload["items"]}
    assert by_name["poi-a"]["risk_level"] == 4
    assert by_name["poi-b"]["risk_level"] is None
    assert by_name["poi-c"]["risk_level"] == 2


def test_risk_pois_requires_product_id_and_valid_time_together(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_risk_pois(db_url)
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    missing_time = client.get(
        "/api/v1/risk/pois",
        params={"bbox": "109,34,112,36", "product_id": 1},
    )
    assert missing_time.status_code == 400
    assert missing_time.json()["error_code"] == 40000

    missing_product = client.get(
        "/api/v1/risk/pois",
        params={"bbox": "109,34,112,36", "valid_time": "2024-01-01T00:00:00Z"},
    )
    assert missing_product.status_code == 400
    assert missing_product.json()["error_code"] == 40000


def test_risk_pois_cache_hit_skips_db_queries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_risk_pois(db_url)
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    first = client.get(
        "/api/v1/risk/pois", params={"bbox": "109,34,112,36", "page": 1, "page_size": 2}
    )
    assert first.status_code == 200
    etag = first.headers.get("etag")
    assert etag is not None

    import db as db_module

    def _boom() -> None:
        raise AssertionError("db.get_engine() should not be called on cache hit")

    monkeypatch.setattr(db_module, "get_engine", _boom)

    cached = client.get(
        "/api/v1/risk/pois", params={"bbox": "109,34,112,36", "page": 1, "page_size": 2}
    )
    assert cached.status_code == 200
    assert cached.headers.get("etag") == etag
    assert cached.json() == first.json()


def test_risk_pois_lookup_does_not_cache_unknown_results(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_risk_pois(db_url)
    product_id = _seed_products_and_risk_poi_evaluations(db_url)
    client, redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    response = client.get(
        "/api/v1/risk/pois",
        params={
            "bbox": "109,34,112,36",
            "product_id": product_id,
            "valid_time": "2024-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "public, max-age=5"

    identity = (
        f"{109.0!r},{34.0!r},{112.0!r},{36.0!r}"
        f":page=1:size=100:product={product_id}:time=20240101T000000Z"
    )
    fresh_key = f"risk:pois:fresh:{identity}"
    stale_key = f"risk:pois:stale:{identity}"

    assert fresh_key not in redis.values
    assert stale_key not in redis.values


def test_risk_pois_lookup_caches_fully_known_results_with_short_ttl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_risk_pois(db_url)
    product_id = _seed_products_and_risk_poi_evaluations(db_url)

    from models import RiskPOIEvaluation

    engine = create_engine(db_url)
    with Session(engine) as session:
        session.add(
            RiskPOIEvaluation(
                poi_id=2,
                product_id=int(product_id),
                valid_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                risk_level=1,
            )
        )
        session.commit()
    engine.dispose()

    client, redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    first = client.get(
        "/api/v1/risk/pois",
        params={
            "bbox": "109,34,112,36",
            "product_id": product_id,
            "valid_time": "2024-01-01T00:00:00Z",
        },
    )
    assert first.status_code == 200
    assert first.headers.get("cache-control") == "public, max-age=5"

    identity = (
        f"{109.0!r},{34.0!r},{112.0!r},{36.0!r}"
        f":page=1:size=100:product={product_id}:time=20240101T000000Z"
    )
    fresh_key = f"risk:pois:fresh:{identity}"
    stale_key = f"risk:pois:stale:{identity}"

    assert fresh_key in redis.values
    assert stale_key in redis.values
    assert redis.expires_at[fresh_key] - redis.now() == 5.0
    assert redis.expires_at[stale_key] - redis.now() == 60.0

    import db as db_module

    def _boom() -> None:
        raise AssertionError("db.get_engine() should not be called on cache hit")

    monkeypatch.setattr(db_module, "get_engine", _boom)

    cached = client.get(
        "/api/v1/risk/pois",
        params={
            "bbox": "109,34,112,36",
            "product_id": product_id,
            "valid_time": "2024-01-01T00:00:00Z",
        },
    )
    assert cached.status_code == 200
    assert cached.json() == first.json()


def test_risk_pois_lookup_chunks_poi_ids_for_sqlite_variable_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_many_risk_pois(db_url, count=1000)
    product_id = _seed_products_and_risk_poi_evaluations(db_url)
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    response = client.get(
        "/api/v1/risk/pois",
        params={
            "bbox": "109,34,112,36",
            "page": 1,
            "page_size": 1000,
            "product_id": product_id,
            "valid_time": "2024-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1000
    assert len(payload["items"]) == 1000


def test_risk_pois_without_redis_returns_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_risk_pois(db_url)
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)
    client.app.state.redis_client = None

    response = client.get("/api/v1/risk/pois", params={"bbox": "109,34,112,36"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert len(payload["items"]) == 3


def test_risk_pois_if_none_match_returns_304(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_risk_pois(db_url)
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    first = client.get("/api/v1/risk/pois", params={"bbox": "109,34,112,36"})
    assert first.status_code == 200
    etag = first.headers["etag"]

    cached = client.get(
        "/api/v1/risk/pois",
        params={"bbox": "109,34,112,36"},
        headers={"If-None-Match": etag},
    )
    assert cached.status_code == 304
    assert cached.headers["etag"] == etag
    assert cached.text == ""


def test_risk_pois_invalid_bbox_returns_400(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_risk_pois(db_url)
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    response = client.get("/api/v1/risk/pois", params={"bbox": "bad"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == 40000
    assert "trace_id" in payload


@pytest.mark.parametrize(
    "bbox",
    [
        "nan,0,1,1",
        "0,nan,1,1",
        "0,0,inf,1",
        "0,0,1,inf",
        "-inf,0,1,1",
    ],
)
def test_risk_pois_bbox_rejects_non_finite_numbers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bbox: str
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_risk_pois(db_url)
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    response = client.get("/api/v1/risk/pois", params={"bbox": bbox})
    assert response.status_code == 400
    payload = response.json()
    assert payload["message"] == "bbox values must be finite numbers"


@pytest.mark.parametrize(
    "bbox,message",
    [
        ("-181,0,1,1", "bbox lon must be between -180 and 180"),
        ("0,0,181,1", "bbox lon must be between -180 and 180"),
        ("0,-91,1,1", "bbox lat must be between -90 and 90"),
        ("0,0,1,91", "bbox lat must be between -90 and 90"),
    ],
)
def test_risk_pois_bbox_rejects_out_of_range_coords(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bbox: str, message: str
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_risk_pois(db_url)
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    response = client.get("/api/v1/risk/pois", params={"bbox": bbox})
    assert response.status_code == 400
    payload = response.json()
    assert payload["message"] == message


def test_risk_pois_page_upper_bound_is_enforced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_risk_pois(db_url)
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    ok = client.get(
        "/api/v1/risk/pois",
        params={"bbox": "109,34,112,36", "page": 1000, "page_size": 1},
    )
    assert ok.status_code == 200

    too_high = client.get(
        "/api/v1/risk/pois",
        params={"bbox": "109,34,112,36", "page": 1001, "page_size": 1},
    )
    assert too_high.status_code == 400


def test_risk_pois_http_exception_is_not_retried_after_cache_layer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_risk_pois(db_url)
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    import routers.risk as risk_module

    calls: list[object] = []

    def _boom(
        *,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
        page: int,
        page_size: int,
        product_id: int | None = None,
        valid_time: object | None = None,
    ) -> None:
        calls.append(
            {
                "min_lon": min_lon,
                "min_lat": min_lat,
                "max_lon": max_lon,
                "max_lat": max_lat,
                "page": page,
                "page_size": page_size,
            }
        )
        raise risk_module.HTTPException(
            status_code=503, detail="Risk POI database unavailable"
        )

    monkeypatch.setattr(risk_module, "_query_risk_pois", _boom)

    response = client.get("/api/v1/risk/pois", params={"bbox": "109,34,112,36"})
    assert response.status_code == 503
    assert len(calls) == 1


def test_risk_pois_cluster_low_zoom_groups_points(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_risk_pois_for_clustering(db_url)
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    response = client.get(
        "/api/v1/risk/pois/cluster",
        params={"bbox": "109,34,112,37", "zoom": 10},
    )
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"clusters"}
    clusters = payload["clusters"]
    assert len(clusters) == 2

    cluster_counts = sorted(item["count"] for item in clusters)
    assert cluster_counts == [1, 3]

    trio = next(item for item in clusters if item["count"] == 3)
    assert trio["poi_ids"] == [1, 2, 3]
    assert abs(trio["lon"] - 110.0001) < 1e-6
    assert abs(trio["lat"] - 35.0001) < 1e-6


def test_risk_pois_cluster_high_zoom_returns_singletons(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_risk_pois_for_clustering(db_url)
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    response = client.get(
        "/api/v1/risk/pois/cluster",
        params={"bbox": "109,34,112,37", "zoom": 14},
    )
    assert response.status_code == 200
    payload = response.json()
    clusters = payload["clusters"]
    assert len(clusters) == 4
    assert [item["count"] for item in clusters] == [1, 1, 1, 1]
    assert [item["poi_ids"] for item in clusters] == [[1], [2], [3], [4]]


def test_risk_pois_cluster_without_redis_returns_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_risk_pois_for_clustering(db_url)
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)
    client.app.state.redis_client = None

    response = client.get(
        "/api/v1/risk/pois/cluster",
        params={"bbox": "109,34,112,37", "zoom": 10},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["clusters"]


def test_risk_pois_cluster_empty_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_risk_pois_for_clustering(db_url)
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    response = client.get(
        "/api/v1/risk/pois/cluster",
        params={"bbox": "0,0,1,1", "zoom": 10},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["clusters"] == []


def test_risk_pois_cluster_cache_hit_skips_db_queries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_risk_pois_for_clustering(db_url)
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    first = client.get(
        "/api/v1/risk/pois/cluster",
        params={"bbox": "109,34,112,37", "zoom": 10},
    )
    assert first.status_code == 200
    etag = first.headers.get("etag")
    assert etag is not None

    import db as db_module

    def _boom() -> None:
        raise AssertionError("db.get_engine() should not be called on cache hit")

    monkeypatch.setattr(db_module, "get_engine", _boom)

    cached = client.get(
        "/api/v1/risk/pois/cluster",
        params={"bbox": "109,34,112,37", "zoom": 10},
    )
    assert cached.status_code == 200
    assert cached.headers.get("etag") == etag
    assert cached.json() == first.json()


def test_risk_pois_cluster_if_none_match_returns_304(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_risk_pois_for_clustering(db_url)
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    first = client.get(
        "/api/v1/risk/pois/cluster",
        params={"bbox": "109,34,112,37", "zoom": 10},
    )
    assert first.status_code == 200
    etag = first.headers["etag"]

    cached = client.get(
        "/api/v1/risk/pois/cluster",
        params={"bbox": "109,34,112,37", "zoom": 10},
        headers={"If-None-Match": etag},
    )
    assert cached.status_code == 304
    assert cached.headers["etag"] == etag
    assert cached.text == ""


def test_risk_pois_cluster_invalid_bbox_returns_400(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_risk_pois_for_clustering(db_url)
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    response = client.get(
        "/api/v1/risk/pois/cluster",
        params={"bbox": "bad", "zoom": 10},
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == 40000
    assert "trace_id" in payload


def test_risk_pois_cluster_zoom_upper_bound_is_enforced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'risk.db'}"
    _seed_risk_pois_for_clustering(db_url)
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    response = client.get(
        "/api/v1/risk/pois/cluster",
        params={"bbox": "109,34,112,37", "zoom": 23},
    )
    assert response.status_code == 400
