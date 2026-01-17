from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from digital_earth_config import ApiRateLimitRule, ApiRateLimitSettings
from fastapi import FastAPI
from fastapi.testclient import TestClient

from observability import TraceIdMiddleware
from rate_limit import RateLimitMiddleware


@dataclass
class FakeRedis:
    zsets: dict[str, list[int]] = field(default_factory=dict)
    calls: int = 0

    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object:
        self.calls += 1
        assert numkeys == 1

        key = str(keys_and_args[0])
        now_ms = int(keys_and_args[1])
        window_ms = int(keys_and_args[2])
        limit = int(keys_and_args[3])

        entries = self.zsets.setdefault(key, [])
        threshold = now_ms - window_ms
        entries = [item for item in entries if item > threshold]
        self.zsets[key] = entries

        if len(entries) < limit:
            entries.append(now_ms)
            entries.sort()
            return [1, 0]

        oldest = entries[0] if entries else now_ms
        retry_after_ms = oldest + window_ms - now_ms
        return [0, max(0, retry_after_ms)]


class BrokenRedis:
    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object:
        raise RuntimeError("redis down")


@dataclass
class Clock:
    now: int

    def __call__(self) -> int:
        return self.now


def _make_app(
    *, config: ApiRateLimitSettings, redis_client: object, clock: Clock
) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        config=config,
        redis_client=redis_client,
        now_ms=clock,
    )
    app.add_middleware(TraceIdMiddleware)
    return app


def test_rate_limit_returns_429_with_retry_after() -> None:
    clock = Clock(now=1_000_000)
    redis = FakeRedis()
    config = ApiRateLimitSettings(
        rules=[ApiRateLimitRule(path_prefix="/api/v1/catalog", requests_per_minute=1)]
    )
    app = _make_app(config=config, redis_client=redis, clock=clock)
    hit_counter = {"count": 0}

    @app.get("/api/v1/catalog/items")
    def catalog_items() -> dict[str, bool]:
        hit_counter["count"] += 1
        return {"ok": True}

    client = TestClient(app)
    headers = {"X-Forwarded-For": "203.0.113.10"}

    ok = client.get("/api/v1/catalog/items", headers=headers)
    assert ok.status_code == 200
    assert hit_counter["count"] == 1

    blocked = client.get("/api/v1/catalog/items", headers=headers)
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "60"
    assert hit_counter["count"] == 1

    trace_id = blocked.headers["X-Trace-Id"]
    payload = blocked.json()
    assert payload["trace_id"] == trace_id
    assert payload["message"] == "Too Many Requests"


def test_rate_limit_sliding_window_allows_after_window() -> None:
    clock = Clock(now=1_000_000)
    redis = FakeRedis()
    config = ApiRateLimitSettings(
        rules=[
            ApiRateLimitRule(
                path_prefix="/api/v1/catalog",
                requests_per_minute=1,
                window_seconds=60,
            )
        ]
    )
    app = _make_app(config=config, redis_client=redis, clock=clock)
    hit_counter = {"count": 0}

    @app.get("/api/v1/catalog/items")
    def catalog_items() -> dict[str, bool]:
        hit_counter["count"] += 1
        return {"ok": True}

    client = TestClient(app)
    headers = {"X-Forwarded-For": "203.0.113.10"}

    assert client.get("/api/v1/catalog/items", headers=headers).status_code == 200
    assert client.get("/api/v1/catalog/items", headers=headers).status_code == 429

    clock.now += 60_001
    assert client.get("/api/v1/catalog/items", headers=headers).status_code == 200
    assert hit_counter["count"] == 2


def test_ip_blocklist_returns_403() -> None:
    clock = Clock(now=1_000_000)
    redis = FakeRedis()
    config = ApiRateLimitSettings(
        ip_blocklist=["203.0.113.0/24"],
        rules=[ApiRateLimitRule(path_prefix="/api/v1/catalog", requests_per_minute=10)],
    )
    app = _make_app(config=config, redis_client=redis, clock=clock)
    hit_counter = {"count": 0}

    @app.get("/api/v1/catalog/items")
    def catalog_items() -> dict[str, bool]:
        hit_counter["count"] += 1
        return {"ok": True}

    client = TestClient(app)
    response = client.get(
        "/api/v1/catalog/items", headers={"X-Forwarded-For": "203.0.113.10"}
    )

    assert response.status_code == 403
    assert "Retry-After" not in response.headers
    assert hit_counter["count"] == 0


def test_ip_allowlist_bypasses_rate_limit() -> None:
    clock = Clock(now=1_000_000)
    redis = FakeRedis()
    config = ApiRateLimitSettings(
        ip_allowlist=["203.0.113.10"],
        rules=[ApiRateLimitRule(path_prefix="/api/v1/catalog", requests_per_minute=1)],
    )
    app = _make_app(config=config, redis_client=redis, clock=clock)
    hit_counter = {"count": 0}

    @app.get("/api/v1/catalog/items")
    def catalog_items() -> dict[str, bool]:
        hit_counter["count"] += 1
        return {"ok": True}

    client = TestClient(app)
    headers = {"X-Forwarded-For": "203.0.113.10"}

    assert client.get("/api/v1/catalog/items", headers=headers).status_code == 200
    assert client.get("/api/v1/catalog/items", headers=headers).status_code == 200
    assert hit_counter["count"] == 2


def test_unmatched_path_does_not_hit_redis() -> None:
    clock = Clock(now=1_000_000)
    redis = FakeRedis()
    config = ApiRateLimitSettings(
        rules=[ApiRateLimitRule(path_prefix="/api/v1/catalog", requests_per_minute=1)]
    )
    app = _make_app(config=config, redis_client=redis, clock=clock)

    @app.get("/api/v1/catalogue/items")
    def catalogue_items() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    response = client.get(
        "/api/v1/catalogue/items", headers={"X-Forwarded-For": "203.0.113.10"}
    )
    assert response.status_code == 200
    assert redis.calls == 0


@pytest.mark.parametrize("header", ["203.0.113.10:1234", "[203.0.113.10]:1234"])
def test_client_ip_parses_port_variants(header: str) -> None:
    clock = Clock(now=1_000_000)
    redis = FakeRedis()
    config = ApiRateLimitSettings(
        rules=[ApiRateLimitRule(path_prefix="/api/v1/catalog", requests_per_minute=1)]
    )
    app = _make_app(config=config, redis_client=redis, clock=clock)

    @app.get("/api/v1/catalog/items")
    def catalog_items() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    assert (
        client.get("/api/v1/catalog/items", headers={"X-Real-Ip": header}).status_code
        == 200
    )


def test_redis_errors_return_503() -> None:
    clock = Clock(now=1_000_000)
    config = ApiRateLimitSettings(
        rules=[ApiRateLimitRule(path_prefix="/api/v1/catalog", requests_per_minute=1)]
    )
    app = _make_app(config=config, redis_client=BrokenRedis(), clock=clock)

    @app.get("/api/v1/catalog/items")
    def catalog_items() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    response = client.get(
        "/api/v1/catalog/items", headers={"X-Forwarded-For": "203.0.113.10"}
    )
    assert response.status_code == 503
    assert response.json()["message"] == "Rate limiter unavailable"
