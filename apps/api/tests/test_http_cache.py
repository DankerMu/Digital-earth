from __future__ import annotations

from http_cache import if_none_match_matches


def test_if_none_match_matches_returns_false_for_blank_header() -> None:
    assert if_none_match_matches("   ", '"t"') is False
