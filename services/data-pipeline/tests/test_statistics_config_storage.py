from __future__ import annotations

from pathlib import Path

import pytest


def test_load_statistics_config_resolves_paths(tmp_path: Path) -> None:
    from statistics.config import load_statistics_config

    cfg_path = tmp_path / "statistics.yaml"
    cfg_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "output:",
                "  root_dir: Data/statistics",
                "  version: v9",
                "statistics:",
                "  percentiles: [25, 75]",
                "  exact_percentiles_max_samples: 10",
                "tiles:",
                "  root_dir: Data/tiles",
                "  formats: [png, webp]",
                "  layer_prefix: statistics",
                "  legend_filename: legend.json",
                "",
            ]
        ),
        encoding="utf-8",
    )

    cfg = load_statistics_config(cfg_path)
    assert cfg.output.version == "v9"
    assert cfg.statistics.percentiles == [25.0, 75.0]
    assert cfg.statistics.exact_percentiles_max_samples == 10
    assert cfg.output.root_dir.is_absolute()
    assert cfg.tiles.root_dir.is_absolute()


def test_load_statistics_config_rejects_invalid_tile_format(tmp_path: Path) -> None:
    from statistics.config import load_statistics_config

    cfg_path = tmp_path / "statistics.yaml"
    cfg_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "tiles:",
                "  formats: [tiff]",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported tile format"):
        load_statistics_config(cfg_path)


def test_statistics_store_rejects_path_traversal(tmp_path: Path) -> None:
    from statistics.storage import StatisticsStore

    store = StatisticsStore(tmp_path)
    with pytest.raises(ValueError, match="source"):
        store.resolve_paths(
            source="../evil",
            variable="TMP",
            window_kind="monthly",
            window_key="202001",
            version="v1",
        )


def test_statistics_store_builds_expected_paths(tmp_path: Path) -> None:
    from statistics.storage import StatisticsStore

    store = StatisticsStore(tmp_path)
    artifact = store.resolve_paths(
        source="cldas",
        variable="TMP",
        window_kind="monthly",
        window_key="202001",
        version="v1",
    )
    assert artifact.dataset_path.is_absolute()
    assert artifact.dataset_path.name == "statistics.nc"
    assert artifact.metadata_path.name.endswith(".meta.json")
