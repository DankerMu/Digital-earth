from __future__ import annotations

from pathlib import Path

import pytest


def _write_risk_rules_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "",
                "factors:",
                "  - id: snowfall",
                "    weight: 1.0",
                "    direction: ascending",
                "    thresholds:",
                "      - threshold: 0",
                "        score: 0",
                "",
                "  - id: snow_depth",
                "    weight: 1.0",
                "    direction: ascending",
                "    thresholds:",
                "      - threshold: 0",
                "        score: 0",
                "",
                "  - id: wind",
                "    weight: 1.0",
                "    direction: ascending",
                "    thresholds:",
                "      - threshold: 0",
                "        score: 0",
                "",
                "  - id: temp",
                "    weight: 1.0",
                "    direction: descending",
                "    thresholds:",
                "      - threshold: 5",
                "        score: 0",
                "",
                "final_levels:",
                "  - min_score: 0",
                "    level: 1",
                "  - min_score: 1",
                "    level: 2",
                "  - min_score: 2",
                "    level: 3",
                "  - min_score: 3",
                "    level: 4",
                "  - min_score: 4",
                "    level: 5",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_get_risk_rules_payload_supports_relative_path_argument(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_risk_rules_config(tmp_path / "risk-rules.yaml")

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    payload = get_risk_rules_payload("risk-rules.yaml")
    assert payload.model.schema_version == 1


def test_get_risk_rules_payload_resolves_relative_env_var(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_risk_rules_config(tmp_path / "risk-rules.yaml")
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", "risk-rules.yaml")

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    payload = get_risk_rules_payload()
    assert payload.model.schema_version == 1


def test_get_risk_rules_payload_resolves_relative_config_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "cfg"
    _write_risk_rules_config(config_dir / "risk-rules.yaml")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", "cfg")

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    payload = get_risk_rules_payload()
    assert payload.model.schema_version == 1


def test_get_risk_rules_payload_searches_repo_config_when_no_env_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DIGITAL_EARTH_RISK_RULES_CONFIG", raising=False)
    monkeypatch.delenv("DIGITAL_EARTH_CONFIG_DIR", raising=False)

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    payload = get_risk_rules_payload()
    assert payload.model.schema_version == 1


def test_get_risk_rules_payload_fallback_path_missing_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DIGITAL_EARTH_RISK_RULES_CONFIG", raising=False)
    monkeypatch.delenv("DIGITAL_EARTH_CONFIG_DIR", raising=False)

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    with pytest.raises(FileNotFoundError, match="Risk rules config file not found"):
        get_risk_rules_payload()


def test_get_risk_rules_payload_rejects_directory_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    directory = tmp_path / "rules-dir"
    directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DIGITAL_EARTH_RISK_RULES_CONFIG", str(directory))

    from risk_rules_config import get_risk_rules_payload

    get_risk_rules_payload.cache_clear()
    with pytest.raises(FileNotFoundError, match="Risk rules config file not found"):
        get_risk_rules_payload()
