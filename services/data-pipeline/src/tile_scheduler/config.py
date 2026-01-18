from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Mapping, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from digital_earth_config.settings import _resolve_config_dir

SUPPORTED_SCHEMA_VERSIONS: Final[set[int]] = {1}

DEFAULT_TILE_SCHEDULER_CONFIG_NAME: Final[str] = "tile-scheduler.yaml"
DEFAULT_TILE_SCHEDULER_CONFIG_ENV: Final[str] = "DIGITAL_EARTH_TILE_SCHEDULER_CONFIG"


class TileSchedulerBackoffConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_seconds: float = Field(default=1.0, gt=0)
    factor: float = Field(default=2.0, gt=1.0)
    max_seconds: float = Field(default=60.0, gt=0)


class TileSchedulerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    enabled: bool = False

    # Concurrency.
    max_workers: int = Field(default=4, ge=1, le=128)

    # Retry policy.
    max_retries: int = Field(default=2, ge=0, le=50)
    backoff: TileSchedulerBackoffConfig = Field(
        default_factory=TileSchedulerBackoffConfig
    )

    # Log progress at most every N completed jobs (1 = every job).
    progress_log_every: int = Field(default=1, ge=1, le=10_000)

    @model_validator(mode="after")
    def _validate_schema_version(self) -> "TileSchedulerConfig":
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"Unsupported tile scheduler schema_version={self.schema_version}; "
                f"supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )
        return self


def _resolve_config_path(path: Optional[Union[str, Path]]) -> Path:
    if path is not None:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    explicit = os.environ.get(DEFAULT_TILE_SCHEDULER_CONFIG_ENV)
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    config_dir = _resolve_config_dir(os.environ)
    return config_dir / DEFAULT_TILE_SCHEDULER_CONFIG_NAME


def _parse_yaml(text: str, *, source: Path) -> Mapping[str, Any]:
    try:
        data = yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Failed to load tile scheduler YAML: {source}") from exc

    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        raise ValueError(f"tile scheduler config must be a mapping: {source}")
    return data


def load_tile_scheduler_config(
    path: Optional[Union[str, Path]] = None,
) -> TileSchedulerConfig:
    config_path = _resolve_config_path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"tile scheduler config file not found: {config_path}")

    raw_text = config_path.read_text(encoding="utf-8")
    data = dict(_parse_yaml(raw_text, source=config_path))

    try:
        return TileSchedulerConfig.model_validate(data)
    except ValidationError as exc:
        raise ValueError(
            f"Invalid tile scheduler config ({config_path}): {exc}"
        ) from exc


@lru_cache(maxsize=8)
def _get_tile_scheduler_config_cached(
    config_path: str, mtime_ns: int, size: int
) -> TileSchedulerConfig:
    _ = (mtime_ns, size)
    return load_tile_scheduler_config(config_path)


def get_tile_scheduler_config(
    path: Optional[Union[str, Path]] = None,
) -> TileSchedulerConfig:
    resolved = _resolve_config_path(path)
    try:
        stat = resolved.stat()
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"tile scheduler config file not found: {resolved}"
        ) from exc
    return _get_tile_scheduler_config_cached(
        str(resolved), stat.st_mtime_ns, stat.st_size
    )


get_tile_scheduler_config.cache_clear = _get_tile_scheduler_config_cached.cache_clear  # type: ignore[attr-defined]
