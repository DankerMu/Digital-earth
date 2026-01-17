from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from effect.preset import get_risk_intensity_for_effect_preset
from risk.intensity_mapping import (
    RiskIntensityMapping,
    build_risk_intensity_lookup,
    load_risk_intensity_mappings,
    merge_risk_level_with_severity,
    parse_risk_intensity_mappings,
)
from schemas.effect_preset import EffectPreset


def _base_preset_payload() -> dict:
    return {
        "effect_type": "rain",
        "intensity": 3,
        "duration": 30,
        "color_hint": "rgba(255, 255, 255, 0.5)",
        "spawn_rate": 10,
        "particle_size": [0.5, 1.0],
        "wind_influence": 0.25,
    }


def test_load_risk_intensity_mappings_parses_repo_default_config() -> None:
    mappings = load_risk_intensity_mappings()
    assert len(mappings) == 5
    assert mappings[0].level == 1
    assert mappings[0].intensity == 0.2
    assert mappings[0].effect_params.particle_count == 100
    assert mappings[-1].level == 5
    assert mappings[-1].intensity == 1.0
    assert mappings[-1].effect_params.particle_count == 1500

    assert all(
        mappings[idx].intensity < mappings[idx + 1].intensity
        for idx in range(len(mappings) - 1)
    )


def test_parse_supports_particles_alias_and_defaults() -> None:
    data = {
        "level_1": {"intensity": 0.2, "particles": 100},
        "level_2": {"intensity": 0.4, "particles": 300},
        "level_3": {"intensity": 0.6, "particles": 600},
        "level_4": {"intensity": 0.8, "particles": 1000},
        "level_5": {"intensity": 1.0, "particles": 1500},
    }

    mappings = parse_risk_intensity_mappings(data)
    assert mappings[2].level == 3
    assert mappings[2].effect_params.opacity == 0.6
    assert mappings[2].effect_params.speed == 0.6


def test_parse_rejects_missing_levels() -> None:
    data = {
        "level_1": {"intensity": 0.2, "particles": 100},
        "level_2": {"intensity": 0.4, "particles": 300},
        "level_3": {"intensity": 0.6, "particles": 600},
        "level_4": {"intensity": 0.8, "particles": 1000},
    }

    with pytest.raises(ValueError, match="missing levels"):
        parse_risk_intensity_mappings(data)


def test_parse_rejects_non_increasing_intensity() -> None:
    data = {
        "level_1": {"intensity": 0.2, "particles": 100},
        "level_2": {"intensity": 0.4, "particles": 300},
        "level_3": {"intensity": 0.4, "particles": 600},
        "level_4": {"intensity": 0.8, "particles": 1000},
        "level_5": {"intensity": 1.0, "particles": 1500},
    }

    with pytest.raises(ValueError, match="strictly increasing"):
        parse_risk_intensity_mappings(data)


def test_build_risk_intensity_lookup_rejects_duplicates() -> None:
    mappings = (
        RiskIntensityMapping.model_validate(
            {
                "level": 1,
                "intensity": 0.2,
                "effect_params": {"particle_count": 100, "opacity": 0.2, "speed": 0.2},
            }
        ),
        RiskIntensityMapping.model_validate(
            {
                "level": 1,
                "intensity": 0.2,
                "effect_params": {"particle_count": 100, "opacity": 0.2, "speed": 0.2},
            }
        ),
    )

    with pytest.raises(ValueError, match="Duplicate mapping"):
        build_risk_intensity_lookup(mappings)


def test_merge_risk_level_with_severity_rule_is_max() -> None:
    assert merge_risk_level_with_severity(3, severity=5) == 5
    assert merge_risk_level_with_severity(5, severity=3) == 5
    assert merge_risk_level_with_severity(2, severity=None) == 2

    with pytest.raises(ValueError, match="level must be in the range 1-5"):
        merge_risk_level_with_severity(0, severity=1)

    with pytest.raises(ValueError, match="severity must be in the range 1-5"):
        merge_risk_level_with_severity(1, severity=6)


def test_effect_preset_integration_resolves_mapping() -> None:
    mappings = parse_risk_intensity_mappings(
        {
            "level_1": {"intensity": 0.2, "particles": 100},
            "level_2": {"intensity": 0.4, "particles": 300},
            "level_3": {"intensity": 0.6, "particles": 600},
            "level_4": {"intensity": 0.8, "particles": 1000},
            "level_5": {"intensity": 1.0, "particles": 1500},
        }
    )

    preset = EffectPreset.model_validate({**_base_preset_payload(), "intensity": 4})
    mapping = get_risk_intensity_for_effect_preset(preset, mappings, severity=2)
    assert mapping.level == 4

    merged = get_risk_intensity_for_effect_preset(preset, mappings, severity=5)
    assert merged.level == 5


def test_load_risk_intensity_mappings_errors_are_clear(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    with pytest.raises(FileNotFoundError, match="Risk intensity config file not found"):
        load_risk_intensity_mappings(missing)

    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(":\n- nope\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Failed to load risk intensity YAML"):
        load_risk_intensity_mappings(bad_yaml)

    wrong_shape = tmp_path / "wrong_shape.yaml"
    wrong_shape.write_text("- not-a-mapping\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a mapping"):
        load_risk_intensity_mappings(wrong_shape)

    missing_particles = tmp_path / "missing_particles.yaml"
    missing_particles.write_text("level_1:\n  intensity: 0.2\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_risk_intensity_mappings(missing_particles)
