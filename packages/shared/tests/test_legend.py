from __future__ import annotations

from pathlib import Path

import pytest

from legend import load_legend


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
