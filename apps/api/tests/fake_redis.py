from __future__ import annotations

import time
from dataclasses import dataclass, field


def _now() -> float:
    return time.monotonic()


@dataclass
class FakeRedis:
    _store: dict[str, bytes] = field(default_factory=dict)
    _expires_at: dict[str, float] = field(default_factory=dict)
    zsets: dict[str, list[int]] = field(default_factory=dict)

    def _purge_if_expired(self, key: str) -> None:
        expires_at = self._expires_at.get(key)
        if expires_at is None:
            return
        if _now() >= expires_at:
            self._store.pop(key, None)
            self._expires_at.pop(key, None)

    async def get(self, key: str) -> bytes | None:
        self._purge_if_expired(key)
        return self._store.get(key)

    async def set(
        self,
        key: str,
        value: bytes,
        *,
        ex: int | None = None,
        px: int | None = None,
        nx: bool = False,
        **_kwargs: object,
    ) -> object:
        self._purge_if_expired(key)
        if nx and key in self._store:
            return None

        self._store[key] = bytes(value)
        if ex is not None:
            self._expires_at[key] = _now() + float(ex)
        elif px is not None:
            self._expires_at[key] = _now() + float(px) / 1000.0
        else:
            self._expires_at.pop(key, None)
        return True

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            self._purge_if_expired(key)
            if key in self._store:
                self._store.pop(key, None)
                self._expires_at.pop(key, None)
                removed += 1
        return removed

    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object:
        if "ZREMRANGEBYSCORE" in script and "ZCARD" in script:
            return self._eval_rate_limit(script, numkeys, *keys_and_args)
        if 'redis.call("get"' in script and 'redis.call("del"' in script:
            return self._eval_lock_release(numkeys, *keys_and_args)
        raise NotImplementedError("Unsupported eval script")

    def _eval_lock_release(self, numkeys: int, *keys_and_args: object) -> int:
        assert numkeys == 1
        key = str(keys_and_args[0])
        token_raw = keys_and_args[1]
        if isinstance(token_raw, bytes):
            token = token_raw
        else:
            token = str(token_raw).encode("utf-8")

        self._purge_if_expired(key)
        if self._store.get(key) != token:
            return 0
        self._store.pop(key, None)
        self._expires_at.pop(key, None)
        return 1

    def _eval_rate_limit(
        self, script: str, numkeys: int, *keys_and_args: object
    ) -> object:
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

    async def close(self) -> None:
        return None
