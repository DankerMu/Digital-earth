from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

logger = logging.getLogger("api.cache")

_LOCK_RELEASE_SCRIPT = """
local key = KEYS[1]
local token = ARGV[1]
if redis.call("get", key) == token then
  return redis.call("del", key)
end
return 0
"""


class RedisBytesClient(Protocol):
    async def get(self, key: str) -> bytes | None: ...

    async def set(
        self,
        key: str,
        value: bytes,
        *,
        ex: int | None = None,
        px: int | None = None,
        nx: bool = False,
    ) -> object: ...

    async def delete(self, *keys: str) -> int: ...

    async def eval(
        self, script: str, numkeys: int, *keys_and_args: object
    ) -> object: ...


@dataclass(frozen=True)
class CacheRecord:
    etag: str
    payload: dict[str, Any]
    schema_version: int = 1

    def to_bytes(self) -> bytes:
        body = {
            "schema_version": self.schema_version,
            "etag": self.etag,
            "payload": self.payload,
        }
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> "CacheRecord":
        decoded = json.loads(raw.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("Invalid cache record")

        schema_version = decoded.get("schema_version", 0)
        if schema_version != 1:
            raise ValueError("Unsupported cache record schema_version")

        etag = decoded.get("etag")
        payload = decoded.get("payload")
        if not isinstance(etag, str) or not isinstance(payload, dict):
            raise ValueError("Invalid cache record fields")
        return cls(etag=etag, payload=payload, schema_version=1)


@dataclass(frozen=True)
class CacheResult:
    record: CacheRecord
    status: str


class StaleRedisCache:
    def __init__(
        self,
        redis: RedisBytesClient,
        *,
        key_prefix: str = "catalog",
        default_ttl_s: int = 60,
        default_stale_ttl_s: int = 24 * 60 * 60,
        lock_ttl_ms: int = 5_000,
        wait_timeout_s: float = 0.4,
    ) -> None:
        self.redis = redis
        self.key_prefix = key_prefix.strip(":") or "catalog"
        self.default_ttl_s = default_ttl_s
        self.default_stale_ttl_s = default_stale_ttl_s
        self.lock_ttl_ms = lock_ttl_ms
        self.wait_timeout_s = wait_timeout_s

    def _key(self, key: str) -> str:
        suffix = key.strip(":")
        return f"{self.key_prefix}:{suffix}" if suffix else self.key_prefix

    async def _safe_get(self, key: str) -> CacheRecord | None:
        try:
            raw = await self.redis.get(key)
        except Exception:  # noqa: BLE001
            logger.exception("catalog_cache.redis_get_failed", extra={"key": key})
            return None
        if raw is None:
            return None
        try:
            return CacheRecord.from_bytes(raw)
        except Exception:  # noqa: BLE001
            logger.exception("catalog_cache.decode_failed", extra={"key": key})
            return None

    async def _safe_set(
        self,
        key: str,
        record: CacheRecord,
        *,
        ttl_s: int | None,
        nx: bool = False,
        px: int | None = None,
    ) -> bool:
        try:
            result = await self.redis.set(
                key,
                record.to_bytes(),
                ex=ttl_s,
                px=px,
                nx=nx,
            )
        except Exception:  # noqa: BLE001
            logger.exception("catalog_cache.redis_set_failed", extra={"key": key})
            return False
        return bool(result)

    async def _safe_set_raw(
        self,
        key: str,
        value: bytes,
        *,
        ttl_s: int | None,
        nx: bool = False,
        px: int | None = None,
    ) -> bool:
        try:
            result = await self.redis.set(
                key,
                value,
                ex=ttl_s,
                px=px,
                nx=nx,
            )
        except Exception:  # noqa: BLE001
            logger.exception("catalog_cache.redis_set_failed", extra={"key": key})
            return False
        return bool(result)

    async def _release_lock(self, key: str, token: str) -> None:
        try:
            await self.redis.eval(_LOCK_RELEASE_SCRIPT, 1, key, token)
        except Exception:  # noqa: BLE001
            logger.exception(
                "catalog_cache.redis_lock_release_failed", extra={"key": key}
            )

    async def set_record(
        self,
        key: str,
        record: CacheRecord,
        *,
        ttl_s: int | None = None,
        stale_ttl_s: int | None = None,
    ) -> None:
        ttl = self.default_ttl_s if ttl_s is None else ttl_s
        stale_ttl = self.default_stale_ttl_s if stale_ttl_s is None else stale_ttl_s
        fresh_key = self._key(key)
        stale_key = f"{fresh_key}:stale"

        await self._safe_set(fresh_key, record, ttl_s=ttl)
        await self._safe_set(stale_key, record, ttl_s=stale_ttl)

    async def get_or_compute(
        self,
        key: str,
        *,
        compute: Callable[[], Awaitable[CacheRecord]],
        ttl_s: int | None = None,
        stale_ttl_s: int | None = None,
    ) -> CacheResult:
        ttl = self.default_ttl_s if ttl_s is None else ttl_s
        stale_ttl = self.default_stale_ttl_s if stale_ttl_s is None else stale_ttl_s

        fresh_key = self._key(key)
        stale_key = f"{fresh_key}:stale"
        lock_key = f"{fresh_key}:lock"

        record = await self._safe_get(fresh_key)
        if record is not None:
            return CacheResult(record=record, status="hit")

        token = uuid.uuid4().hex
        acquired = False
        try:
            acquired = await self._safe_set_raw(
                lock_key,
                token.encode("utf-8"),
                ttl_s=None,
                nx=True,
                px=self.lock_ttl_ms,
            )
            if acquired:
                try:
                    computed = await compute()
                except Exception:  # noqa: BLE001
                    stale = await self._safe_get(stale_key)
                    if stale is not None:
                        return CacheResult(record=stale, status="stale")
                    raise

                await self._safe_set(fresh_key, computed, ttl_s=ttl)
                await self._safe_set(stale_key, computed, ttl_s=stale_ttl)
                return CacheResult(record=computed, status="miss")

            stale = await self._safe_get(stale_key)
            if stale is not None:
                return CacheResult(record=stale, status="stale")

            deadline = asyncio.get_running_loop().time() + self.wait_timeout_s
            sleep_s = 0.01
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(sleep_s)
                record = await self._safe_get(fresh_key)
                if record is not None:
                    return CacheResult(record=record, status="wait")
                sleep_s = min(sleep_s * 2, 0.05)

            computed = await compute()
            await self._safe_set(fresh_key, computed, ttl_s=ttl)
            await self._safe_set(stale_key, computed, ttl_s=stale_ttl)
            return CacheResult(record=computed, status="miss_unlocked")
        finally:
            if acquired:
                await self._release_lock(lock_key, token)
