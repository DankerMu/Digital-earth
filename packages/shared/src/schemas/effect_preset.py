from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

SUPPORTED_SCHEMA_VERSIONS: Final[set[int]] = {1}

SHARED_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EFFECT_PRESETS_CONFIG_PATH = SHARED_ROOT / "config" / "effect_presets.yaml"

_RGBA_PATTERN = re.compile(
    r"^rgba\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*"
    r"((?:0(?:\.\d+)?)|(?:1(?:\.0+)?))\s*\)$",
    re.IGNORECASE,
)


class EffectType(str, Enum):
    rain = "rain"
    snow = "snow"
    fog = "fog"
    wind = "wind"
    storm = "storm"


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    extreme = "extreme"


def risk_level_from_intensity(intensity: int) -> RiskLevel:
    if intensity in (1, 2):
        return RiskLevel.low
    if intensity == 3:
        return RiskLevel.medium
    if intensity == 4:
        return RiskLevel.high
    if intensity == 5:
        return RiskLevel.extreme
    raise ValueError("intensity must be in the range 1-5")


class ParticleSizeRange(BaseModel):
    min: float = Field(gt=0)
    max: float = Field(gt=0)

    @model_validator(mode="after")
    def _validate_range(self) -> "ParticleSizeRange":
        if self.max < self.min:
            raise ValueError("particle_size.max must be >= particle_size.min")
        return self


def _normalize_rgba(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (list, tuple)) and len(value) == 4:
        r, g, b, a = value
        text = f"rgba({r}, {g}, {b}, {a})"
    elif isinstance(value, dict) and {"r", "g", "b", "a"} <= set(value):
        text = f"rgba({value['r']}, {value['g']}, {value['b']}, {value['a']})"
    else:
        raise ValueError(
            "color_hint must be a rgba() string, [r,g,b,a] list, or {r,g,b,a} map"
        )

    match = _RGBA_PATTERN.match(text)
    if not match:
        raise ValueError(
            "color_hint must match rgba(r,g,b,a) with r,g,b in 0-255 and a in 0-1"
        )

    r, g, b = (int(match.group(i)) for i in range(1, 4))
    a = float(match.group(4))
    if any(channel < 0 or channel > 255 for channel in (r, g, b)):
        raise ValueError("color_hint rgb channels must be in 0-255")
    if a < 0 or a > 1:
        raise ValueError("color_hint alpha channel must be in 0-1")

    return f"rgba({r}, {g}, {b}, {a:g})"


class EffectPreset(BaseModel):
    effect_type: EffectType
    intensity: int = Field(ge=1, le=5)
    duration: float = Field(ge=0, description="Seconds; 0 means 'until disabled'")
    color_hint: str = Field(description="RGBA hint, e.g. rgba(255, 255, 255, 0.8)")
    spawn_rate: float = Field(ge=0, description="Particle spawn rate")
    particle_size: ParticleSizeRange
    wind_influence: float = Field(ge=0, description="Wind field influence coefficient")

    @field_validator("color_hint", mode="before")
    @classmethod
    def _validate_color_hint(cls, value: Any) -> Any:
        return _normalize_rgba(value)

    @field_validator("particle_size", mode="before")
    @classmethod
    def _coerce_particle_size_range(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return {"min": value[0], "max": value[1]}
        return value

    @computed_field(return_type=RiskLevel)
    @property
    def risk_level(self) -> RiskLevel:
        return risk_level_from_intensity(self.intensity)


class EffectPresetsFile(BaseModel):
    schema_version: int
    presets: dict[str, EffectPreset]

    @model_validator(mode="after")
    def _validate_schema_version(self) -> "EffectPresetsFile":
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"Unsupported effect preset schema_version={self.schema_version}; "
                f"supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )
        return self


def _resolve_config_path(path: str | Path | None) -> Path:
    if path is None:
        return DEFAULT_EFFECT_PRESETS_CONFIG_PATH
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    return candidate


def load_effect_presets(path: str | Path | None = None) -> EffectPresetsFile:
    config_path = _resolve_config_path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Effect presets config file not found: {config_path}")

    raw_text = config_path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]

        data = yaml.safe_load(raw_text)
    except Exception as exc:
        raise ValueError(f"Failed to load effect presets YAML: {config_path}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Effect presets config must be a mapping: {config_path}")
    return EffectPresetsFile.model_validate(data)
