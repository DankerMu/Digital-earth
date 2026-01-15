from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from schemas.effect_preset import (
    EffectPreset,
    EffectPresetsFile,
    EffectType,
    RiskLevel,
    load_effect_presets,
    risk_level_from_intensity,
)


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


@pytest.mark.parametrize(
    ("intensity", "expected"),
    [
        (1, RiskLevel.low),
        (2, RiskLevel.low),
        (3, RiskLevel.medium),
        (4, RiskLevel.high),
        (5, RiskLevel.extreme),
    ],
)
def test_risk_level_mapping(intensity: int, expected: RiskLevel) -> None:
    preset = EffectPreset.model_validate({**_base_preset_payload(), "intensity": intensity})
    assert preset.risk_level == expected
    assert risk_level_from_intensity(intensity) == expected


def test_risk_level_rejects_out_of_range() -> None:
    with pytest.raises(ValueError, match="intensity must be in the range 1-5"):
        risk_level_from_intensity(0)


def test_parses_effect_type_enum() -> None:
    preset = EffectPreset.model_validate(_base_preset_payload())
    assert preset.effect_type is EffectType.rain


def test_color_hint_accepts_string_list_and_map() -> None:
    payload = _base_preset_payload()

    preset_str = EffectPreset.model_validate({**payload, "color_hint": "rgba(10,20,30,0.25)"})
    assert preset_str.color_hint == "rgba(10, 20, 30, 0.25)"

    preset_list = EffectPreset.model_validate({**payload, "color_hint": [10, 20, 30, 0.25]})
    assert preset_list.color_hint == "rgba(10, 20, 30, 0.25)"

    preset_map = EffectPreset.model_validate(
        {**payload, "color_hint": {"r": 10, "g": 20, "b": 30, "a": 0.25}}
    )
    assert preset_map.color_hint == "rgba(10, 20, 30, 0.25)"


@pytest.mark.parametrize(
    "color_hint",
    [
        "rgb(10, 20, 30)",
        "rgba(256, 0, 0, 1)",
        "rgba(0, 0, 0, 2)",
        {"r": 0, "g": 0, "b": 0},
        123,
    ],
)
def test_color_hint_rejects_invalid_values(color_hint: object) -> None:
    payload = _base_preset_payload()
    with pytest.raises(ValidationError):
        EffectPreset.model_validate({**payload, "color_hint": color_hint})


def test_particle_size_accepts_list_or_mapping() -> None:
    payload = _base_preset_payload()

    preset_list = EffectPreset.model_validate({**payload, "particle_size": [0.2, 0.4]})
    assert preset_list.particle_size.min == 0.2
    assert preset_list.particle_size.max == 0.4

    preset_map = EffectPreset.model_validate(
        {**payload, "particle_size": {"min": 0.2, "max": 0.4}}
    )
    assert preset_map.particle_size.min == 0.2
    assert preset_map.particle_size.max == 0.4


def test_particle_size_rejects_invalid_range() -> None:
    payload = _base_preset_payload()
    with pytest.raises(ValidationError, match="particle_size\\.max must be >= particle_size\\.min"):
        EffectPreset.model_validate({**payload, "particle_size": [1.0, 0.5]})


def test_presets_file_schema_version_validation() -> None:
    payload = {"schema_version": 999, "presets": {"p": _base_preset_payload()}}
    with pytest.raises(ValidationError, match="Unsupported effect preset schema_version"):
        EffectPresetsFile.model_validate(payload)


def test_load_effect_presets_parses_repo_default_config() -> None:
    cfg = load_effect_presets()
    assert cfg.schema_version == 1
    assert "light_rain" in cfg.presets
    assert cfg.presets["light_rain"].effect_type is EffectType.rain
    assert cfg.presets["light_rain"].risk_level is RiskLevel.low
    assert cfg.presets["extreme_storm"].risk_level is RiskLevel.extreme


def test_load_effect_presets_errors_are_clear(tmp_path: Path) -> None:
    from schemas.effect_preset import load_effect_presets

    with pytest.raises(FileNotFoundError, match="Effect presets config file not found"):
        load_effect_presets(tmp_path / "missing.yaml")

    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(":\n- nope\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Failed to load effect presets YAML"):
        load_effect_presets(bad_yaml)

    wrong_shape = tmp_path / "wrong_shape.yaml"
    wrong_shape.write_text("- not-a-mapping\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a mapping"):
        load_effect_presets(wrong_shape)

