from __future__ import annotations

from pathlib import Path

import pytest

from digital_earth_config.local_data import get_local_data_paths


def _write_local_data_config(
    path: Path, *, schema_version: int = 1, root_dir: str = "Data"
) -> None:
    path.write_text(
        "\n".join(
            [
                f"schema_version: {schema_version}",
                f"root_dir: {root_dir}",
                "sources:",
                "  cldas: CLDAS",
                "  ecmwf: EC-forecast/EC预报",
                "  town_forecast: 城镇预报导出",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_get_local_data_paths_resolves_relative_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    _write_local_data_config(config_dir / "local-data.yaml", root_dir="Data")

    (tmp_path / "Data").mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_local_data_paths.cache_clear()
    paths = get_local_data_paths()

    assert paths.config_path == (config_dir / "local-data.yaml").resolve()
    assert paths.root_dir == (tmp_path / "Data").resolve()
    assert paths.cldas_dir == (tmp_path / "Data" / "CLDAS").resolve()
    assert paths.ecmwf_dir == (tmp_path / "Data" / "EC-forecast" / "EC预报").resolve()


def test_local_data_env_overrides_root_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    _write_local_data_config(config_dir / "local-data.yaml", root_dir="Data")

    override_root = tmp_path / "mounted" / "data"
    override_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_LOCAL_DATA_ROOT", str(override_root))
    get_local_data_paths.cache_clear()
    paths = get_local_data_paths()

    assert paths.root_dir == override_root.resolve()
    assert paths.town_forecast_dir == (override_root / "城镇预报导出").resolve()


def test_env_can_override_index_cache_ttl_seconds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    _write_local_data_config(config_dir / "local-data.yaml", root_dir="Data")
    (tmp_path / "Data").mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_LOCAL_DATA_INDEX_CACHE_TTL_SECONDS", "123")
    get_local_data_paths.cache_clear()

    paths = get_local_data_paths()
    assert paths.index_cache_ttl_seconds == 123


def test_invalid_schema_version_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    _write_local_data_config(config_dir / "local-data.yaml", schema_version=2)

    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_local_data_paths.cache_clear()

    with pytest.raises(ValueError, match="Unsupported local-data schema_version"):
        get_local_data_paths()


def test_can_resolve_explicit_config_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    _write_local_data_config(config_dir / "local-data.yaml", root_dir="Data")
    (tmp_path / "Data").mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_local_data_paths.cache_clear()

    paths = get_local_data_paths(config_dir / "local-data.yaml")
    assert paths.root_dir == (tmp_path / "Data").resolve()


def test_env_can_override_config_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "custom.yaml"
    _write_local_data_config(config_file, root_dir="Data")
    (tmp_path / "Data").mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DIGITAL_EARTH_LOCAL_DATA_CONFIG", str(config_file))
    monkeypatch.delenv("DIGITAL_EARTH_CONFIG_DIR", raising=False)
    get_local_data_paths.cache_clear()

    paths = get_local_data_paths()
    assert paths.config_path == config_file.resolve()


def test_empty_yaml_uses_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "local-data.yaml").write_text("", encoding="utf-8")

    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_local_data_paths.cache_clear()
    paths = get_local_data_paths()
    assert paths.root_dir == (tmp_path / "Data").resolve()


def test_rejects_non_mapping_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "local-data.yaml").write_text("- a\n- b\n", encoding="utf-8")

    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_local_data_paths.cache_clear()

    with pytest.raises(ValueError, match="must be a mapping"):
        get_local_data_paths()


def test_rejects_invalid_yaml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "local-data.yaml").write_text("a: [\n", encoding="utf-8")

    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_local_data_paths.cache_clear()

    with pytest.raises(ValueError, match="Failed to load local-data YAML"):
        get_local_data_paths()


def test_env_can_override_source_dirs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    _write_local_data_config(config_dir / "local-data.yaml", root_dir="Data")
    (tmp_path / "Data").mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_LOCAL_DATA_CLDAS_DIR", "CLDAS_OVERRIDE")
    get_local_data_paths.cache_clear()

    paths = get_local_data_paths()
    assert paths.cldas_dir == (tmp_path / "Data" / "CLDAS_OVERRIDE").resolve()


def test_rejects_absolute_source_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "local-data.yaml"
    config_file.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "root_dir: Data",
                "sources:",
                f"  cldas: {tmp_path / 'outside'}",
                "  ecmwf: EC-forecast/EC预报",
                "  town_forecast: 城镇预报导出",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "Data").mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_local_data_paths.cache_clear()

    with pytest.raises(ValueError, match="must be relative"):
        get_local_data_paths()


def test_rejects_source_paths_that_escape_root_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "local-data.yaml"
    config_file.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "root_dir: Data",
                "sources:",
                "  cldas: ../outside",
                "  ecmwf: EC-forecast/EC预报",
                "  town_forecast: 城镇预报导出",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "Data").mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_local_data_paths.cache_clear()

    with pytest.raises(ValueError, match="resolve within"):
        get_local_data_paths()


def test_config_path_must_be_a_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    directory_path = config_dir / "local-data.yaml"
    directory_path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_local_data_paths.cache_clear()

    with pytest.raises(FileNotFoundError, match="local-data config file not found"):
        get_local_data_paths()
