from __future__ import annotations

from pathlib import Path

import pytest

from legend import compute_legend_version, load_legend, normalize_legend_for_clients


def test_load_cldas_tmp_legend() -> None:
    legend = load_legend("cldas", "tmp", "legend.json")
    assert legend["title"] == "温度"
    assert legend["unit"] == "°C"
    assert legend["type"] == "gradient"
    stops = legend["stops"]
    assert isinstance(stops, list)
    assert len(stops) == 3
    assert stops[0]["value"] == -20
    assert stops[0]["color"] == "#3B82F6"
    assert stops[1]["value"] == 0
    assert stops[1]["color"] == "#FFFFFF"
    assert stops[2]["value"] == 40
    assert stops[2]["color"] == "#EF4444"


def test_normalize_legend_for_clients_adds_version_min_max_and_color_stops() -> None:
    raw = load_legend("cldas", "tmp", "legend.json")
    normalized = normalize_legend_for_clients(raw)

    assert normalized["unit"] == "°C"
    assert normalized["min"] == -20
    assert normalized["max"] == 40
    assert isinstance(normalized["colorStops"], list)
    assert len(normalized["colorStops"]) == 3
    assert normalized["colorStops"][0]["value"] == -20
    assert normalized["colorStops"][0]["color"] == "#3B82F6"
    assert normalized["colorStops"][-1]["value"] == 40
    assert normalized["version"] == compute_legend_version(raw)
    assert len(normalized["version"]) == 64


def test_legend_version_changes_when_config_changes() -> None:
    legend = load_legend("cldas", "tmp", "legend.json")
    version = compute_legend_version(legend)

    mutated = dict(legend)
    mutated["unit"] = "K"
    assert compute_legend_version(mutated) != version


def test_legend_version_ignores_derived_fields() -> None:
    legend = load_legend("cldas", "tmp", "legend.json")
    version = compute_legend_version(legend)
    normalized = normalize_legend_for_clients(legend)
    assert compute_legend_version(normalized) == version


def test_load_legend_errors_are_clear(tmp_path: Path) -> None:
    from legend import LegendLoadError, load_legend

    with pytest.raises(FileNotFoundError, match="Legend file not found"):
        load_legend("does-not-exist.json")

    bad = tmp_path / "bad.json"
    bad.write_text("not-json", encoding="utf-8")
    import legend as legend_module

    original_root = legend_module.LEGEND_ROOT
    legend_module.LEGEND_ROOT = tmp_path
    try:
        with pytest.raises(LegendLoadError, match="not valid JSON"):
            load_legend("bad.json")
    finally:
        legend_module.LEGEND_ROOT = original_root
