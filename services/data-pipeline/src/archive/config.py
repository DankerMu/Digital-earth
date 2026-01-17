from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Mapping, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from digital_earth_config.settings import _resolve_config_dir

SUPPORTED_SCHEMA_VERSIONS: Final[set[int]] = {1}

DEFAULT_ARCHIVE_CONFIG_NAME: Final[str] = "archive.yaml"
DEFAULT_ARCHIVE_CONFIG_ENV: Final[str] = "DIGITAL_EARTH_ARCHIVE_CONFIG"


class ArchiveConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    raw_root_dir: Path = Path("Data/raw")
    keep_n_runs: int = Field(default=5, ge=0)
    checksum_algorithm: str = "sha256"
    manifest_filename: str = "manifest.json"

    @model_validator(mode="after")
    def _validate_schema_version(self) -> "ArchiveConfig":
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"Unsupported archive schema_version={self.schema_version}; "
                f"supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )

        algo = (self.checksum_algorithm or "").strip().lower()
        if algo not in {"sha256"}:
            raise ValueError(
                f"Unsupported checksum_algorithm={self.checksum_algorithm!r}; "
                "expected 'sha256'"
            )
        self.checksum_algorithm = algo

        name = (self.manifest_filename or "").strip()
        if name == "":
            raise ValueError("manifest_filename must not be empty")
        candidate = Path(name)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("manifest_filename must be a relative filename")
        self.manifest_filename = str(candidate.as_posix())

        return self


def _resolve_config_path(path: Optional[Union[str, Path]]) -> Path:
    if path is not None:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    explicit = os.environ.get(DEFAULT_ARCHIVE_CONFIG_ENV)
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    config_dir = _resolve_config_dir(os.environ)
    return config_dir / DEFAULT_ARCHIVE_CONFIG_NAME


def _parse_yaml(text: str, *, source: Path) -> Mapping[str, Any]:
    try:
        data = yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Failed to load archive YAML: {source}") from exc

    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        raise ValueError(f"archive config must be a mapping: {source}")
    return data


def load_archive_config(path: Optional[Union[str, Path]] = None) -> ArchiveConfig:
    config_path = _resolve_config_path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"archive config file not found: {config_path}")

    raw_text = config_path.read_text(encoding="utf-8")
    data = dict(_parse_yaml(raw_text, source=config_path))

    try:
        parsed = ArchiveConfig.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid archive config ({config_path}): {exc}") from exc

    config_dir = config_path.parent
    repo_root = config_dir.parent
    repo_root_resolved = repo_root.resolve()

    raw_root_dir = Path(parsed.raw_root_dir).expanduser()
    if not raw_root_dir.is_absolute():
        raw_root_dir = (repo_root / raw_root_dir).resolve()
        if not raw_root_dir.is_relative_to(repo_root_resolved):
            raise ValueError("archive raw_root_dir must resolve within repo root")
    else:
        raw_root_dir = raw_root_dir.resolve()

    return parsed.model_copy(update={"raw_root_dir": raw_root_dir})


@lru_cache(maxsize=8)
def _get_archive_config_cached(
    config_path: str, mtime_ns: int, size: int
) -> ArchiveConfig:
    _ = (mtime_ns, size)
    return load_archive_config(config_path)


def get_archive_config(path: Optional[Union[str, Path]] = None) -> ArchiveConfig:
    resolved = _resolve_config_path(path)
    try:
        stat = resolved.stat()
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"archive config file not found: {resolved}") from exc

    return _get_archive_config_cached(str(resolved), stat.st_mtime_ns, stat.st_size)


get_archive_config.cache_clear = _get_archive_config_cached.cache_clear  # type: ignore[attr-defined]
