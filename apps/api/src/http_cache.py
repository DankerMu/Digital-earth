from __future__ import annotations


def if_none_match_matches(header: str | None, etag: str) -> bool:
    if header is None:
        return False

    text = header.strip()
    if text == "":
        return False
    if text == "*":
        return True

    return any(item.strip() == etag for item in text.split(","))
