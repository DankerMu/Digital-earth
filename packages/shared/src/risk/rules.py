from __future__ import annotations

import math
from enum import Enum
from functools import cached_property
from pathlib import Path
from typing import Any, Final, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

SUPPORTED_SCHEMA_VERSIONS: Final[set[int]] = {1}
SUPPORTED_RISK_LEVELS: Final[tuple[int, ...]] = (1, 2, 3, 4, 5)


class RiskFactorId(str, Enum):
    snowfall = "snowfall"
    snow_depth = "snow_depth"
    wind = "wind"
    temp = "temp"


REQUIRED_RISK_FACTORS: Final[tuple[RiskFactorId, ...]] = (
    RiskFactorId.snowfall,
    RiskFactorId.snow_depth,
    RiskFactorId.wind,
    RiskFactorId.temp,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_RISK_RULES_CONFIG_PATH = REPO_ROOT / "config" / "risk-rules.yaml"


class ThresholdDirection(str, Enum):
    ascending = "ascending"
    descending = "descending"


class ThresholdScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: float
    score: float = Field(ge=0)

    @model_validator(mode="after")
    def _validate_finite(self) -> "ThresholdScore":
        if not math.isfinite(float(self.threshold)):
            raise ValueError("threshold must be a finite number")
        if not math.isfinite(float(self.score)):
            raise ValueError("score must be a finite number")
        return self


class RiskFactorRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: RiskFactorId
    weight: float = Field(gt=0)
    direction: ThresholdDirection = ThresholdDirection.ascending
    thresholds: tuple[ThresholdScore, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_thresholds_and_weight(self) -> "RiskFactorRule":
        if not math.isfinite(float(self.weight)):
            raise ValueError("weight must be a finite number")

        thresholds = self.thresholds
        if not thresholds:
            raise ValueError("thresholds must not be empty")

        ascending = self.direction == ThresholdDirection.ascending

        seen: set[float] = set()
        prev_threshold: float | None = None
        prev_score: float | None = None

        for item in thresholds:
            threshold = float(item.threshold)
            score = float(item.score)
            if threshold in seen:
                raise ValueError("thresholds must be unique")
            seen.add(threshold)

            if prev_threshold is not None:
                if ascending and threshold <= prev_threshold:
                    raise ValueError(
                        "thresholds must be strictly increasing for ascending direction"
                    )
                if not ascending and threshold >= prev_threshold:
                    raise ValueError(
                        "thresholds must be strictly decreasing for descending direction"
                    )
            if prev_score is not None and score < prev_score:
                raise ValueError("threshold scores must be non-decreasing")

            prev_threshold = threshold
            prev_score = score

        return self

    def score_for(self, value: float) -> float:
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"{self.id.value} must be a finite number")

        thresholds = self.thresholds
        selected = float(thresholds[0].score)

        if self.direction == ThresholdDirection.ascending:
            for rule in thresholds[1:]:
                if numeric >= float(rule.threshold):
                    selected = float(rule.score)
                else:
                    break
        else:
            for rule in thresholds[1:]:
                if numeric <= float(rule.threshold):
                    selected = float(rule.score)
                else:
                    break

        return selected


class FinalLevelRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_score: float
    level: int = Field(ge=1, le=5)

    @model_validator(mode="after")
    def _validate_finite(self) -> "FinalLevelRule":
        if not math.isfinite(float(self.min_score)):
            raise ValueError("min_score must be a finite number")
        return self


class RiskFactorEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: RiskFactorId
    value: float
    score: float
    weight: float
    normalized_weight: float
    contribution: float


class RiskEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float
    level: int
    factors: tuple[RiskFactorEvaluation, ...]


class RiskRuleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    factors: tuple[RiskFactorRule, ...]
    final_levels: tuple[FinalLevelRule, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_schema(self) -> "RiskRuleModel":
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"Unsupported risk rules schema_version={self.schema_version}; "
                f"supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )

        ids = [factor.id for factor in self.factors]
        if len(ids) != len(set(ids)):
            raise ValueError("factors must not contain duplicates")

        required = set(REQUIRED_RISK_FACTORS)
        present = set(ids)
        missing = sorted(required - present, key=lambda item: item.value)
        if missing:
            raise ValueError(
                "risk rules missing factors: "
                + ", ".join(item.value for item in missing)
            )

        levels = list(self.final_levels)
        levels.sort(key=lambda item: float(item.min_score))

        if not levels:
            raise ValueError("final_levels must not be empty")

        seen_levels: set[int] = set()
        for prev, curr in zip(levels, levels[1:]):
            if float(curr.min_score) <= float(prev.min_score):
                raise ValueError("final level min_score values must be increasing")
            if curr.level < prev.level:
                raise ValueError("final levels must be non-decreasing")
        for item in levels:
            if item.level in seen_levels:
                raise ValueError("final_levels must not contain duplicate levels")
            seen_levels.add(item.level)

        if seen_levels != set(SUPPORTED_RISK_LEVELS):
            missing_levels = sorted(set(SUPPORTED_RISK_LEVELS) - seen_levels)
            extra_levels = sorted(seen_levels - set(SUPPORTED_RISK_LEVELS))
            details: list[str] = []
            if missing_levels:
                details.append(
                    "missing: " + ", ".join(str(level) for level in missing_levels)
                )
            if extra_levels:
                details.append(
                    "extra: " + ", ".join(str(level) for level in extra_levels)
                )
            raise ValueError(
                "final_levels must define levels 1-5"
                + (f" ({'; '.join(details)})" if details else "")
            )

        self.final_levels = tuple(levels)
        return self

    @cached_property
    def _factor_lookup(self) -> dict[RiskFactorId, RiskFactorRule]:
        return {factor.id: factor for factor in self.factors}

    @cached_property
    def _total_weight(self) -> float:
        return float(sum(float(rule.weight) for rule in self.factors))

    def evaluate(
        self, values: Mapping[str | RiskFactorId, float]
    ) -> RiskEvaluationResult:
        resolved: dict[RiskFactorId, float] = {}
        for key, value in values.items():
            factor_id = key if isinstance(key, RiskFactorId) else RiskFactorId(str(key))
            resolved[factor_id] = float(value)

        required = set(REQUIRED_RISK_FACTORS)
        missing = sorted(required - set(resolved), key=lambda item: item.value)
        if missing:
            raise ValueError(
                "Missing factor values: " + ", ".join(item.value for item in missing)
            )

        total_weight = self._total_weight
        if total_weight <= 0:
            raise ValueError("Total factor weight must be > 0")

        factor_results: list[RiskFactorEvaluation] = []
        total_score = 0.0

        for factor_id in REQUIRED_RISK_FACTORS:
            rule = self._factor_lookup[factor_id]
            value = float(resolved[factor_id])
            score = rule.score_for(value)
            normalized_weight = float(rule.weight) / total_weight
            contribution = normalized_weight * score
            total_score += contribution
            factor_results.append(
                RiskFactorEvaluation(
                    id=factor_id,
                    value=value,
                    score=score,
                    weight=float(rule.weight),
                    normalized_weight=normalized_weight,
                    contribution=contribution,
                )
            )

        level = self._map_score_to_level(total_score)
        return RiskEvaluationResult(
            score=float(total_score),
            level=level,
            factors=tuple(factor_results),
        )

    def _map_score_to_level(self, score: float) -> int:
        numeric = float(score)
        if not math.isfinite(numeric):
            raise ValueError("score must be a finite number")

        levels = self.final_levels
        selected = int(levels[0].level)
        for rule in levels[1:]:
            if numeric >= float(rule.min_score):
                selected = int(rule.level)
            else:
                break
        return selected


def _resolve_config_path(path: str | Path | None) -> Path:
    if path is None:
        return DEFAULT_RISK_RULES_CONFIG_PATH
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    return candidate


def parse_risk_rule_model(data: Mapping[str, Any]) -> RiskRuleModel:
    if not isinstance(data, Mapping):
        raise TypeError("data must be a mapping")
    return RiskRuleModel.model_validate(data)


def load_risk_rule_model(path: str | Path | None = None) -> RiskRuleModel:
    config_path = _resolve_config_path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Risk rules config file not found: {config_path}")

    raw_text = config_path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]

        data = yaml.safe_load(raw_text)
    except Exception as exc:
        raise ValueError(f"Failed to load risk rules YAML: {config_path}") from exc

    if not isinstance(data, Mapping):
        raise ValueError(f"Risk rules config must be a mapping: {config_path}")

    return parse_risk_rule_model(data)
