from __future__ import annotations

import ipaddress
import os
import secrets
import time
from dataclasses import dataclass
from typing import Callable, Final, Iterable

from digital_earth_config import ApiRateLimitSettings
from observability import make_api_error
from rate_limit import RedisLike, SlidingWindowRedisRateLimiter
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_EDIT_METHODS: Final[set[str]] = {"POST", "PUT", "PATCH", "DELETE"}
_DEFAULT_EDIT_PATH_PREFIXES: Final[tuple[str, ...]] = (
    "/api/v1/products",
    "/api/v1/vector",
)

_DEFAULT_RATE_LIMIT_REQUESTS_PER_MINUTE: Final[int] = 10
_DEFAULT_RATE_LIMIT_WINDOW_SECONDS: Final[int] = 60


def _now_ms() -> int:
    return int(time.time() * 1000)


def _parse_bool_env(name: str) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return False

    normalized = raw.strip().lower()
    if normalized == "":
        return False

    truthy = {"1", "true", "yes", "y", "on"}
    falsy = {"0", "false", "no", "n", "off"}
    if normalized in truthy:
        return True
    if normalized in falsy:
        return False
    raise ValueError(
        f"Invalid {name}={raw!r}; expected one of: {', '.join(sorted(truthy | falsy))}"
    )


def _parse_token_env(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    token = raw.strip()
    return token or None


@dataclass(frozen=True)
class EditorPermissionsConfig:
    enabled: bool
    token: str | None


def get_editor_permissions_config() -> EditorPermissionsConfig:
    return EditorPermissionsConfig(
        enabled=_parse_bool_env("ENABLE_EDITOR"),
        token=_parse_token_env("EDITOR_TOKEN"),
    )


def _path_matches_prefix(path: str, prefix: str) -> bool:
    if prefix == "/":
        return True
    return path == prefix or path.startswith(prefix + "/")


def _is_edit_request(
    *, path: str, method: str, protected_prefixes: Iterable[str]
) -> str | None:
    if method.upper() not in _EDIT_METHODS:
        return None

    normalized = (path or "").rstrip("/") or "/"
    for prefix in protected_prefixes:
        if _path_matches_prefix(normalized, prefix.rstrip("/") or "/"):
            return prefix
    return None


def _strip_port(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("[") and "]" in stripped:
        host = stripped[1 : stripped.index("]")]
        return host

    if stripped.count(":") == 1:
        host, port = stripped.rsplit(":", 1)
        if port.isdigit():
            return host
    return stripped


def _canonicalize_ip(value: str) -> str | None:
    host = _strip_port(value)
    if not host:
        return None
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


def _client_ip_from_headers(headers: Headers) -> str | None:
    xff = headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        return _canonicalize_ip(first)
    x_real_ip = headers.get("x-real-ip")
    if x_real_ip:
        return _canonicalize_ip(x_real_ip)
    return None


def _client_ip_from_scope(scope: Scope) -> str:
    client = scope.get("client")
    if not client:
        return "unknown"
    host, _port = client
    return host or "unknown"


def _parse_ip_networks(entries: list[str]) -> list[ipaddress._BaseNetwork]:
    networks: list[ipaddress._BaseNetwork] = []
    for entry in entries:
        stripped = (entry or "").strip()
        if not stripped:
            continue
        networks.append(ipaddress.ip_network(stripped, strict=False))
    return networks


def _ip_in_networks(ip: str, networks: list[ipaddress._BaseNetwork]) -> bool:
    if not networks:
        return False
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(address in network for network in networks)


def _parse_bearer_token(value: str | None) -> str | None:
    if value is None:
        return None
    raw = value.strip()
    if raw == "":
        return None

    parts = raw.split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts[0], parts[1]
    if scheme.lower() != "bearer":
        return None

    token = token.strip()
    if token == "":
        return None
    return token


def _extract_token(headers: Headers) -> str | None:
    bearer = _parse_bearer_token(headers.get("authorization"))
    if bearer is not None:
        return bearer
    direct = headers.get("x-editor-token")
    if direct is None:
        return None
    token = direct.strip()
    return token or None


def _error_payload(
    *, status_code: int, message: str | None = None
) -> dict[str, object]:
    api_error = make_api_error(status_code=status_code, message=message)
    return {
        "error_code": api_error.error_code,
        "message": api_error.message,
        "trace_id": api_error.trace_id,
    }


class EditorPermissionsMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        config: ApiRateLimitSettings,
        redis_client: RedisLike,
        permissions: EditorPermissionsConfig,
        now_ms: Callable[[], int] = _now_ms,
        protected_prefixes: tuple[str, ...] = _DEFAULT_EDIT_PATH_PREFIXES,
        requests_per_minute: int = _DEFAULT_RATE_LIMIT_REQUESTS_PER_MINUTE,
        window_seconds: int = _DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
    ) -> None:
        self.app = app
        self.permissions = permissions
        self.protected_prefixes = protected_prefixes
        self.rate_limit_enabled = bool(config.enabled)
        self.requests_per_minute = int(requests_per_minute)
        self.window_seconds = int(window_seconds)

        self.trust_proxy_headers = bool(config.trust_proxy_headers)
        self.trusted_proxies = _parse_ip_networks(config.trusted_proxies)

        self.limiter = SlidingWindowRedisRateLimiter(
            redis_client, key_prefix="edit_rate_limit", now_ms=now_ms
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = (scope.get("path") or "").rstrip("/") or "/"
        method = scope.get("method") or ""
        matched_prefix = _is_edit_request(
            path=path, method=method, protected_prefixes=self.protected_prefixes
        )
        if matched_prefix is None:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if not self.permissions.enabled:
            expected = self.permissions.token
            if expected is None:
                response = JSONResponse(
                    status_code=403,
                    content=_error_payload(status_code=403, message="Forbidden"),
                )
                await response(scope, receive, send)
                return

            provided = _extract_token(headers)
            if provided is None or not secrets.compare_digest(provided, expected):
                response = JSONResponse(
                    status_code=403,
                    content=_error_payload(status_code=403, message="Forbidden"),
                )
                await response(scope, receive, send)
                return

        socket_ip = _client_ip_from_scope(scope)
        client_ip = socket_ip

        if self.trust_proxy_headers and _ip_in_networks(
            socket_ip, self.trusted_proxies
        ):
            forwarded_ip = _client_ip_from_headers(headers)
            if forwarded_ip is not None:
                client_ip = forwarded_ip

        if self.rate_limit_enabled:
            bucket = (
                f"edit:{matched_prefix.strip('/').replace('/', ':') or 'root'}:"
                f"{method.lower()}"
            )
            try:
                result = await self.limiter.allow(
                    bucket=bucket,
                    client_id=client_ip,
                    limit=self.requests_per_minute,
                    window_s=self.window_seconds,
                )
            except Exception:
                response = JSONResponse(
                    status_code=503,
                    content=_error_payload(
                        status_code=503, message="Rate limiter unavailable"
                    ),
                )
                await response(scope, receive, send)
                return

            if not result.allowed:
                retry_after = result.retry_after_seconds or self.window_seconds
                response = JSONResponse(
                    status_code=429,
                    content=_error_payload(
                        status_code=429, message="Too Many Requests"
                    ),
                    headers={"Retry-After": str(retry_after)},
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)
