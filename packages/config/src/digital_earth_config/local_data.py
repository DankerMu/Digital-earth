from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Mapping, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .settings import _resolve_config_dir

SUPPORTED_SCHEMA_VERSIONS: Final[set[int]] = {1}

DEFAULT_LOCAL_DATA_CONFIG_NAME: Final[str] = "local-data.yaml"
DEFAULT_LOCAL_DATA_CONFIG_ENV: Final[str] = "DIGITAL_EARTH_LOCAL_DATA_CONFIG"

DEFAULT_LOCAL_DATA_ROOT_ENV: Final[str] = "DIGITAL_EARTH_LOCAL_DATA_ROOT"
DEFAULT_LOCAL_DATA_CLDAS_DIR_ENV: Final[str] = "DIGITAL_EARTH_LOCAL_DATA_CLDAS_DIR"
DEFAULT_LOCAL_DATA_ECMWF_DIR_ENV: Final[str] = "DIGITAL_EARTH_LOCAL_DATA_ECMWF_DIR"
DEFAULT_LOCAL_DATA_TOWN_FORECAST_DIR_ENV: Final[str] = (
    "DIGITAL_EARTH_LOCAL_DATA_TOWN_FORECAST_DIR"
)


class LocalDataSourcePaths(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cldas: str = "CLDAS"
    ecmwf: str = "EC-forecast/EC预报"
    town_forecast: str = "城镇预报导出"


class LocalDataConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    root_dir: str = "Data"
    sources: LocalDataSourcePaths = Field(default_factory=LocalDataSourcePaths)

    @model_validator(mode="after")
    def _validate_schema_version(self) -> "LocalDataConfig":
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"Unsupported local-data schema_version={self.schema_version}; "
                f"supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )
        return self


@dataclass(frozen=True)
class LocalDataPaths:
    config_path: Path
    root_dir: Path
    cldas_dir: Path
    ecmwf_dir: Path
    town_forecast_dir: Path


def _resolve_config_path(path: Optional[Union[str, Path]]) -> Path:
    if path is not None:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    explicit = os.environ.get(DEFAULT_LOCAL_DATA_CONFIG_ENV)
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    config_dir = _resolve_config_dir(os.environ)
    return config_dir / DEFAULT_LOCAL_DATA_CONFIG_NAME


def _parse_yaml(text: str, *, source: Path) -> Mapping[str, Any]:
    try:
        data = yaml.safe_load(text)
    except Exception as exc:
        raise ValueError(f"Failed to load local-data YAML: {source}") from exc

    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        raise ValueError(f"local-data config must be a mapping: {source}")
    return data


def _env_overrides(environ: Mapping[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {}

    root_dir = environ.get(DEFAULT_LOCAL_DATA_ROOT_ENV)
    if root_dir and root_dir.strip():
        result["root_dir"] = root_dir.strip()

    cldas_dir = environ.get(DEFAULT_LOCAL_DATA_CLDAS_DIR_ENV)
    if cldas_dir and cldas_dir.strip():
        result.setdefault("sources", {})["cldas"] = cldas_dir.strip()

    ecmwf_dir = environ.get(DEFAULT_LOCAL_DATA_ECMWF_DIR_ENV)
    if ecmwf_dir and ecmwf_dir.strip():
        result.setdefault("sources", {})["ecmwf"] = ecmwf_dir.strip()

    town_dir = environ.get(DEFAULT_LOCAL_DATA_TOWN_FORECAST_DIR_ENV)
    if town_dir and town_dir.strip():
        result.setdefault("sources", {})["town_forecast"] = town_dir.strip()

    return result


def _deep_update(base: dict[str, Any], updates: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, Mapping)
            and isinstance(value, dict)
        ):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def _override_signature(environ: Mapping[str, str]) -> str:
    keys = (
        DEFAULT_LOCAL_DATA_ROOT_ENV,
        DEFAULT_LOCAL_DATA_CLDAS_DIR_ENV,
        DEFAULT_LOCAL_DATA_ECMWF_DIR_ENV,
        DEFAULT_LOCAL_DATA_TOWN_FORECAST_DIR_ENV,
    )
    payload = "\n".join(f"{key}={environ.get(key, '')}" for key in keys).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@lru_cache(maxsize=8)
def _get_local_data_config_cached(
    config_path: str, mtime_ns: int, size: int, overrides_sig: str
) -> LocalDataPaths:
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"local-data config file not found: {path}")

    raw = path.read_text(encoding="utf-8")
    data = dict(_parse_yaml(raw, source=path))
    _deep_update(data, _env_overrides(os.environ))

    try:
        parsed = LocalDataConfig.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid local-data config ({path}): {exc}") from exc

    config_dir = path.parent
    repo_root = config_dir.parent

    root_dir = Path(parsed.root_dir).expanduser()
    if not root_dir.is_absolute():
        root_dir = (repo_root / root_dir).resolve()
    else:
        root_dir = root_dir.resolve()

    def resolve_child(child: str) -> Path:
        candidate = Path(child).expanduser()
        if candidate.is_absolute():
            return candidate.resolve()
        return (root_dir / candidate).resolve()

    return LocalDataPaths(
        config_path=path.resolve(),
        root_dir=root_dir,
        cldas_dir=resolve_child(parsed.sources.cldas),
        ecmwf_dir=resolve_child(parsed.sources.ecmwf),
        town_forecast_dir=resolve_child(parsed.sources.town_forecast),
    )


def get_local_data_paths(path: Optional[Union[str, Path]] = None) -> LocalDataPaths:
    resolved = _resolve_config_path(path)
    try:
        stat = resolved.stat()
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"local-data config file not found: {resolved}"
        ) from exc

    return _get_local_data_config_cached(
        str(resolved),
        stat.st_mtime_ns,
        stat.st_size,
        _override_signature(os.environ),
    )


get_local_data_paths.cache_clear = _get_local_data_config_cached.cache_clear  # type: ignore[attr-defined]
