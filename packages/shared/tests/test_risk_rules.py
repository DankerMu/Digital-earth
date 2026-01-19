from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from risk.rules import (
    FinalLevelRule,
    RiskFactorId,
    RiskFactorRule,
    RiskRuleModel,
    ThresholdDirection,
    ThresholdScore,
    load_risk_rule_model,
    parse_risk_rule_model,
)


def test_load_risk_rule_model_parses_repo_default_config() -> None:
    model = load_risk_rule_model()
    assert model.schema_version == 1
    assert {factor.id for factor in model.factors} == {
        RiskFactorId.snowfall,
        RiskFactorId.snow_depth,
        RiskFactorId.wind,
        RiskFactorId.temp,
    }
    assert [rule.level for rule in model.final_levels] == [1, 2, 3, 4, 5]

    low = model.evaluate(
        {"snowfall": 0, "snow_depth": 0, "wind": 0, "temp": 10},
    )
    assert low.score == pytest.approx(0.0)
    assert low.level == 1

    mid = model.evaluate(
        {"snowfall": 12, "snow_depth": 12, "wind": 12, "temp": -7},
    )
    assert mid.score == pytest.approx(2.0)
    assert mid.level == 3

    high = model.evaluate(
        {"snowfall": 35, "snow_depth": 35, "wind": 25, "temp": -25},
    )
    assert high.score == pytest.approx(4.0)
    assert high.level == 5


def test_factor_scoring_supports_ascending_thresholds() -> None:
    factor = RiskFactorRule.model_validate(
        {
            "id": "snowfall",
            "weight": 1.0,
            "direction": "ascending",
            "thresholds": [
                {"threshold": 0, "score": 0},
                {"threshold": 10, "score": 1},
                {"threshold": 20, "score": 3},
            ],
        }
    )
    assert factor.direction is ThresholdDirection.ascending
    assert factor.score_for(-1) == 0
    assert factor.score_for(0) == 0
    assert factor.score_for(10) == 1
    assert factor.score_for(19.9) == 1
    assert factor.score_for(20) == 3


def test_factor_scoring_supports_descending_thresholds() -> None:
    factor = RiskFactorRule.model_validate(
        {
            "id": "temp",
            "weight": 1.0,
            "direction": "descending",
            "thresholds": [
                {"threshold": 5, "score": 0},
                {"threshold": 0, "score": 1},
                {"threshold": -10, "score": 2},
            ],
        }
    )
    assert factor.direction is ThresholdDirection.descending
    assert factor.score_for(10) == 0
    assert factor.score_for(1) == 0
    assert factor.score_for(0) == 1
    assert factor.score_for(-9.9) == 1
    assert factor.score_for(-10) == 2


def test_model_accepts_enum_keys_when_evaluating() -> None:
    model = RiskRuleModel.model_validate(
        {
            "schema_version": 1,
            "factors": [
                {
                    "id": "snowfall",
                    "weight": 1,
                    "thresholds": [{"threshold": 0, "score": 0}],
                },
                {
                    "id": "snow_depth",
                    "weight": 1,
                    "thresholds": [{"threshold": 0, "score": 0}],
                },
                {
                    "id": "wind",
                    "weight": 1,
                    "thresholds": [{"threshold": 0, "score": 0}],
                },
                {
                    "id": "temp",
                    "weight": 1,
                    "direction": "descending",
                    "thresholds": [{"threshold": 5, "score": 0}],
                },
            ],
            "final_levels": [
                {"min_score": 0, "level": 1},
                {"min_score": 1, "level": 2},
                {"min_score": 2, "level": 3},
                {"min_score": 3, "level": 4},
                {"min_score": 4, "level": 5},
            ],
        }
    )

    result = model.evaluate(
        {
            RiskFactorId.snowfall: 0,
            RiskFactorId.snow_depth: 0,
            RiskFactorId.wind: 0,
            RiskFactorId.temp: 0,
        }
    )
    assert result.level == 1
    assert result.score == pytest.approx(0.0)


def test_evaluate_rejects_missing_values() -> None:
    model = load_risk_rule_model()
    with pytest.raises(ValueError, match="Missing factor values"):
        model.evaluate({"snowfall": 0})


def test_risk_rule_model_validation_rejects_threshold_ordering() -> None:
    with pytest.raises(ValidationError, match="strictly increasing"):
        RiskFactorRule.model_validate(
            {
                "id": "snowfall",
                "weight": 1.0,
                "direction": "ascending",
                "thresholds": [
                    {"threshold": 10, "score": 1},
                    {"threshold": 0, "score": 0},
                ],
            }
        )

    with pytest.raises(ValidationError, match="strictly decreasing"):
        RiskFactorRule.model_validate(
            {
                "id": "temp",
                "weight": 1.0,
                "direction": "descending",
                "thresholds": [
                    {"threshold": 0, "score": 1},
                    {"threshold": 5, "score": 0},
                ],
            }
        )


def test_risk_rule_model_validation_rejects_decreasing_scores() -> None:
    with pytest.raises(ValidationError, match="non-decreasing"):
        RiskFactorRule.model_validate(
            {
                "id": "snowfall",
                "weight": 1.0,
                "thresholds": [
                    {"threshold": 0, "score": 2},
                    {"threshold": 10, "score": 1},
                ],
            }
        )


def test_rule_model_validation_rejects_missing_factors() -> None:
    base_levels = [
        {"min_score": 0, "level": 1},
        {"min_score": 1, "level": 2},
        {"min_score": 2, "level": 3},
        {"min_score": 3, "level": 4},
        {"min_score": 4, "level": 5},
    ]

    with pytest.raises(ValidationError, match="missing factors"):
        RiskRuleModel.model_validate(
            {
                "schema_version": 1,
                "factors": [
                    {
                        "id": "snowfall",
                        "weight": 1,
                        "thresholds": [{"threshold": 0, "score": 0}],
                    },
                    {
                        "id": "wind",
                        "weight": 1,
                        "thresholds": [{"threshold": 0, "score": 0}],
                    },
                    {
                        "id": "temp",
                        "weight": 1,
                        "direction": "descending",
                        "thresholds": [{"threshold": 5, "score": 0}],
                    },
                ],
                "final_levels": base_levels,
            }
        )


def test_rule_model_validation_rejects_invalid_levels() -> None:
    factors = [
        {
            "id": "snowfall",
            "weight": 1,
            "thresholds": [{"threshold": 0, "score": 0}],
        },
        {
            "id": "snow_depth",
            "weight": 1,
            "thresholds": [{"threshold": 0, "score": 0}],
        },
        {"id": "wind", "weight": 1, "thresholds": [{"threshold": 0, "score": 0}]},
        {
            "id": "temp",
            "weight": 1,
            "direction": "descending",
            "thresholds": [{"threshold": 5, "score": 0}],
        },
    ]

    with pytest.raises(ValidationError, match="levels 1-5"):
        RiskRuleModel.model_validate(
            {
                "schema_version": 1,
                "factors": factors,
                "final_levels": [
                    {"min_score": 0, "level": 1},
                    {"min_score": 1, "level": 2},
                    {"min_score": 2, "level": 3},
                    {"min_score": 3, "level": 4},
                ],
            }
        )

    with pytest.raises(ValidationError, match="duplicate levels"):
        RiskRuleModel.model_validate(
            {
                "schema_version": 1,
                "factors": factors,
                "final_levels": [
                    {"min_score": 0, "level": 1},
                    {"min_score": 1, "level": 2},
                    {"min_score": 2, "level": 3},
                    {"min_score": 3, "level": 4},
                    {"min_score": 4, "level": 4},
                ],
            }
        )


def test_parse_risk_rule_model_requires_mapping() -> None:
    with pytest.raises(TypeError, match="must be a mapping"):
        parse_risk_rule_model([])  # type: ignore[arg-type]


def test_load_risk_rule_model_errors_are_clear(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    with pytest.raises(FileNotFoundError, match="Risk rules config file not found"):
        load_risk_rule_model(missing)

    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(":\n- nope\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Failed to load risk rules YAML"):
        load_risk_rule_model(bad_yaml)

    wrong_shape = tmp_path / "wrong_shape.yaml"
    wrong_shape.write_text("- not-a-mapping\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a mapping"):
        load_risk_rule_model(wrong_shape)


def test_models_reject_non_finite_values() -> None:
    with pytest.raises(ValidationError, match="threshold must be a finite number"):
        ThresholdScore.model_validate({"threshold": float("inf"), "score": 0})

    with pytest.raises(ValidationError, match="min_score must be a finite number"):
        FinalLevelRule.model_validate({"min_score": float("nan"), "level": 1})

    model = load_risk_rule_model()
    with pytest.raises(ValueError, match="score must be a finite number"):
        model._map_score_to_level(float("nan"))
