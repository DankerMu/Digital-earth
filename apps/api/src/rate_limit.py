from __future__ import annotations

import ipaddress
import logging
import math
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Protocol

from digital_earth_config import ApiRateLimitSettings
from observability import make_api_error
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

try:
    from redis.asyncio import Redis
except ModuleNotFoundError:  # pragma: no cover
    Redis = object  # type: ignore[assignment]


class RedisLike(Protocol):
    async def eval(
        self, script: str, numkeys: int, *keys_and_args: object
    ) -> object: ...


_SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, 0, now - window)

local count = tonumber(redis.call('ZCARD', key))
if count < limit then
  redis.call('ZADD', key, now, member)
  redis.call('PEXPIRE', key, window)
  return {1, 0}
end

local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local oldest_score = tonumber(oldest[2]) or now
redis.call('PEXPIRE', key, window)

local retry_after_ms = oldest_score + window - now
if retry_after_ms < 0 then
  retry_after_ms = 0
end

return {0, retry_after_ms}
"""


def create_redis_client(redis_url: str) -> LazyRedisClient:
    return LazyRedisClient(redis_url)


class LazyRedisClient:
    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: Redis | None = None

    async def connect(self) -> None:
        if self._client is not None:
            return
        if Redis is object:  # pragma: no cover
            raise RuntimeError("redis dependency is required for rate limiting")
        self._client = Redis.from_url(self._redis_url, decode_responses=False)

    def _require(self) -> Redis:
        if self._client is None:  # pragma: no cover
            raise RuntimeError("Redis client is not connected yet")
        return self._client

    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object:
        return await self._require().eval(script, numkeys, *keys_and_args)

    async def get(self, key: str) -> bytes | None:
        return await self._require().get(key)

    async def set(
        self,
        key: str,
        value: bytes,
        *,
        ex: int | None = None,
        px: int | None = None,
        nx: bool = False,
    ) -> object:
        return await self._require().set(key, value, ex=ex, px=px, nx=nx)

    async def delete(self, *keys: str) -> int:
        return await self._require().delete(*keys)

    async def close(self) -> None:
        if self._client is None:
            return
        await self._client.close()
        self._client = None


def _now_ms() -> int:
    return int(time.time() * 1000)


def _path_matches_prefix(path: str, prefix: str) -> bool:
    if prefix == "/":
        return True
    return path == prefix or path.startswith(prefix + "/")


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


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int | None = None


class SlidingWindowRedisRateLimiter:
    def __init__(
        self,
        redis_client: RedisLike,
        *,
        key_prefix: str = "rate_limit",
        now_ms: Callable[[], int] = _now_ms,
    ) -> None:
        self.redis = redis_client
        self.key_prefix = key_prefix
        self.now_ms = now_ms

    async def allow(
        self, *, bucket: str, client_id: str, limit: int, window_s: int
    ) -> RateLimitResult:
        now_ms = self.now_ms()
        window_ms = window_s * 1000
        key = f"{self.key_prefix}:{bucket}:{client_id}"
        member = f"{now_ms}:{uuid.uuid4().hex}"

        raw = await self.redis.eval(
            _SLIDING_WINDOW_SCRIPT,
            1,
            key,
            now_ms,
            window_ms,
            limit,
            member,
        )
        allowed, retry_after_ms = _parse_redis_script_result(raw)
        if allowed:
            return RateLimitResult(allowed=True)

        retry_after_seconds = max(1, math.ceil(retry_after_ms / 1000))
        return RateLimitResult(allowed=False, retry_after_seconds=retry_after_seconds)


def _parse_redis_script_result(raw: object) -> tuple[bool, int]:
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:  # pragma: no cover
        raise ValueError(f"Unexpected Redis script result: {raw!r}")
    allowed_raw = raw[0]
    retry_raw = raw[1]

    allowed = int(allowed_raw) == 1
    retry_after_ms = int(retry_raw)
    return allowed, max(0, retry_after_ms)


class RateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        config: ApiRateLimitSettings,
        redis_client: RedisLike,
        now_ms: Callable[[], int] = _now_ms,
    ) -> None:
        self.app = app
        self.config = config
        self.limiter = SlidingWindowRedisRateLimiter(redis_client, now_ms=now_ms)
        self.logger = logging.getLogger("api.rate_limit")

        self.trusted_proxies = _parse_ip_networks(config.trusted_proxies)
        self.allowlist = _parse_ip_networks(config.ip_allowlist)
        self.blocklist = _parse_ip_networks(config.ip_blocklist)
        self.rules = sorted(
            config.rules, key=lambda rule: len(rule.path_prefix), reverse=True
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.config.enabled:
            await self.app(scope, receive, send)
            return

        path = (scope.get("path") or "").rstrip("/") or "/"
        if path == "/health":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        socket_ip = _client_ip_from_scope(scope)
        client_ip = socket_ip

        if self.config.trust_proxy_headers and _ip_in_networks(
            socket_ip, self.trusted_proxies
        ):
            forwarded_ip = _client_ip_from_headers(headers)
            if forwarded_ip is not None:
                client_ip = forwarded_ip

        if _ip_in_networks(client_ip, self.blocklist):
            response = JSONResponse(
                status_code=403,
                content=_error_payload(status_code=403, message="Forbidden"),
            )
            await response(scope, receive, send)
            return

        if _ip_in_networks(client_ip, self.allowlist):
            await self.app(scope, receive, send)
            return

        rule = next(
            (
                item
                for item in self.rules
                if _path_matches_prefix(path, item.path_prefix)
            ),
            None,
        )
        if rule is None:
            await self.app(scope, receive, send)
            return

        bucket = rule.path_prefix.strip("/").replace("/", ":") or "root"
        try:
            result = await self.limiter.allow(
                bucket=bucket,
                client_id=client_ip,
                limit=rule.requests_per_minute,
                window_s=rule.window_seconds,
            )
        except Exception:
            self.logger.exception(
                "rate_limit.redis_error",
                extra={"client_ip": client_ip, "path": path, "bucket": bucket},
            )
            response = JSONResponse(
                status_code=503,
                content=_error_payload(
                    status_code=503, message="Rate limiter unavailable"
                ),
            )
            await response(scope, receive, send)
            return

        if result.allowed:
            await self.app(scope, receive, send)
            return

        retry_after = result.retry_after_seconds or rule.window_seconds
        response = JSONResponse(
            status_code=429,
            content=_error_payload(status_code=429, message="Too Many Requests"),
            headers={"Retry-After": str(retry_after)},
        )
        await response(scope, receive, send)


def _error_payload(
    *, status_code: int, message: str | None = None
) -> dict[str, object]:
    api_error = make_api_error(status_code=status_code, message=message)
    return {
        "error_code": api_error.error_code,
        "message": api_error.message,
        "trace_id": api_error.trace_id,
    }
