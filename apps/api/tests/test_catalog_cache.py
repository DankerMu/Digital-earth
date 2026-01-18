from __future__ import annotations

import asyncio

from catalog_cache import (
    _coerce_bytes,
    _start_lock_renewal_task,
    get_or_compute_cached_bytes,
)

from redis_fakes import FakeRedis


def test_catalog_cache_waits_beyond_wait_timeout_without_stampede() -> None:
    redis = FakeRedis(use_real_time=True)
    fresh_key = "catalog:test:fresh"
    stale_key = "catalog:test:stale"
    lock_key = "catalog:test:lock"

    started = asyncio.Event()
    release = asyncio.Event()
    calls = {"count": 0}

    async def compute() -> bytes:
        calls["count"] += 1
        started.set()
        await release.wait()
        return b'{"ok":true}'

    async def _run() -> tuple[bytes, bytes]:
        first = asyncio.create_task(
            get_or_compute_cached_bytes(
                redis,
                fresh_key=fresh_key,
                stale_key=stale_key,
                lock_key=lock_key,
                fresh_ttl_seconds=60,
                stale_ttl_seconds=3600,
                lock_ttl_ms=1000,
                wait_timeout_ms=50,
                compute=compute,
                max_wait_ms=5_000,
            )
        )

        await started.wait()

        second = asyncio.create_task(
            get_or_compute_cached_bytes(
                redis,
                fresh_key=fresh_key,
                stale_key=stale_key,
                lock_key=lock_key,
                fresh_ttl_seconds=60,
                stale_ttl_seconds=3600,
                lock_ttl_ms=1000,
                wait_timeout_ms=50,
                compute=compute,
                max_wait_ms=5_000,
            )
        )

        await asyncio.sleep(0.15)
        release.set()
        first_result, second_result = await asyncio.gather(first, second)
        return first_result.body, second_result.body

    first_body, second_body = asyncio.run(_run())
    assert calls["count"] == 1
    assert first_body == b'{"ok":true}'
    assert second_body == b'{"ok":true}'


def test_catalog_cache_compute_failure_sets_cooldown_and_serves_stale() -> None:
    redis = FakeRedis(use_real_time=True)
    fresh_key = "catalog:test:fresh"
    stale_key = "catalog:test:stale"
    lock_key = "catalog:test:lock"

    async def _seed() -> None:
        await redis.set(stale_key, b'{"value":"stale"}', ex=3600)

    asyncio.run(_seed())

    calls = {"count": 0}

    async def compute() -> bytes:
        calls["count"] += 1
        raise RuntimeError("boom")

    async def _run() -> tuple[bytes, int]:
        result = await get_or_compute_cached_bytes(
            redis,
            fresh_key=fresh_key,
            stale_key=stale_key,
            lock_key=lock_key,
            fresh_ttl_seconds=60,
            stale_ttl_seconds=3600,
            lock_ttl_ms=1000,
            wait_timeout_ms=50,
            compute=compute,
            cooldown_ttl_seconds=5,
        )
        ttl_ms = await redis.pttl(fresh_key)
        return result.body, ttl_ms

    body, ttl_ms = asyncio.run(_run())
    assert calls["count"] == 1
    assert body == b'{"value":"stale"}'
    assert 0 < ttl_ms <= 5000


def test_catalog_cache_lock_is_renewed_for_slow_compute() -> None:
    redis = FakeRedis(use_real_time=True)
    fresh_key = "catalog:test:fresh"
    stale_key = "catalog:test:stale"
    lock_key = "catalog:test:lock"

    calls = {"count": 0}
    started = asyncio.Event()

    async def compute() -> bytes:
        calls["count"] += 1
        started.set()
        await asyncio.sleep(0.6)
        return b'{"ok":true}'

    async def _run() -> list[bytes]:
        first = asyncio.create_task(
            get_or_compute_cached_bytes(
                redis,
                fresh_key=fresh_key,
                stale_key=stale_key,
                lock_key=lock_key,
                fresh_ttl_seconds=60,
                stale_ttl_seconds=3600,
                lock_ttl_ms=200,
                wait_timeout_ms=50,
                compute=compute,
                max_wait_ms=5_000,
            )
        )

        await started.wait()
        await asyncio.sleep(0.3)

        second = asyncio.create_task(
            get_or_compute_cached_bytes(
                redis,
                fresh_key=fresh_key,
                stale_key=stale_key,
                lock_key=lock_key,
                fresh_ttl_seconds=60,
                stale_ttl_seconds=3600,
                lock_ttl_ms=200,
                wait_timeout_ms=50,
                compute=compute,
                max_wait_ms=5_000,
            )
        )

        results = await asyncio.gather(first, second)
        return [item.body for item in results]

    bodies = asyncio.run(_run())
    assert calls["count"] == 1
    assert bodies == [b'{"ok":true}', b'{"ok":true}']


def test_catalog_cache_coerce_bytes_is_idempotent() -> None:
    assert _coerce_bytes(b"token") == b"token"


def test_catalog_cache_renew_task_stops_on_event() -> None:
    redis = FakeRedis(use_real_time=True)

    async def _run() -> None:
        stop = asyncio.Event()
        task = await _start_lock_renewal_task(
            redis,
            lock_key="catalog:test:lock",
            token=b"token",
            lock_ttl_ms=500,
            stop=stop,
        )

        await asyncio.sleep(0)
        stop.set()
        await task

    asyncio.run(_run())


def test_catalog_cache_stale_can_wait_for_warmed_fresh_from_other_worker() -> None:
    redis = FakeRedis(use_real_time=True)
    fresh_key = "catalog:test:fresh"
    stale_key = "catalog:test:stale"
    lock_key = "catalog:test:lock"

    async def _run() -> bytes:
        await redis.set(stale_key, b'{"value":"stale"}', ex=3600)
        await redis.set(lock_key, b"other-worker", px=1000)

        async def _warm_cache() -> None:
            await asyncio.sleep(0.05)
            await redis.set(fresh_key, b'{"value":"fresh"}', ex=60)

        warm_task = asyncio.create_task(_warm_cache())

        async def _boom() -> bytes:
            raise AssertionError("compute should not run when lock is held")

        result = await get_or_compute_cached_bytes(
            redis,
            fresh_key=fresh_key,
            stale_key=stale_key,
            lock_key=lock_key,
            fresh_ttl_seconds=60,
            stale_ttl_seconds=3600,
            lock_ttl_ms=1000,
            wait_timeout_ms=200,
            poll_interval_ms=10,
            compute=_boom,
        )
        await warm_task
        return result.body

    assert asyncio.run(_run()) == b'{"value":"fresh"}'


def test_catalog_cache_compute_failure_ignores_cooldown_set_errors() -> None:
    fresh_key = "catalog:test:fresh"
    stale_key = "catalog:test:stale"
    lock_key = "catalog:test:lock"

    class BrokenCooldownRedis:
        def __init__(self) -> None:
            self.delegate = FakeRedis(use_real_time=True)

        async def get(self, key: str) -> bytes | None:
            return await self.delegate.get(key)

        async def set(
            self,
            key: str,
            value: bytes,
            *,
            ex: int | None = None,
            px: int | None = None,
            nx: bool = False,
        ) -> object:
            if key == fresh_key and ex is not None and not nx:
                raise RuntimeError("redis set down")
            return await self.delegate.set(key, value, ex=ex, px=px, nx=nx)

        async def pttl(self, key: str) -> int:
            return await self.delegate.pttl(key)

        async def eval(
            self, script: str, numkeys: int, *keys_and_args: object
        ) -> object:
            return await self.delegate.eval(script, numkeys, *keys_and_args)

    redis = BrokenCooldownRedis()

    async def _run() -> bytes:
        await redis.set(stale_key, b'{"value":"stale"}', ex=3600)

        async def _boom() -> bytes:
            raise RuntimeError("compute failed")

        result = await get_or_compute_cached_bytes(
            redis,
            fresh_key=fresh_key,
            stale_key=stale_key,
            lock_key=lock_key,
            fresh_ttl_seconds=60,
            stale_ttl_seconds=3600,
            lock_ttl_ms=500,
            wait_timeout_ms=50,
            cooldown_ttl_seconds=5,
            compute=_boom,
        )
        return result.body

    assert asyncio.run(_run()) == b'{"value":"stale"}'


def test_catalog_cache_retries_lock_after_wait_timeout_in_cold_start() -> None:
    redis = FakeRedis(use_real_time=True)
    fresh_key = "catalog:test:fresh"
    stale_key = "catalog:test:stale"
    lock_key = "catalog:test:lock"

    calls = {"count": 0}

    async def compute() -> bytes:
        calls["count"] += 1
        return b'{"ok":true}'

    async def _run() -> bytes:
        await redis.set(lock_key, b"other-worker", px=80)
        result = await get_or_compute_cached_bytes(
            redis,
            fresh_key=fresh_key,
            stale_key=stale_key,
            lock_key=lock_key,
            fresh_ttl_seconds=60,
            stale_ttl_seconds=3600,
            lock_ttl_ms=200,
            wait_timeout_ms=20,
            poll_interval_ms=5,
            max_wait_ms=2_000,
            compute=compute,
        )
        return result.body

    assert asyncio.run(_run()) == b'{"ok":true}'
    assert calls["count"] == 1
