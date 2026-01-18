from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Mapping, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from digital_earth_config.settings import _resolve_config_dir

DEFAULT_TILING_CONFIG_NAME: Final[str] = "tiling.yaml"
DEFAULT_TILING_CONFIG_ENV: Final[str] = "DIGITAL_EARTH_TILING_CONFIG"

SUPPORTED_TILING_CRS: Final[set[str]] = {"EPSG:4326"}


class ZoomRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_zoom: int = Field(ge=0)
    max_zoom: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_range(self) -> "ZoomRange":
        if self.max_zoom < self.min_zoom:
            raise ValueError("max_zoom must be >= min_zoom")
        return self


class TilingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crs: str
    global_: ZoomRange = Field(alias="global")
    event: ZoomRange
    tile_size: int = Field(default=256, gt=0)

    @model_validator(mode="after")
    def _validate_tiling(self) -> "TilingConfig":
        normalized_crs = (self.crs or "").strip().upper()
        if normalized_crs not in SUPPORTED_TILING_CRS:
            raise ValueError(
                f"Unsupported tiling CRS={self.crs!r}; supported: {sorted(SUPPORTED_TILING_CRS)}"
            )
        self.crs = normalized_crs

        if self.global_.max_zoom >= self.event.min_zoom:
            raise ValueError(
                "global zoom range must end before event zoom range starts"
            )

        return self


class TilingConfigFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tiling: TilingConfig


def _resolve_config_path(path: Optional[Union[str, Path]]) -> Path:
    if path is not None:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    explicit = os.environ.get(DEFAULT_TILING_CONFIG_ENV)
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    config_dir = _resolve_config_dir(os.environ)
    return config_dir / DEFAULT_TILING_CONFIG_NAME


def _parse_yaml(text: str, *, source: Path) -> Mapping[str, Any]:
    try:
        data = yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Failed to load tiling YAML: {source}") from exc

    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        raise ValueError(f"tiling config must be a mapping: {source}")
    return data


def load_tiling_config(path: Optional[Union[str, Path]] = None) -> TilingConfig:
    config_path = _resolve_config_path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"tiling config file not found: {config_path}")

    raw = config_path.read_text(encoding="utf-8")
    data = dict(_parse_yaml(raw, source=config_path))

    try:
        parsed = TilingConfigFile.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid tiling config ({config_path}): {exc}") from exc

    return parsed.tiling


@lru_cache(maxsize=8)
def _get_tiling_config_cached(
    config_path: str, mtime_ns: int, size: int
) -> TilingConfig:
    _ = (mtime_ns, size)
    return load_tiling_config(config_path)


def get_tiling_config(path: Optional[Union[str, Path]] = None) -> TilingConfig:
    resolved = _resolve_config_path(path)
    try:
        stat = resolved.stat()
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"tiling config file not found: {resolved}") from exc

    return _get_tiling_config_cached(str(resolved), stat.st_mtime_ns, stat.st_size)


get_tiling_config.cache_clear = _get_tiling_config_cached.cache_clear  # type: ignore[attr-defined]
