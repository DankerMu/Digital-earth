from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from digital_earth_config import ApiRateLimitSettings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from editor_permissions import (
    _canonicalize_ip,
    _client_ip_from_headers,
    _client_ip_from_scope,
    _ip_in_networks,
    _is_edit_request,
    _now_ms,
    _parse_bearer_token,
    _parse_ip_networks,
    _path_matches_prefix,
    _strip_port,
    EditorPermissionsConfig,
    EditorPermissionsMiddleware,
    get_editor_permissions_config,
)
from observability import TraceIdMiddleware


@dataclass
class FakeRedis:
    zsets: dict[str, list[int]] = field(default_factory=dict)

    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object:
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


@dataclass
class Clock:
    now: int = 0

    def __call__(self) -> int:
        return self.now


def _make_app(
    *,
    permissions: EditorPermissionsConfig,
    rate_limit_enabled: bool = False,
    clock: Clock | None = None,
    requests_per_minute: int = 10,
) -> FastAPI:
    app = FastAPI()
    redis = FakeRedis()
    config = ApiRateLimitSettings(
        enabled=rate_limit_enabled,
        trusted_proxies=["127.0.0.0/8"],
    )
    app.add_middleware(
        EditorPermissionsMiddleware,
        config=config,
        redis_client=redis,
        permissions=permissions,
        now_ms=clock or Clock(now=0),
        requests_per_minute=requests_per_minute,
    )
    app.add_middleware(TraceIdMiddleware)

    @app.post("/api/v1/vector/prewarm")
    def prewarm() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_editor_permissions_config_parses_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ENABLE_EDITOR", raising=False)
    monkeypatch.delenv("EDITOR_TOKEN", raising=False)
    assert get_editor_permissions_config() == EditorPermissionsConfig(
        enabled=False, token=None
    )

    monkeypatch.setenv("ENABLE_EDITOR", "")
    monkeypatch.setenv("EDITOR_TOKEN", "  ")
    assert get_editor_permissions_config() == EditorPermissionsConfig(
        enabled=False, token=None
    )

    monkeypatch.setenv("ENABLE_EDITOR", "0")
    monkeypatch.setenv("EDITOR_TOKEN", "secret")
    assert get_editor_permissions_config() == EditorPermissionsConfig(
        enabled=False, token="secret"
    )

    monkeypatch.setenv("ENABLE_EDITOR", "yes")
    assert get_editor_permissions_config() == EditorPermissionsConfig(
        enabled=True, token="secret"
    )

    monkeypatch.setenv("ENABLE_EDITOR", "maybe")
    with pytest.raises(ValueError):
        get_editor_permissions_config()


def test_editor_helpers_cover_edge_cases() -> None:
    assert isinstance(_now_ms(), int)
    assert _path_matches_prefix("/anything", "/") is True
    assert (
        _is_edit_request(path="/anything", method="POST", protected_prefixes=["/"])
        == "/"
    )

    assert _strip_port("203.0.113.10:1234") == "203.0.113.10"
    assert _strip_port("[203.0.113.10]:1234") == "203.0.113.10"
    assert _canonicalize_ip("not-an-ip") is None

    assert (
        _client_ip_from_headers(Headers({"x-real-ip": "203.0.113.10"}))
        == "203.0.113.10"
    )
    assert _client_ip_from_scope({"type": "http"}) == "unknown"

    assert len(_parse_ip_networks(["", "  ", "127.0.0.1/32"])) == 1
    assert _ip_in_networks("127.0.0.1", []) is False

    assert _parse_bearer_token("") is None
    assert _parse_bearer_token("Bearer") is None
    assert _parse_bearer_token("Token abc") is None
    assert _parse_bearer_token("Bearer   ") is None


@pytest.mark.anyio
async def test_middleware_passes_through_non_http_scope() -> None:
    called = {"value": False}

    async def app(scope: object, receive: object, send: object) -> None:
        called["value"] = True

    middleware = EditorPermissionsMiddleware(
        app,
        config=ApiRateLimitSettings(enabled=False),
        redis_client=FakeRedis(),
        permissions=EditorPermissionsConfig(enabled=False, token=None),
    )

    async def receive() -> object:
        return {}

    async def send(_message: object) -> None:
        return None

    await middleware({"type": "lifespan"}, receive, send)  # type: ignore[arg-type]
    assert called["value"] is True


def test_edit_rate_limit_redis_failure_returns_503() -> None:
    class BrokenRedis:
        async def eval(
            self, script: str, numkeys: int, *keys_and_args: object
        ) -> object:
            raise RuntimeError("redis down")

    app = FastAPI()
    app.add_middleware(
        EditorPermissionsMiddleware,
        config=ApiRateLimitSettings(enabled=True),
        redis_client=BrokenRedis(),
        permissions=EditorPermissionsConfig(enabled=True, token=None),
        requests_per_minute=1,
    )
    app.add_middleware(TraceIdMiddleware)

    @app.post("/api/v1/vector/prewarm")
    def prewarm() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app, client=("127.0.0.1", 12345))
    response = client.post(
        "/api/v1/vector/prewarm", headers={"X-Forwarded-For": "1.2.3.4"}
    )
    assert response.status_code == 503
    assert response.json()["message"] == "Rate limiter unavailable"


def test_edit_endpoints_return_403_when_disabled() -> None:
    app = _make_app(
        permissions=EditorPermissionsConfig(enabled=False, token=None),
        rate_limit_enabled=True,
    )
    client = TestClient(app, client=("127.0.0.1", 12345))

    response = client.post(
        "/api/v1/vector/prewarm", headers={"X-Forwarded-For": "1.2.3.4"}
    )
    assert response.status_code == 403
    assert response.json()["message"] == "Forbidden"
    assert response.json()["trace_id"] == response.headers["X-Trace-Id"]


def test_edit_endpoints_allow_when_feature_flag_enabled() -> None:
    app = _make_app(permissions=EditorPermissionsConfig(enabled=True, token=None))
    client = TestClient(app, client=("127.0.0.1", 12345))

    response = client.post("/api/v1/vector/prewarm")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.parametrize(
    ("headers", "expected_status"),
    [
        ({}, 403),
        ({"Authorization": "Bearer wrong"}, 403),
        ({"Authorization": "Bearer secret"}, 200),
        ({"X-Editor-Token": "secret"}, 200),
    ],
)
def test_edit_endpoints_require_token_when_configured(
    headers: dict[str, str], expected_status: int
) -> None:
    app = _make_app(
        permissions=EditorPermissionsConfig(enabled=False, token="secret"),
    )
    client = TestClient(app, client=("127.0.0.1", 12345))
    response = client.post("/api/v1/vector/prewarm", headers=headers)
    assert response.status_code == expected_status


def test_edit_endpoints_are_rate_limited() -> None:
    clock = Clock(now=1_000_000)
    app = _make_app(
        permissions=EditorPermissionsConfig(enabled=True, token=None),
        rate_limit_enabled=True,
        clock=clock,
        requests_per_minute=1,
    )
    client = TestClient(app, client=("127.0.0.1", 12345))
    headers = {"X-Forwarded-For": "203.0.113.10"}

    assert client.post("/api/v1/vector/prewarm", headers=headers).status_code == 200
    blocked = client.post("/api/v1/vector/prewarm", headers=headers)
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "60"

    clock.now += 60_001
    assert client.post("/api/v1/vector/prewarm", headers=headers).status_code == 200


def test_token_protected_edit_endpoints_are_rate_limited() -> None:
    clock = Clock(now=1_000_000)
    app = _make_app(
        permissions=EditorPermissionsConfig(enabled=False, token="secret"),
        rate_limit_enabled=True,
        clock=clock,
        requests_per_minute=1,
    )
    client = TestClient(app, client=("127.0.0.1", 12345))
    headers = {"X-Forwarded-For": "203.0.113.10", "Authorization": "Bearer wrong"}

    assert client.post("/api/v1/vector/prewarm", headers=headers).status_code == 403
    blocked = client.post("/api/v1/vector/prewarm", headers=headers)
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "60"
