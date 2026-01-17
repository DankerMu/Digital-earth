from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final, Mapping

from pydantic import BaseModel, Field

SUPPORTED_RISK_LEVELS: Final[tuple[int, ...]] = (1, 2, 3, 4, 5)

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_RISK_INTENSITY_CONFIG_PATH = REPO_ROOT / "config" / "risk-intensity.yaml"

_LEVEL_KEY_PATTERN = re.compile(r"^level_(\d+)$", re.IGNORECASE)


class EffectParams(BaseModel):
    particle_count: int = Field(ge=0)
    opacity: float = Field(ge=0, le=1)
    speed: float = Field(ge=0)


class RiskIntensityMapping(BaseModel):
    level: int = Field(ge=1, le=5)
    intensity: float = Field(ge=0, le=1)
    effect_params: EffectParams


def merge_risk_level_with_severity(level: int, severity: int | None = None) -> int:
    """Merge a computed risk level with product severity.

    Rule: take the maximum of the two values (both are expected to be 1-5).
    """

    if level not in SUPPORTED_RISK_LEVELS:
        raise ValueError("level must be in the range 1-5")

    if severity is None:
        return level

    if severity not in SUPPORTED_RISK_LEVELS:
        raise ValueError("severity must be in the range 1-5")

    return max(level, severity)


def build_risk_intensity_lookup(
    mappings: tuple[RiskIntensityMapping, ...],
) -> dict[int, RiskIntensityMapping]:
    lookup: dict[int, RiskIntensityMapping] = {}
    for item in mappings:
        if item.level in lookup:
            raise ValueError(f"Duplicate mapping for level={item.level}")
        lookup[item.level] = item
    return lookup


def _resolve_config_path(path: str | Path | None) -> Path:
    if path is None:
        return DEFAULT_RISK_INTENSITY_CONFIG_PATH
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    return candidate


def _extract_effect_params(
    entry: Mapping[str, Any], *, intensity: float
) -> dict[str, Any]:
    params: Any = entry.get("effect_params")
    if isinstance(params, Mapping):
        params_dict: dict[str, Any] = dict(params)
    else:
        params_dict = dict(entry)

    particle_count = params_dict.get("particle_count", params_dict.get("particles"))
    opacity = params_dict.get("opacity", intensity)
    speed = params_dict.get("speed", intensity)

    return {
        "particle_count": particle_count,
        "opacity": opacity,
        "speed": speed,
    }


def parse_risk_intensity_mappings(
    data: Mapping[str, Any],
) -> tuple[RiskIntensityMapping, ...]:
    entries: list[RiskIntensityMapping] = []

    for key, value in data.items():
        match = _LEVEL_KEY_PATTERN.match(str(key))
        if not match:
            continue

        level = int(match.group(1))
        if not isinstance(value, Mapping):
            raise ValueError(f"{key} must be a mapping")

        if "intensity" not in value:
            raise ValueError(f"{key}.intensity is required")
        intensity = value["intensity"]

        payload = {
            "level": level,
            "intensity": intensity,
            "effect_params": _extract_effect_params(value, intensity=float(intensity)),
        }
        entries.append(RiskIntensityMapping.model_validate(payload))

    if not entries:
        raise ValueError("Risk intensity config must include level_1..level_5 entries")

    entries.sort(key=lambda item: item.level)
    lookup = build_risk_intensity_lookup(tuple(entries))

    missing = [level for level in SUPPORTED_RISK_LEVELS if level not in lookup]
    if missing:
        raise ValueError(
            "Risk intensity config missing levels: "
            + ", ".join(str(level) for level in missing)
        )

    previous_intensity: float | None = None
    for level in SUPPORTED_RISK_LEVELS:
        current = lookup[level].intensity
        if previous_intensity is not None and current <= previous_intensity:
            raise ValueError(
                "Risk intensity must be strictly increasing for levels 1-5"
            )
        previous_intensity = current

    return tuple(lookup[level] for level in SUPPORTED_RISK_LEVELS)


def load_risk_intensity_mappings(
    path: str | Path | None = None,
) -> tuple[RiskIntensityMapping, ...]:
    config_path = _resolve_config_path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Risk intensity config file not found: {config_path}")

    raw_text = config_path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]

        data = yaml.safe_load(raw_text)
    except Exception as exc:
        raise ValueError(f"Failed to load risk intensity YAML: {config_path}") from exc

    if not isinstance(data, Mapping):
        raise ValueError(f"Risk intensity config must be a mapping: {config_path}")

    return parse_risk_intensity_mappings(data)
