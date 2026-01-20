from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Mapping, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from digital_earth_config.settings import _resolve_config_dir


DEFAULT_STATISTICS_CONFIG_NAME: Final[str] = "statistics.yaml"
DEFAULT_STATISTICS_CONFIG_ENV: Final[str] = "DIGITAL_EARTH_STATISTICS_CONFIG"


class OutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_dir: Path = Path("Data/statistics")
    version: str = "v1"


class CldasSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_dir: Optional[Path] = None
    engine: Optional[str] = None


class ArchiveSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_path: Optional[Path] = None
    engine: Optional[str] = None


class SourcesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cldas: CldasSourceConfig = Field(default_factory=CldasSourceConfig)
    archive: ArchiveSourceConfig = Field(default_factory=ArchiveSourceConfig)


class StatisticsComputeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    percentiles: list[float] = Field(default_factory=lambda: [10.0, 50.0, 90.0])
    exact_percentiles_max_samples: int = Field(default=64, ge=0)

    @model_validator(mode="after")
    def _validate_percentiles(self) -> "StatisticsComputeConfig":
        cleaned: list[float] = []
        for raw in self.percentiles:
            value = float(raw)
            if not (0.0 < value < 100.0):
                raise ValueError("percentiles must be in (0, 100)")
            if value not in cleaned:
                cleaned.append(value)
        self.percentiles = cleaned
        return self


class TilesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_dir: Path = Path("Data/tiles")
    formats: list[str] = Field(default_factory=lambda: ["png"])
    layer_prefix: str = "statistics"
    legend_filename: str = "legend.json"

    @model_validator(mode="after")
    def _validate_formats(self) -> "TilesConfig":
        normalized: list[str] = []
        for raw in self.formats:
            fmt = str(raw or "").strip().lower()
            if fmt == "":
                continue
            if fmt not in {"png", "webp"}:
                raise ValueError(f"Unsupported tile format: {fmt!r}")
            if fmt not in normalized:
                normalized.append(fmt)
        if not normalized:
            raise ValueError("At least one tile format must be specified")
        self.formats = normalized
        self.layer_prefix = (
            str(self.layer_prefix or "").strip().strip("/") or "statistics"
        )
        self.legend_filename = str(self.legend_filename or "").strip() or "legend.json"
        return self


class StatisticsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    output: OutputConfig = Field(default_factory=OutputConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    statistics: StatisticsComputeConfig = Field(default_factory=StatisticsComputeConfig)
    tiles: TilesConfig = Field(default_factory=TilesConfig)

    @model_validator(mode="after")
    def _validate_schema(self) -> "StatisticsConfig":
        if self.schema_version != 1:
            raise ValueError(f"Unsupported schema_version={self.schema_version}")
        self.output.version = str(self.output.version or "").strip() or "v1"
        return self


def _resolve_config_path(path: Optional[Union[str, Path]]) -> Path:
    if path is not None:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    explicit = os.environ.get(DEFAULT_STATISTICS_CONFIG_ENV)
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    config_dir = _resolve_config_dir(os.environ)
    return config_dir / DEFAULT_STATISTICS_CONFIG_NAME


def _parse_yaml(text: str, *, source: Path) -> Mapping[str, Any]:
    try:
        data = yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Failed to load statistics YAML: {source}") from exc

    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        raise ValueError(f"statistics config must be a mapping: {source}")
    return data


def load_statistics_config(path: Optional[Union[str, Path]] = None) -> StatisticsConfig:
    config_path = _resolve_config_path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"statistics config file not found: {config_path}")

    raw_text = config_path.read_text(encoding="utf-8")
    data = dict(_parse_yaml(raw_text, source=config_path))

    try:
        parsed = StatisticsConfig.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid statistics config ({config_path}): {exc}") from exc

    config_dir = config_path.parent
    repo_root = config_dir.parent
    repo_root_resolved = repo_root.resolve()

    def resolve_path(value: Optional[Path]) -> Optional[Path]:
        if value is None:
            return None
        candidate = Path(value).expanduser()
        if candidate.is_absolute():
            return candidate.resolve()
        resolved = (repo_root / candidate).resolve()
        if not resolved.is_relative_to(repo_root_resolved):
            raise ValueError("statistics paths must resolve within repo root")
        return resolved

    output_root_dir = (
        resolve_path(parsed.output.root_dir) or repo_root / "Data/statistics"
    )
    tiles_root_dir = resolve_path(parsed.tiles.root_dir) or repo_root / "Data/tiles"
    cldas_root_dir = resolve_path(parsed.sources.cldas.root_dir)
    archive_dataset_path = resolve_path(parsed.sources.archive.dataset_path)

    parsed = parsed.model_copy(
        update={
            "output": parsed.output.model_copy(update={"root_dir": output_root_dir}),
            "tiles": parsed.tiles.model_copy(update={"root_dir": tiles_root_dir}),
            "sources": parsed.sources.model_copy(
                update={
                    "cldas": parsed.sources.cldas.model_copy(
                        update={"root_dir": cldas_root_dir}
                    ),
                    "archive": parsed.sources.archive.model_copy(
                        update={"dataset_path": archive_dataset_path}
                    ),
                }
            ),
        }
    )
    return parsed


@lru_cache(maxsize=8)
def _get_statistics_config_cached(
    config_path: str, mtime_ns: int, size: int
) -> StatisticsConfig:
    _ = (mtime_ns, size)
    return load_statistics_config(config_path)


def get_statistics_config(path: Optional[Union[str, Path]] = None) -> StatisticsConfig:
    resolved = _resolve_config_path(path)
    try:
        stat = resolved.stat()
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"statistics config file not found: {resolved}"
        ) from exc

    return _get_statistics_config_cached(str(resolved), stat.st_mtime_ns, stat.st_size)


get_statistics_config.cache_clear = _get_statistics_config_cached.cache_clear  # type: ignore[attr-defined]
