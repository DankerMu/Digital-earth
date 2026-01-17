from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

SUPPORTED_SCHEMA_VERSIONS: set[int] = {1}

DEFAULT_SCHEDULER_CONFIG_NAME = "scheduler.yaml"
DEFAULT_SCHEDULER_CONFIG_ENV = "DIGITAL_EARTH_SCHEDULER_CONFIG"


def _resolve_config_dir(environ: Optional[Mapping[str, str]] = None) -> Path:
    environ = environ or os.environ
    explicit = environ.get("DIGITAL_EARTH_CONFIG_DIR")
    if explicit:
        explicit_path = Path(explicit).expanduser()
        if not explicit_path.is_absolute():
            explicit_path = (Path.cwd() / explicit_path).resolve()
        return explicit_path

    cwd = Path.cwd()
    for candidate_root in (cwd, *cwd.parents):
        config_dir = candidate_root / "config"
        if (
            (config_dir / "dev.json").is_file()
            and (config_dir / "staging.json").is_file()
            and (config_dir / "prod.json").is_file()
        ):
            return config_dir

    return cwd / "config"


def _resolve_config_path(path: Optional[Union[str, Path]]) -> Path:
    if path is not None:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    explicit = os.environ.get(DEFAULT_SCHEDULER_CONFIG_ENV)
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    config_dir = _resolve_config_dir(os.environ)
    return config_dir / DEFAULT_SCHEDULER_CONFIG_NAME


def _parse_yaml(text: str, *, source: Path) -> Mapping[str, Any]:
    try:
        data = yaml.safe_load(text)
    except Exception as exc:
        raise ValueError(f"Failed to load scheduler YAML: {source}") from exc

    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        raise ValueError(f"scheduler config must be a mapping: {source}")
    return data


class SchedulerBackoffConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_seconds: float = Field(default=1.0, gt=0)
    factor: float = Field(default=2.0, gt=1.0)
    max_seconds: float = Field(default=300.0, gt=0)


class SchedulerRunsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storage_path: str = ".cache/ingest-runs.json"
    max_entries: int = Field(default=200, ge=1, le=10_000)


class SchedulerAlertConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consecutive_failures: int = Field(default=3, ge=1)
    webhook_url: Optional[str] = None
    webhook_headers: dict[str, str] = Field(default_factory=dict)


class SchedulerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    enabled: bool = False
    cron: str = "0 * * * *"
    max_retries: int = Field(default=3, ge=0)
    backoff: SchedulerBackoffConfig = Field(default_factory=SchedulerBackoffConfig)
    runs: SchedulerRunsConfig = Field(default_factory=SchedulerRunsConfig)
    alert: SchedulerAlertConfig = Field(default_factory=SchedulerAlertConfig)

    @model_validator(mode="after")
    def _validate_schema(self) -> "SchedulerConfig":
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"Unsupported scheduler schema_version={self.schema_version}; "
                f"supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )
        if self.cron.strip() == "":
            raise ValueError("scheduler.cron must not be empty")
        return self


@lru_cache(maxsize=8)
def _get_scheduler_config_cached(
    config_path: str, mtime_ns: int, size: int
) -> SchedulerConfig:
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"scheduler config file not found: {path}")

    raw = path.read_text(encoding="utf-8")
    data = dict(_parse_yaml(raw, source=path))

    try:
        return SchedulerConfig.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid scheduler config ({path}): {exc}") from exc


def get_scheduler_config(path: Optional[Union[str, Path]] = None) -> SchedulerConfig:
    resolved = _resolve_config_path(path)
    stat = resolved.stat()
    return _get_scheduler_config_cached(str(resolved), stat.st_mtime_ns, stat.st_size)


get_scheduler_config.cache_clear = _get_scheduler_config_cached.cache_clear  # type: ignore[attr-defined]
