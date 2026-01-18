from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal, Protocol

logger = logging.getLogger("api.error")


class RedisLike(Protocol):
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

    async def pttl(self, key: str) -> int: ...

    async def eval(
        self, script: str, numkeys: int, *keys_and_args: object
    ) -> object: ...


CacheStatus = Literal["fresh", "computed", "stale"]


@dataclass(frozen=True)
class CacheResult:
    body: bytes
    status: CacheStatus


_RELEASE_LOCK_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("DEL", KEYS[1])
end
return 0
"""

_RENEW_LOCK_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("PEXPIRE", KEYS[1], ARGV[2])
end
return 0
"""


def _coerce_bytes(value: str | bytes) -> bytes:
    if isinstance(value, bytes):
        return value
    return value.encode("utf-8")


def _pick_cooldown_seconds(cooldown_ttl_seconds: int | tuple[int, int]) -> int:
    if isinstance(cooldown_ttl_seconds, int):
        return max(1, cooldown_ttl_seconds)
    low, high = cooldown_ttl_seconds
    low = max(1, int(low))
    high = max(low, int(high))
    return random.randint(low, high)


async def _release_lock(redis: RedisLike, *, lock_key: str, token: bytes) -> None:
    try:
        await redis.eval(_RELEASE_LOCK_SCRIPT, 1, lock_key, token)
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog_cache_lock_release_failed", extra={"error": str(exc)})


async def _start_lock_renewal_task(
    redis: RedisLike,
    *,
    lock_key: str,
    token: bytes,
    lock_ttl_ms: int,
    stop: asyncio.Event,
) -> asyncio.Task[None]:
    renew_every_ms = max(50, lock_ttl_ms // 3)

    async def _renew_loop() -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=renew_every_ms / 1000)
                continue
            except TimeoutError:
                pass

            try:
                await redis.eval(_RENEW_LOCK_SCRIPT, 1, lock_key, token, lock_ttl_ms)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "catalog_cache_lock_renew_failed", extra={"error": str(exc)}
                )

    return asyncio.create_task(_renew_loop())


async def _wait_for_fresh(
    redis: RedisLike,
    *,
    fresh_key: str,
    lock_key: str,
    wait_timeout_ms: int,
    poll_interval_ms: int,
) -> bytes | None:
    deadline = time.monotonic() + max(0, wait_timeout_ms) / 1000
    sleep_s = max(0.001, poll_interval_ms / 1000)

    while time.monotonic() < deadline:
        cached = await redis.get(fresh_key)
        if cached is not None:
            return cached

        ttl_ms = await redis.pttl(lock_key)
        if ttl_ms <= 0:
            return None

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        await asyncio.sleep(min(sleep_s, remaining))

    return await redis.get(fresh_key)


async def get_or_compute_cached_bytes(
    redis: RedisLike,
    *,
    fresh_key: str,
    stale_key: str,
    lock_key: str,
    fresh_ttl_seconds: int,
    stale_ttl_seconds: int,
    lock_ttl_ms: int,
    wait_timeout_ms: int,
    compute: Callable[[], Awaitable[bytes]],
    cooldown_ttl_seconds: int | tuple[int, int] = (5, 30),
    poll_interval_ms: int = 50,
    max_wait_ms: int = 60_000,
) -> CacheResult:
    cached = await redis.get(fresh_key)
    if cached is not None:
        return CacheResult(body=cached, status="fresh")

    stale = await redis.get(stale_key)

    token = _coerce_bytes(uuid.uuid4().hex)
    acquired = await redis.set(lock_key, token, nx=True, px=lock_ttl_ms)
    if acquired:
        stop = asyncio.Event()
        renew_task = await _start_lock_renewal_task(
            redis,
            lock_key=lock_key,
            token=token,
            lock_ttl_ms=lock_ttl_ms,
            stop=stop,
        )
        try:
            try:
                computed = await compute()
            except Exception as exc:  # noqa: BLE001
                if stale is not None:
                    cooldown_s = _pick_cooldown_seconds(cooldown_ttl_seconds)
                    try:
                        await redis.set(fresh_key, stale, ex=cooldown_s)
                    except Exception as set_exc:  # noqa: BLE001
                        logger.warning(
                            "catalog_cache_cooldown_set_failed",
                            extra={"error": str(set_exc)},
                        )

                    logger.warning(
                        "catalog_cache_compute_failed_serving_stale",
                        extra={"error": str(exc)},
                    )
                    return CacheResult(body=stale, status="stale")
                raise

            await redis.set(fresh_key, computed, ex=fresh_ttl_seconds)
            await redis.set(stale_key, computed, ex=stale_ttl_seconds)
            return CacheResult(body=computed, status="computed")
        finally:
            stop.set()
            renew_task.cancel()
            try:
                await renew_task
            except asyncio.CancelledError:
                pass
            await _release_lock(redis, lock_key=lock_key, token=token)

    if stale is not None:
        warmed = await _wait_for_fresh(
            redis,
            fresh_key=fresh_key,
            lock_key=lock_key,
            wait_timeout_ms=wait_timeout_ms,
            poll_interval_ms=poll_interval_ms,
        )
        if warmed is not None:
            return CacheResult(body=warmed, status="fresh")
        return CacheResult(body=stale, status="stale")

    start = time.monotonic()
    while (time.monotonic() - start) * 1000 < max_wait_ms:
        warmed = await _wait_for_fresh(
            redis,
            fresh_key=fresh_key,
            lock_key=lock_key,
            wait_timeout_ms=wait_timeout_ms,
            poll_interval_ms=poll_interval_ms,
        )
        if warmed is not None:
            return CacheResult(body=warmed, status="fresh")

        token = _coerce_bytes(uuid.uuid4().hex)
        acquired = await redis.set(lock_key, token, nx=True, px=lock_ttl_ms)
        if acquired:
            stop = asyncio.Event()
            renew_task = await _start_lock_renewal_task(
                redis,
                lock_key=lock_key,
                token=token,
                lock_ttl_ms=lock_ttl_ms,
                stop=stop,
            )
            try:
                computed = await compute()
                await redis.set(fresh_key, computed, ex=fresh_ttl_seconds)
                await redis.set(stale_key, computed, ex=stale_ttl_seconds)
                return CacheResult(body=computed, status="computed")
            finally:
                stop.set()
                renew_task.cancel()
                try:
                    await renew_task
                except asyncio.CancelledError:
                    pass
                await _release_lock(redis, lock_key=lock_key, token=token)

    raise TimeoutError("Timed out waiting for catalog cache to warm")
