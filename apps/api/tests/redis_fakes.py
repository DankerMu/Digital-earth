from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class FakeRedis:
    use_real_time: bool = True
    values: dict[str, bytes] = field(default_factory=dict)
    zsets: dict[str, dict[bytes, float]] = field(default_factory=dict)
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
            self.zsets.pop(key, None)
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

    async def expire(self, key: str, seconds: int) -> object:
        self._purge_if_expired(key)
        if key not in self.values and key not in self.zsets:
            return 0

        ttl_s = max(0, int(seconds))
        self.expires_at[key] = self.now() + ttl_s
        if ttl_s == 0:
            self._purge_if_expired(key)
        return 1

    async def zincrby(self, key: str, amount: int | float, member: str) -> object:
        self._purge_if_expired(key)
        if isinstance(member, bytes):  # pragma: no cover
            member_bytes = bytes(member)
        else:
            member_bytes = str(member).encode("utf-8")

        entries = self.zsets.setdefault(key, {})
        current = float(entries.get(member_bytes, 0.0))
        updated = current + float(amount)
        entries[member_bytes] = updated
        return updated

    async def zrevrange(
        self,
        key: str,
        start: int,
        end: int,
        *,
        withscores: bool = False,
    ) -> object:
        self._purge_if_expired(key)
        entries = self.zsets.get(key, {})
        items = sorted(entries.items(), key=lambda item: (item[1], item[0]), reverse=True)

        resolved_start = max(0, int(start))
        resolved_end = int(end)
        if resolved_end < 0:
            resolved_end = len(items) - 1

        if resolved_end < resolved_start:
            selected: list[tuple[bytes, float]] = []
        else:
            selected = items[resolved_start : resolved_end + 1]

        if withscores:
            return [(member, score) for member, score in selected]
        return [member for member, _score in selected]

    async def pttl(self, key: str) -> int:
        self._purge_if_expired(key)
        if key not in self.values and key not in self.zsets:
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
