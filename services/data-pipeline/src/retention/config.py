from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Mapping, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from digital_earth_config.settings import _resolve_config_dir

SUPPORTED_SCHEMA_VERSIONS: Final[set[int]] = {1}

DEFAULT_RETENTION_CONFIG_NAME: Final[str] = "retention.yaml"
DEFAULT_RETENTION_CONFIG_ENV: Final[str] = "DIGITAL_EARTH_RETENTION_CONFIG"


class RawRetentionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    root_dir: Path = Path("Data/raw")
    keep_n_runs: int = Field(default=5, ge=0)


class CubeRetentionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    root_dir: Path = Path("Data/cube")
    keep_n_runs: int = Field(default=5, ge=0)


class TilesRetentionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    root_dir: Path = Path("Data/tiles")
    keep_n_versions: int = Field(default=5, ge=0)
    referenced_versions_path: Optional[Path] = None


class RetentionAuditConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    log_path: Path = Path(".cache/audit/retention.jsonl")


class RetentionSchedulerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    cron: str = "0 3 * * *"

    @model_validator(mode="after")
    def _validate(self) -> "RetentionSchedulerConfig":
        if self.cron.strip() == "":
            raise ValueError("scheduler.cron must not be empty")
        return self


class RetentionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    raw: RawRetentionConfig = Field(default_factory=RawRetentionConfig)
    cube: CubeRetentionConfig = Field(default_factory=CubeRetentionConfig)
    tiles: TilesRetentionConfig = Field(default_factory=TilesRetentionConfig)
    audit: RetentionAuditConfig = Field(default_factory=RetentionAuditConfig)
    scheduler: RetentionSchedulerConfig = Field(
        default_factory=RetentionSchedulerConfig
    )

    @model_validator(mode="after")
    def _validate_schema(self) -> "RetentionConfig":
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"Unsupported retention schema_version={self.schema_version}; "
                f"supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )
        return self


def _resolve_config_path(path: Optional[Union[str, Path]]) -> Path:
    if path is not None:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    explicit = os.environ.get(DEFAULT_RETENTION_CONFIG_ENV)
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    config_dir = _resolve_config_dir(os.environ)
    return config_dir / DEFAULT_RETENTION_CONFIG_NAME


def _parse_yaml(text: str, *, source: Path) -> Mapping[str, Any]:
    try:
        data = yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Failed to load retention YAML: {source}") from exc

    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        raise ValueError(f"retention config must be a mapping: {source}")
    return data


def _resolve_repo_root(*, config_path: Path) -> Path:
    config_dir = config_path.parent
    repo_root = config_dir.parent
    return repo_root.resolve()


def _resolve_within_repo_root(*, value: Path, repo_root: Path, field_name: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        resolved = (repo_root / candidate).resolve()
        if not resolved.is_relative_to(repo_root):
            raise ValueError(
                f"retention {field_name} must resolve within repo root when relative"
            )
        return resolved
    return candidate.resolve()


def _normalize_paths(cfg: RetentionConfig, *, config_path: Path) -> RetentionConfig:
    repo_root = _resolve_repo_root(config_path=config_path)
    return cfg.model_copy(
        update={
            "raw": cfg.raw.model_copy(
                update={
                    "root_dir": _resolve_within_repo_root(
                        value=cfg.raw.root_dir,
                        repo_root=repo_root,
                        field_name="raw.root_dir",
                    )
                }
            ),
            "cube": cfg.cube.model_copy(
                update={
                    "root_dir": _resolve_within_repo_root(
                        value=cfg.cube.root_dir,
                        repo_root=repo_root,
                        field_name="cube.root_dir",
                    )
                }
            ),
            "tiles": cfg.tiles.model_copy(
                update={
                    "root_dir": _resolve_within_repo_root(
                        value=cfg.tiles.root_dir,
                        repo_root=repo_root,
                        field_name="tiles.root_dir",
                    ),
                    "referenced_versions_path": (
                        None
                        if cfg.tiles.referenced_versions_path is None
                        else _resolve_within_repo_root(
                            value=cfg.tiles.referenced_versions_path,
                            repo_root=repo_root,
                            field_name="tiles.referenced_versions_path",
                        )
                    ),
                }
            ),
            "audit": cfg.audit.model_copy(
                update={
                    "log_path": _resolve_within_repo_root(
                        value=cfg.audit.log_path,
                        repo_root=repo_root,
                        field_name="audit.log_path",
                    )
                }
            ),
        }
    )


def load_retention_config(path: Optional[Union[str, Path]] = None) -> RetentionConfig:
    config_path = _resolve_config_path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"retention config file not found: {config_path}")

    raw_text = config_path.read_text(encoding="utf-8")
    data = dict(_parse_yaml(raw_text, source=config_path))

    try:
        cfg = RetentionConfig.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid retention config ({config_path}): {exc}") from exc

    return _normalize_paths(cfg, config_path=config_path)


@lru_cache(maxsize=8)
def _get_retention_config_cached(
    config_path: str, mtime_ns: int, size: int
) -> RetentionConfig:
    _ = (mtime_ns, size)
    return load_retention_config(config_path)


def get_retention_config(path: Optional[Union[str, Path]] = None) -> RetentionConfig:
    resolved = _resolve_config_path(path)
    try:
        stat = resolved.stat()
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"retention config file not found: {resolved}") from exc

    return _get_retention_config_cached(str(resolved), stat.st_mtime_ns, stat.st_size)


get_retention_config.cache_clear = _get_retention_config_cached.cache_clear  # type: ignore[attr-defined]
