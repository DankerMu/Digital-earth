from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Literal

import numpy as np

TimeWindowKind = Literal["monthly", "seasonal", "annual"]


def parse_time(value: object) -> datetime:
    if isinstance(value, np.datetime64):
        text = np.datetime_as_string(value.astype("datetime64[s]"), unit="s")
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)

    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    raw = str(value or "").strip()
    if raw == "":
        raise ValueError("time value must not be empty")

    candidate = raw
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"Invalid time value: {raw!r}") from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _validate_aligned(dt: datetime, *, kind: TimeWindowKind) -> None:
    if dt.tzinfo is None:
        raise ValueError("time must be timezone-aware")
    dt = dt.astimezone(timezone.utc)
    if dt.minute or dt.second or dt.microsecond:
        raise ValueError(f"{kind} windows require 00:00:00 alignment")

    if kind == "monthly":
        if dt.day != 1 or dt.hour != 0:
            raise ValueError("monthly windows require day=1 at 00:00:00Z")
        return

    if kind == "annual":
        if dt.month != 1 or dt.day != 1 or dt.hour != 0:
            raise ValueError("annual windows require Jan 1st at 00:00:00Z")
        return

    if kind == "seasonal":
        if dt.day != 1 or dt.hour != 0:
            raise ValueError("seasonal windows require day=1 at 00:00:00Z")
        if dt.month not in {12, 3, 6, 9}:
            raise ValueError("seasonal windows must start/end on Dec/Mar/Jun/Sep")
        return

    raise ValueError(f"Unsupported window kind: {kind}")


def _add_months(dt: datetime, months: int) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("dt must be timezone-aware")

    year = dt.year
    month_index = (dt.month - 1) + int(months)
    year += month_index // 12
    month = (month_index % 12) + 1
    return datetime(year, month, 1, tzinfo=timezone.utc)


def _season_key(start: datetime) -> str:
    start = start.astimezone(timezone.utc)
    year = start.year
    if start.month == 12:
        season = "DJF"
    elif start.month == 3:
        season = "MAM"
    elif start.month == 6:
        season = "JJA"
    elif start.month == 9:
        season = "SON"
    else:  # pragma: no cover - guarded by _validate_aligned
        raise ValueError("Invalid seasonal window start month")
    return f"{year}-{season}"


@dataclass(frozen=True)
class TimeWindow:
    kind: TimeWindowKind
    start: datetime
    end: datetime

    @property
    def key(self) -> str:
        start = self.start.astimezone(timezone.utc)
        if self.kind == "monthly":
            return start.strftime("%Y%m")
        if self.kind == "annual":
            return start.strftime("%Y")
        if self.kind == "seasonal":
            return _season_key(self.start)
        raise ValueError(f"Unsupported window kind: {self.kind}")

    @property
    def start_iso(self) -> str:
        return self.start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @property
    def end_iso(self) -> str:
        return self.end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iter_time_windows(
    *,
    kind: TimeWindowKind,
    start: object,
    end: object,
) -> Iterable[TimeWindow]:
    start_dt = parse_time(start)
    end_dt = parse_time(end)

    if end_dt <= start_dt:
        raise ValueError("end must be after start")

    _validate_aligned(start_dt, kind=kind)
    _validate_aligned(end_dt, kind=kind)

    cursor = start_dt.astimezone(timezone.utc)
    end_dt = end_dt.astimezone(timezone.utc)

    if kind == "monthly":
        step = 1
    elif kind == "annual":
        step = 12
    elif kind == "seasonal":
        step = 3
    else:
        raise ValueError(f"Unsupported window kind: {kind}")

    while cursor < end_dt:
        next_dt = _add_months(cursor, step)
        if next_dt > end_dt:
            raise ValueError("end must align to window boundaries")
        yield TimeWindow(kind=kind, start=cursor, end=next_dt)
        cursor = next_dt
