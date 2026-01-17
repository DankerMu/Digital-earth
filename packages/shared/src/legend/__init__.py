from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class LegendLoadError(RuntimeError):
    pass


LEGEND_ROOT = Path(__file__).resolve().parent


def get_legend_path(*parts: str) -> Path:
    if not parts:
        raise ValueError("legend path parts must not be empty")
    cleaned = [part.strip().strip("/") for part in parts]
    if any(part == "" for part in cleaned):
        raise ValueError("legend path parts must not be empty")
    return (LEGEND_ROOT.joinpath(*cleaned)).resolve()


def load_legend(*parts: str) -> dict[str, Any]:
    path = get_legend_path(*parts)
    if not path.is_file():
        raise FileNotFoundError(f"Legend file not found: {path}")

    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        raise LegendLoadError(f"Failed to read legend file: {path}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LegendLoadError(f"Legend file is not valid JSON: {path}") from exc

    if not isinstance(data, dict):
        raise LegendLoadError(f"Legend JSON must be an object: {path}")
    return data
