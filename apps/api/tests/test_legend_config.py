from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from legend_config import LegendConfigItem, get_legend_config_payload, normalize_layer_type
from legend_config import _get_legend_payload_cached as get_legend_payload_cached


def _write_legend(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_legend_config_item_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValidationError):
        LegendConfigItem.model_validate(
            {"colors": ["#000000"], "thresholds": [0, 1], "labels": ["0"]}
        )


def test_legend_config_item_rejects_non_increasing_thresholds() -> None:
    with pytest.raises(ValidationError):
        LegendConfigItem.model_validate(
            {"colors": ["#000000", "#FFFFFF"], "thresholds": [0, 0], "labels": ["0", "0"]}
        )


def test_legend_config_item_rejects_empty_color() -> None:
    with pytest.raises(ValidationError):
        LegendConfigItem.model_validate(
            {"colors": ["  "], "thresholds": [0], "labels": ["0"]}
        )


def test_legend_config_item_rejects_empty_label() -> None:
    with pytest.raises(ValidationError):
        LegendConfigItem.model_validate(
            {"colors": ["#000000"], "thresholds": [0], "labels": ["  "]}
        )


def test_normalize_layer_type_supports_cloud_and_precip_aliases() -> None:
    assert normalize_layer_type("cloud") == "cloud"
    assert normalize_layer_type("precip") == "precipitation"


def test_legends_dir_supports_explicit_relative_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_legend(
        tmp_path / "legends" / "temperature.json",
        '{"colors":["#000000"],"thresholds":[0],"labels":["0"]}',
    )
    payload = get_legend_config_payload("temperature", legends_dir="legends")
    assert payload.config.thresholds == [0.0]


def test_legends_dir_supports_env_relative_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DIGITAL_EARTH_LEGENDS_DIR", "legends")
    _write_legend(
        tmp_path / "legends" / "temperature.json",
        '{"colors":["#000000"],"thresholds":[0],"labels":["0"]}',
    )
    payload = get_legend_config_payload("temperature")
    assert payload.config.colors == ["#000000"]


def test_legends_dir_defaults_to_repo_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DIGITAL_EARTH_LEGENDS_DIR", raising=False)
    payload = get_legend_config_payload("temperature")
    assert payload.config.colors


def test_get_legend_payload_cached_raises_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        get_legend_payload_cached("temperature", str(tmp_path / "missing.json"), 0, 0)


def test_get_legend_config_payload_rejects_invalid_json(tmp_path: Path) -> None:
    legends_dir = tmp_path / "legends"
    _write_legend(legends_dir / "temperature.json", "not-json")
    with pytest.raises(ValueError, match="not valid JSON"):
        get_legend_config_payload("temperature", legends_dir=legends_dir)


def test_get_legend_config_payload_rejects_non_object_json(tmp_path: Path) -> None:
    legends_dir = tmp_path / "legends"
    _write_legend(legends_dir / "temperature.json", "[]")
    with pytest.raises(ValueError, match="must be a JSON object"):
        get_legend_config_payload("temperature", legends_dir=legends_dir)


def test_get_legend_config_payload_rejects_invalid_payload(tmp_path: Path) -> None:
    legends_dir = tmp_path / "legends"
    _write_legend(
        legends_dir / "temperature.json",
        '{"colors":["#000000"],"thresholds":[0,1],"labels":["0"]}',
    )
    with pytest.raises(ValueError, match="Invalid legend config"):
        get_legend_config_payload("temperature", legends_dir=legends_dir)

