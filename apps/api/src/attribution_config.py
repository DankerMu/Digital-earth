from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Optional, Union

from pydantic import BaseModel, model_validator

SUPPORTED_SCHEMA_VERSIONS: Final[set[int]] = {1}
DEFAULT_ATTRIBUTION_CONFIG_NAME: Final[str] = "attribution.yaml"


class AttributionSource(BaseModel):
    id: str
    name: str
    provider: Optional[str] = None
    url: Optional[str] = None
    license: Optional[str] = None
    attribution: Optional[str] = None


class AttributionConfig(BaseModel):
    schema_version: int
    version: str
    updated_at: Optional[str] = None
    sources: list[AttributionSource]
    disclaimer: list[str]

    @model_validator(mode="after")
    def _validate_schema_version(self) -> "AttributionConfig":
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"Unsupported attribution schema_version={self.schema_version}; "
                f"supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )
        return self


@dataclass(frozen=True)
class AttributionPayload:
    version: str
    etag: str
    text: str


def _resolve_config_path(path: Optional[Union[str, Path]]) -> Path:
    if path is not None:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    explicit = os.environ.get("DIGITAL_EARTH_ATTRIBUTION_CONFIG")
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    config_dir = os.environ.get("DIGITAL_EARTH_CONFIG_DIR")
    if config_dir:
        candidate_dir = Path(config_dir).expanduser()
        if not candidate_dir.is_absolute():
            candidate_dir = (Path.cwd() / candidate_dir).resolve()
        return candidate_dir / DEFAULT_ATTRIBUTION_CONFIG_NAME

    cwd = Path.cwd()
    for candidate_root in (cwd, *cwd.parents):
        candidate = candidate_root / "config" / DEFAULT_ATTRIBUTION_CONFIG_NAME
        if candidate.is_file():
            return candidate

    return cwd / "config" / DEFAULT_ATTRIBUTION_CONFIG_NAME


def _format_source_line(source: AttributionSource) -> str:
    left = source.name.strip()
    if source.attribution and source.attribution.strip() != source.name.strip():
        left = f"{source.attribution.strip()} — {source.name.strip()}"

    suffixes: list[str] = []
    if source.provider:
        suffixes.append(source.provider.strip())
    if source.url:
        suffixes.append(source.url.strip())
    if source.license:
        suffixes.append(source.license.strip())

    if not suffixes:
        return f"- {left}"
    return f"- {left} ({' · '.join(suffixes)})"


def _render_attribution_text(config: AttributionConfig) -> str:
    lines: list[str] = [f"Attribution (v{config.version})"]
    if config.updated_at:
        lines.append(f"Updated: {config.updated_at}")

    lines.extend(["", "Sources:"])
    lines.extend(_format_source_line(source) for source in config.sources)

    lines.extend(["", "Disclaimer:"])
    lines.extend(f"- {item.strip()}" for item in config.disclaimer if item.strip())
    return "\n".join(lines).strip() + "\n"


def _parse_yaml(text: str, *, source: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-not-found]

        data = yaml.safe_load(text)
    except Exception as exc:
        raise ValueError(f"Failed to load attribution YAML: {source}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Attribution config must be a mapping: {source}")
    return data


@lru_cache(maxsize=4)
def _get_attribution_payload_cached(
    path: str, mtime_ns: int, size: int
) -> AttributionPayload:
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Attribution config file not found: {config_path}")

    raw_bytes = config_path.read_bytes()
    etag = f'"sha256-{hashlib.sha256(raw_bytes).hexdigest()}"'

    raw_text = raw_bytes.decode("utf-8")
    data = _parse_yaml(raw_text, source=config_path)
    parsed = AttributionConfig.model_validate(data)
    return AttributionPayload(
        version=parsed.version, etag=etag, text=_render_attribution_text(parsed)
    )


def get_attribution_payload(
    path: Optional[Union[str, Path]] = None,
) -> AttributionPayload:
    resolved = _resolve_config_path(path)
    try:
        stat = resolved.stat()
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Attribution config file not found: {resolved}"
        ) from exc
    return _get_attribution_payload_cached(
        str(resolved), stat.st_mtime_ns, stat.st_size
    )


get_attribution_payload.cache_clear = _get_attribution_payload_cached.cache_clear  # type: ignore[attr-defined]
