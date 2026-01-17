"""Risk-related schemas and utilities."""

from .intensity_mapping import (
    DEFAULT_RISK_INTENSITY_CONFIG_PATH,
    EffectParams,
    RiskIntensityMapping,
    build_risk_intensity_lookup,
    load_risk_intensity_mappings,
    merge_risk_level_with_severity,
    parse_risk_intensity_mappings,
)

__all__ = [
    "DEFAULT_RISK_INTENSITY_CONFIG_PATH",
    "EffectParams",
    "RiskIntensityMapping",
    "build_risk_intensity_lookup",
    "load_risk_intensity_mappings",
    "merge_risk_level_with_severity",
    "parse_risk_intensity_mappings",
]
