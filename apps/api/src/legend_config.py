from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

DEFAULT_LEGENDS_DIR_ENV: Final[str] = "DIGITAL_EARTH_LEGENDS_DIR"


def _get_repo_root() -> Path:
    """Get repository root, handling both local dev and container environments."""
    try:
        return Path(__file__).resolve().parents[3]
    except IndexError:
        # In container, use a fallback path
        return Path("/app")


REPO_ROOT = _get_repo_root()
DEFAULT_LEGENDS_DIR = REPO_ROOT / "packages" / "config" / "src" / "legends"

SUPPORTED_LAYER_TYPES: Final[tuple[str, ...]] = (
    "temperature",
    "cloud",
    "precipitation",
    "wind",
)


class LegendConfigItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    colors: list[str] = Field(min_length=1)
    thresholds: list[float] = Field(min_length=1)
    labels: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_lengths(self) -> "LegendConfigItem":
        if len(self.colors) != len(self.thresholds) or len(self.colors) != len(
            self.labels
        ):
            raise ValueError("colors, thresholds, labels must have equal lengths")

        prev: float | None = None
        for threshold in self.thresholds:
            value = float(threshold)
            if prev is not None and value <= prev:
                raise ValueError("thresholds must be strictly increasing")
            prev = value

        for color in self.colors:
            if not isinstance(color, str) or color.strip() == "":
                raise ValueError("colors entries must be non-empty strings")

        for label in self.labels:
            if not isinstance(label, str) or label.strip() == "":
                raise ValueError("labels entries must be non-empty strings")

        return self


@dataclass(frozen=True)
class LegendConfigPayload:
    etag: str
    body: bytes
    config: LegendConfigItem


def normalize_layer_type(raw: str) -> str:
    text = (raw or "").strip().lower()
    if text in ("temperature", "temp"):
        return "temperature"
    if text in ("cloud",):
        return "cloud"
    if text in ("precipitation", "precip"):
        return "precipitation"
    if text in ("wind",):
        return "wind"
    raise ValueError(
        "layer_type must be one of: temperature, cloud, precipitation, wind"
    )


def _resolve_legends_dir(path: Optional[Union[str, Path]]) -> Path:
    if path is not None:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    explicit = os.environ.get(DEFAULT_LEGENDS_DIR_ENV)
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    return DEFAULT_LEGENDS_DIR


def _legend_path(legends_dir: Path, layer_type: str) -> Path:
    filename = f"{layer_type}.json"
    return (legends_dir / filename).resolve()


@lru_cache(maxsize=32)
def _get_legend_payload_cached(
    layer_type: str, path: str, mtime_ns: int, ctime_ns: int, size: int
) -> LegendConfigPayload:
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Legend config file not found: {config_path}")

    raw_bytes = config_path.read_bytes()

    try:
        decoded: Any = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Legend config is not valid JSON: {config_path}") from exc

    if not isinstance(decoded, dict):
        raise ValueError(f"Legend config must be a JSON object: {config_path}")

    try:
        parsed = LegendConfigItem.model_validate(decoded)
    except ValidationError as exc:
        raise ValueError(f"Invalid legend config: {config_path}: {exc}") from exc

    body = parsed.model_dump_json().encode("utf-8")
    etag = f'"sha256-{hashlib.sha256(body).hexdigest()}"'
    return LegendConfigPayload(etag=etag, body=body, config=parsed)


def get_legend_config_payload(
    layer_type: str,
    *,
    legends_dir: Optional[Union[str, Path]] = None,
) -> LegendConfigPayload:
    normalized = normalize_layer_type(layer_type)
    resolved_dir = _resolve_legends_dir(legends_dir)
    config_path = _legend_path(resolved_dir, normalized)
    stat = config_path.stat()
    return _get_legend_payload_cached(
        normalized, str(config_path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size
    )


get_legend_config_payload.cache_clear = _get_legend_payload_cached.cache_clear  # type: ignore[attr-defined]
