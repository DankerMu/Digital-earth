from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional, Union

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

SUPPORTED_SCHEMA_VERSIONS = {1}

DATA_PIPELINE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ECMWF_VARIABLES_CONFIG_PATH = (
    DATA_PIPELINE_ROOT / "config" / "ecmwf_variables.yaml"
)


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized == "" or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


class LeadTimeRule(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    step: int = Field(gt=0)

    @model_validator(mode="after")
    def _validate_range(self) -> "LeadTimeRule":
        if self.end < self.start:
            raise ValueError("lead time rule end must be >= start")
        return self

    def hours(self) -> list[int]:
        return list(range(self.start, self.end + 1, self.step))


class VariableGroups(BaseModel):
    sfc: list[str]
    pl: list[str]

    @field_validator("sfc", "pl", mode="before")
    @classmethod
    def _normalize_variables(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            return _dedupe_preserve_order([str(item) for item in value])
        return value


class EcmwfVariablesConfig(BaseModel):
    version: Optional[str] = None
    variables: VariableGroups
    pressure_levels_hpa: list[int]
    lead_time_hours: list[LeadTimeRule]

    @field_validator("pressure_levels_hpa", mode="before")
    @classmethod
    def _normalize_levels(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            return [int(item) for item in value]
        return value

    @model_validator(mode="after")
    def _validate_levels(self) -> "EcmwfVariablesConfig":
        if any(level <= 0 for level in self.pressure_levels_hpa):
            raise ValueError("pressure levels must be positive hPa values")
        self.pressure_levels_hpa = sorted(set(self.pressure_levels_hpa), reverse=True)
        return self

    def lead_times_hours(self) -> list[int]:
        hours: list[int] = []
        for rule in self.lead_time_hours:
            hours.extend(rule.hours())
        return sorted(set(hours))


class EcmwfVariablesConfigFile(BaseModel):
    schema_version: int
    default_version: str
    versions: dict[str, EcmwfVariablesConfig]

    @model_validator(mode="after")
    def _validate_schema(self) -> "EcmwfVariablesConfigFile":
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"Unsupported ECMWF config schema_version={self.schema_version}; "
                f"supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )
        if self.default_version not in self.versions:
            raise ValueError(
                f"default_version={self.default_version!r} not found in versions"
            )
        return self


def _resolve_config_path(path: Union[str, Path, None]) -> Path:
    if path is None:
        return DEFAULT_ECMWF_VARIABLES_CONFIG_PATH
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    return candidate


def _load_yaml(path: Path) -> Any:
    raw_text = path.read_text(encoding="utf-8")
    return yaml.safe_load(raw_text)


def load_ecmwf_variables_config(
    path: Union[str, Path, None] = None, *, version: Optional[str] = None
) -> EcmwfVariablesConfig:
    config_path = _resolve_config_path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"ECMWF variables config file not found: {config_path}")

    data = _load_yaml(config_path)
    if not isinstance(data, dict):
        raise ValueError(f"ECMWF variables config must be a mapping: {config_path}")

    if "versions" not in data:
        if "version" not in data:
            raise ValueError(
                "ECMWF variables config must contain either 'versions' or 'version'"
            )
        legacy_version = str(data["version"])
        data = {
            "schema_version": data.get("schema_version", 1),
            "default_version": legacy_version,
            "versions": {legacy_version: {k: v for k, v in data.items() if k != "version"}},
        }

    config_file = EcmwfVariablesConfigFile.model_validate(data)
    selected_version = version or config_file.default_version
    if selected_version not in config_file.versions:
        raise KeyError(
            f"ECMWF variables config version not found: {selected_version!r}; "
            f"available: {sorted(config_file.versions)}"
        )

    return config_file.versions[selected_version].model_copy(
        update={"version": selected_version}
    )


@lru_cache
def get_ecmwf_variables_config(
    path: Union[str, Path, None] = None, *, version: Optional[str] = None
) -> EcmwfVariablesConfig:
    resolved = _resolve_config_path(path)
    return load_ecmwf_variables_config(resolved, version=version)
