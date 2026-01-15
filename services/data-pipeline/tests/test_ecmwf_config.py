from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _base_version_payload() -> dict:
    return {
        "variables": {
            "sfc": ["2t", "10u", "10v", "tp", "ptype", "tcc"],
            "pl": ["t", "u", "v", "r", "gh"],
        },
        "pressure_levels_hpa": [850, 700, 500, 300],
        "lead_time_hours": [
            {"start": 0, "end": 72, "step": 3},
            {"start": 72, "end": 240, "step": 6},
        ],
    }


def test_loads_repo_default_config() -> None:
    from ecmwf.config import load_ecmwf_variables_config

    config = load_ecmwf_variables_config()
    assert config.version == "v1"
    assert config.variables.sfc == ["2t", "10u", "10v", "tp", "ptype", "tcc"]
    assert config.variables.pl == ["t", "u", "v", "r", "gh"]
    assert config.pressure_levels_hpa == [850, 700, 500, 300]

    lead_times = config.lead_times_hours()
    assert lead_times[0] == 0
    assert lead_times[-1] == 240
    assert 72 in lead_times
    assert 75 not in lead_times
    assert 78 in lead_times
    assert len(lead_times) == 53


def test_getter_caches_and_supports_version_override() -> None:
    from ecmwf.config import get_ecmwf_variables_config

    get_ecmwf_variables_config.cache_clear()
    first = get_ecmwf_variables_config(version="v1")
    second = get_ecmwf_variables_config(version="v1")
    assert first is second
    assert first.version == "v1"


def test_unknown_version_raises_key_error() -> None:
    from ecmwf.config import load_ecmwf_variables_config

    with pytest.raises(KeyError, match="version not found"):
        load_ecmwf_variables_config(version="nope")


def test_supports_legacy_single_version_schema(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    payload = _base_version_payload()
    payload["version"] = "v-legacy"
    payload["variables"]["sfc"].extend([" 2t ", "2t"])
    payload["pressure_levels_hpa"] = [300, 850, 700, 850, 500]

    _write_yaml(tmp_path / "cfg.yaml", payload)

    from ecmwf.config import load_ecmwf_variables_config

    config = load_ecmwf_variables_config("cfg.yaml")
    assert config.version == "v-legacy"
    assert config.variables.sfc == ["2t", "10u", "10v", "tp", "ptype", "tcc"]
    assert config.pressure_levels_hpa == [850, 700, 500, 300]


def test_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    from ecmwf.config import load_ecmwf_variables_config

    _write_yaml(
        tmp_path / "cfg.yaml",
        {
            "schema_version": 999,
            "default_version": "v1",
            "versions": {"v1": _base_version_payload()},
        },
    )

    with pytest.raises(ValueError, match="Unsupported ECMWF config schema_version"):
        load_ecmwf_variables_config(tmp_path / "cfg.yaml")


def test_default_version_must_exist(tmp_path: Path) -> None:
    from ecmwf.config import load_ecmwf_variables_config

    _write_yaml(
        tmp_path / "cfg.yaml",
        {
            "schema_version": 1,
            "default_version": "missing",
            "versions": {"v1": _base_version_payload()},
        },
    )

    with pytest.raises(ValueError, match="default_version"):
        load_ecmwf_variables_config(tmp_path / "cfg.yaml")


def test_invalid_lead_time_rule_raises_validation_error(tmp_path: Path) -> None:
    from ecmwf.config import load_ecmwf_variables_config

    payload = _base_version_payload()
    payload["lead_time_hours"] = [{"start": 10, "end": 0, "step": 3}]
    _write_yaml(
        tmp_path / "cfg.yaml",
        {"schema_version": 1, "default_version": "v1", "versions": {"v1": payload}},
    )

    with pytest.raises(ValidationError, match="lead time rule end must be >= start"):
        load_ecmwf_variables_config(tmp_path / "cfg.yaml")

