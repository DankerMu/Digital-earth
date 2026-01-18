from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class FakeRedis:
    use_real_time: bool = True
    values: dict[str, bytes] = field(default_factory=dict)
    expires_at: dict[str, float] = field(default_factory=dict)
    _now_value: float = field(default_factory=time.monotonic, init=False)

    def now(self) -> float:
        if self.use_real_time:
            return time.monotonic()
        return self._now_value

    def advance(self, seconds: float) -> None:
        if self.use_real_time:
            raise RuntimeError("advance() requires use_real_time=False")
        self._now_value += float(seconds)

    def _purge_if_expired(self, key: str) -> None:
        expires_at = self.expires_at.get(key)
        if expires_at is None:
            return
        if self.now() >= expires_at:
            self.values.pop(key, None)
            self.expires_at.pop(key, None)

    async def get(self, key: str) -> bytes | None:
        self._purge_if_expired(key)
        return self.values.get(key)

    async def set(
        self,
        key: str,
        value: bytes,
        *,
        ex: int | None = None,
        px: int | None = None,
        nx: bool = False,
    ) -> object:
        self._purge_if_expired(key)
        if nx and key in self.values:
            return None

        if isinstance(value, str):  # pragma: no cover
            encoded = value.encode("utf-8")
        else:
            encoded = bytes(value)

        self.values[key] = encoded

        if ex is not None and px is not None:  # pragma: no cover
            raise ValueError("ex and px are mutually exclusive")

        if px is not None:
            ttl_s = int(px) / 1000
            self.expires_at[key] = self.now() + ttl_s
        elif ex is not None:
            ttl_s = int(ex)
            self.expires_at[key] = self.now() + ttl_s
        else:
            self.expires_at.pop(key, None)

        return True

    async def pttl(self, key: str) -> int:
        self._purge_if_expired(key)
        if key not in self.values:
            return -2
        expires_at = self.expires_at.get(key)
        if expires_at is None:
            return -1
        remaining_s = expires_at - self.now()
        if remaining_s <= 0:
            self._purge_if_expired(key)
            return -2
        return int(remaining_s * 1000)

    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object:
        assert numkeys == 1
        key = str(keys_and_args[0])
        token = keys_and_args[1]

        if isinstance(token, str):  # pragma: no cover
            token_bytes = token.encode("utf-8")
        else:
            token_bytes = bytes(token)

        self._purge_if_expired(key)
        current = self.values.get(key)
        if current != token_bytes:
            return 0

        if "PEXPIRE" in script:
            ttl_ms = int(keys_and_args[2])
            self.expires_at[key] = self.now() + ttl_ms / 1000
            return 1

        if "DEL" in script:
            self.values.pop(key, None)
            self.expires_at.pop(key, None)
            return 1

        raise NotImplementedError(f"Unsupported script: {script!r}")

    async def close(self) -> None:  # pragma: no cover
        return None
