from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


class LegendLoadError(RuntimeError):
    pass


LEGEND_ROOT = Path(__file__).resolve().parent
_DERIVED_LEGEND_KEYS = {"colorStops", "max", "min", "version"}


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


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _strip_derived_fields(legend: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in legend.items() if key not in _DERIVED_LEGEND_KEYS
    }


def compute_legend_version(legend: Mapping[str, Any]) -> str:
    """Compute a stable version hash for a legend config payload."""

    payload = _strip_derived_fields(legend)
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return digest


def _load_color_stops(legend: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = legend.get("colorStops")
    if raw is None:
        raw = legend.get("stops")
    if not isinstance(raw, list):
        raise ValueError("legend color stops must be a list")
    stops: list[dict[str, Any]] = []
    for stop in raw:
        if not isinstance(stop, dict):
            raise ValueError("legend color stop entries must be objects")
        value = stop.get("value")
        color = stop.get("color")
        if not isinstance(value, (int, float)):
            raise ValueError("legend color stop value must be a number")
        if not isinstance(color, str) or color.strip() == "":
            raise ValueError("legend color stop color must be a string")
        item: dict[str, Any] = {"value": value, "color": color}
        label = stop.get("label")
        if isinstance(label, str) and label.strip() != "":
            item["label"] = label
        stops.append(item)
    if len(stops) < 2:
        raise ValueError("legend color stops must have at least 2 entries")
    stops.sort(key=lambda item: float(item["value"]))
    return stops


def normalize_legend_for_clients(legend: Mapping[str, Any]) -> dict[str, Any]:
    """Return a legend payload suitable for clients.

    Ensures the legend includes: unit, min, max, colorStops, version.
    """

    if not isinstance(legend, Mapping):
        raise TypeError("legend must be a mapping")

    payload: dict[str, Any] = dict(legend)
    color_stops = _load_color_stops(legend)
    values = [item["value"] for item in color_stops]

    payload["colorStops"] = color_stops
    payload["min"] = min(values)
    payload["max"] = max(values)
    payload["version"] = compute_legend_version(legend)
    return payload
