from __future__ import annotations

from schemas.effect_preset import (  # noqa: F401
    DEFAULT_EFFECT_PRESETS_CONFIG_PATH,
    EffectPreset,
    EffectPresetsFile,
    EffectType,
    RiskLevel,
    load_effect_presets,
    risk_level_from_intensity,
)

from risk.intensity_mapping import (
    RiskIntensityMapping,
    build_risk_intensity_lookup,
    merge_risk_level_with_severity,
)

__all__ = [
    "DEFAULT_EFFECT_PRESETS_CONFIG_PATH",
    "EffectPreset",
    "EffectPresetsFile",
    "EffectType",
    "RiskLevel",
    "get_risk_intensity_for_effect_preset",
    "load_effect_presets",
    "risk_level_from_intensity",
]


def get_risk_intensity_for_effect_preset(
    preset: EffectPreset,
    mappings: tuple[RiskIntensityMapping, ...],
    *,
    severity: int | None = None,
) -> RiskIntensityMapping:
    """Resolve the risk intensity mapping for a given EffectPreset.

    The EffectPreset `intensity` field uses the same 1-5 scale as risk levels.
    """

    merged_level = merge_risk_level_with_severity(preset.intensity, severity)
    lookup = build_risk_intensity_lookup(mappings)
    try:
        return lookup[merged_level]
    except KeyError as exc:
        raise ValueError(
            f"Risk intensity mapping missing level={merged_level}"
        ) from exc
