from __future__ import annotations

from pathlib import Path

import pytest
import yaml


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_loads_repo_default_tiling_config() -> None:
    from tiling.config import load_tiling_config

    config = load_tiling_config()
    assert config.crs == "EPSG:4326"
    assert config.tile_size == 256
    assert config.global_.min_zoom == 0
    assert config.global_.max_zoom == 6
    assert config.event.min_zoom == 8
    assert config.event.max_zoom == 10


def test_getter_caches_by_mtime_and_size() -> None:
    from tiling.config import get_tiling_config

    get_tiling_config.cache_clear()
    first = get_tiling_config()
    second = get_tiling_config()
    assert first is second


def test_rejects_unsupported_crs(tmp_path: Path) -> None:
    from tiling.config import load_tiling_config

    _write_yaml(
        tmp_path / "cfg.yaml",
        {
            "tiling": {
                "crs": "EPSG:3857",
                "global": {"min_zoom": 0, "max_zoom": 6},
                "event": {"min_zoom": 8, "max_zoom": 10},
                "tile_size": 256,
            }
        },
    )

    with pytest.raises(ValueError, match="Unsupported tiling CRS"):
        load_tiling_config(tmp_path / "cfg.yaml")


def test_rejects_overlapping_zoom_ranges(tmp_path: Path) -> None:
    from tiling.config import load_tiling_config

    _write_yaml(
        tmp_path / "cfg.yaml",
        {
            "tiling": {
                "crs": "EPSG:4326",
                "global": {"min_zoom": 0, "max_zoom": 8},
                "event": {"min_zoom": 8, "max_zoom": 10},
                "tile_size": 256,
            }
        },
    )

    with pytest.raises(ValueError, match="global zoom range must end before event"):
        load_tiling_config(tmp_path / "cfg.yaml")


def test_rejects_non_mapping_yaml(tmp_path: Path) -> None:
    from tiling.config import load_tiling_config

    path = tmp_path / "cfg.yaml"
    path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(ValueError, match="tiling config must be a mapping"):
        load_tiling_config(path)
