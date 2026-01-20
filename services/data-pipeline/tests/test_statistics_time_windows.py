from __future__ import annotations

from datetime import datetime, timezone

import pytest


def test_parse_time_accepts_naive_datetime_as_utc() -> None:
    from statistics.time_windows import parse_time

    dt = parse_time(datetime(2020, 1, 1, 12, 0, 0))
    assert dt.tzinfo is not None
    assert dt.isoformat() == "2020-01-01T12:00:00+00:00"


def test_parse_time_rejects_invalid_value() -> None:
    from statistics.time_windows import parse_time

    with pytest.raises(ValueError, match="must not be empty"):
        parse_time("")

    with pytest.raises(ValueError, match="Invalid time value"):
        parse_time("not-a-time")


def test_iter_time_windows_monthly_keys_and_bounds() -> None:
    from statistics.time_windows import iter_time_windows

    windows = list(
        iter_time_windows(
            kind="monthly",
            start="2020-01-01T00:00:00Z",
            end="2020-03-01T00:00:00Z",
        )
    )
    assert [w.key for w in windows] == ["202001", "202002"]
    assert windows[0].start_iso == "2020-01-01T00:00:00Z"
    assert windows[0].end_iso == "2020-02-01T00:00:00Z"


def test_iter_time_windows_seasonal_djf() -> None:
    from statistics.time_windows import iter_time_windows

    windows = list(
        iter_time_windows(
            kind="seasonal",
            start="2020-12-01T00:00:00Z",
            end="2021-03-01T00:00:00Z",
        )
    )
    assert len(windows) == 1
    assert windows[0].key == "2020-DJF"
    assert windows[0].start_iso == "2020-12-01T00:00:00Z"
    assert windows[0].end_iso == "2021-03-01T00:00:00Z"


def test_iter_time_windows_annual_keys() -> None:
    from statistics.time_windows import iter_time_windows

    windows = list(
        iter_time_windows(
            kind="annual",
            start=datetime(2020, 1, 1, tzinfo=timezone.utc),
            end=datetime(2022, 1, 1, tzinfo=timezone.utc),
        )
    )
    assert [w.key for w in windows] == ["2020", "2021"]


def test_iter_time_windows_rejects_misaligned_inputs() -> None:
    from statistics.time_windows import iter_time_windows

    with pytest.raises(ValueError, match="monthly windows require"):
        list(
            iter_time_windows(
                kind="monthly",
                start="2020-01-02T00:00:00Z",
                end="2020-02-01T00:00:00Z",
            )
        )

    with pytest.raises(ValueError, match="monthly windows require"):
        list(
            iter_time_windows(
                kind="monthly",
                start="2020-01-01T00:00:00Z",
                end="2020-02-15T00:00:00Z",
            )
        )
