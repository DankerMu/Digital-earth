from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional, Union

from pydantic import ValidationError

from risk.rules import RiskRuleModel, load_risk_rule_model

__all__ = [
    "RiskRulesPayload",
    "get_risk_rules_payload",
]

DEFAULT_RISK_RULES_CONFIG_ENV: str = "DIGITAL_EARTH_RISK_RULES_CONFIG"
DEFAULT_RISK_RULES_CONFIG_NAME: str = "risk-rules.yaml"


@dataclass(frozen=True)
class RiskRulesPayload:
    etag: str
    model: RiskRuleModel


def _resolve_config_path(path: Optional[Union[str, Path]]) -> Path:
    if path is not None:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    explicit = os.environ.get(DEFAULT_RISK_RULES_CONFIG_ENV)
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    config_dir = os.environ.get("DIGITAL_EARTH_CONFIG_DIR")
    if config_dir:
        candidate_dir = Path(config_dir).expanduser()
        if not candidate_dir.is_absolute():
            candidate_dir = (Path.cwd() / candidate_dir).resolve()
        candidate = candidate_dir / DEFAULT_RISK_RULES_CONFIG_NAME
        if candidate.is_file():
            return candidate

    cwd = Path.cwd()
    for candidate_root in (cwd, *cwd.parents):
        candidate = candidate_root / "config" / DEFAULT_RISK_RULES_CONFIG_NAME
        if candidate.is_file():
            return candidate

    return cwd / "config" / DEFAULT_RISK_RULES_CONFIG_NAME


@lru_cache(maxsize=4)
def _get_risk_rules_payload_cached(
    path: str, mtime_ns: int, size: int
) -> RiskRulesPayload:
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Risk rules config file not found: {config_path}")

    raw_bytes = config_path.read_bytes()
    etag = f'"sha256-{hashlib.sha256(raw_bytes).hexdigest()}"'

    try:
        model = load_risk_rule_model(config_path)
    except ValidationError as exc:
        raise ValueError(f"Invalid risk rules config: {config_path}") from exc

    return RiskRulesPayload(etag=etag, model=model)


def get_risk_rules_payload(
    path: Optional[Union[str, Path]] = None,
) -> RiskRulesPayload:
    resolved = _resolve_config_path(path)
    try:
        stat = resolved.stat()
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Risk rules config file not found: {resolved}"
        ) from exc
    return _get_risk_rules_payload_cached(str(resolved), stat.st_mtime_ns, stat.st_size)


get_risk_rules_payload.cache_clear = _get_risk_rules_payload_cached.cache_clear  # type: ignore[attr-defined]
