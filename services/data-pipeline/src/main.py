from __future__ import annotations

from config import get_settings


def main() -> int:
    _ = get_settings()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
