from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_loads_repo_example_mapping_file() -> None:
    from cldas.config import DEFAULT_CLDAS_MAPPING_PATH, CldasMappingLoader

    assert DEFAULT_CLDAS_MAPPING_PATH.is_file()

    loader = CldasMappingLoader(DEFAULT_CLDAS_MAPPING_PATH)
    config = loader.get(reload=True)

    mappings = config.variables_for(product="CLDAS-V2.0", resolution="0.0625")
    assert set(mappings) == {"TMP", "RHU", "PRE"}

    tmp = mappings["TMP"]
    assert tmp.internal_var == "air_temperature"
    assert tmp.unit == "K"
    assert tmp.scale == 1.0
    assert tmp.offset == 273.15
    assert tmp.missing is not None
    assert tmp.missing.strategy == "interpolate"
    assert tmp.missing.fill_value is None

    pre = mappings["PRE"]
    assert pre.internal_var == "precipitation_amount"
    assert pre.unit == "m"
    assert pre.scale == 0.001
    assert pre.offset == 0.0
    assert pre.missing is not None
    assert pre.missing.strategy == "fill_value"
    assert pre.missing.fill_value == 0.0

    rh = mappings["RHU"]
    assert rh.internal_var == "relative_humidity"
    assert rh.unit == "%"
    assert rh.scale == 1.0
    assert rh.offset == 0.0
    assert rh.missing is not None
    assert rh.missing.strategy == "fill_value"
    assert rh.missing.fill_value == -9999.0


def test_loader_auto_reloads_on_change(tmp_path: Path) -> None:
    from cldas.config import CldasMappingLoader

    path = tmp_path / "mapping.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "defaults:",
                "  scale: 1.0",
                "  offset: 0.0",
                "  missing:",
                "    strategy: fill_value",
                "    fill_value: -9999.0",
                "products:",
                "  CLDAS-V2.0:",
                "    resolutions:",
                '      "0.25":',
                "        variables:",
                "          - source_var: TMP",
                "            internal_var: air_temperature",
                "            unit: K",
                "            offset: 273.15",
                "            missing:",
                "              strategy: interpolate",
                "",
            ]
        ),
        encoding="utf-8",
    )

    loader = CldasMappingLoader(path)
    config1 = loader.get()
    assert (
        config1.variables_for(product="CLDAS-V2.0", resolution="0.25")["TMP"].internal_var
        == "air_temperature"
    )

    mtime_ns = path.stat().st_mtime_ns
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "defaults:",
                "  scale: 1.0",
                "  offset: 0.0",
                "  missing:",
                "    strategy: fill_value",
                "    fill_value: -9999.0",
                "products:",
                "  CLDAS-V2.0:",
                "    resolutions:",
                '      "0.25":',
                "        variables:",
                "          - source_var: TMP",
                "            internal_var: t2m",
                "            unit: K",
                "            offset: 273.15",
                "            missing:",
                "              strategy: interpolate",
                "",
            ]
        ),
        encoding="utf-8",
    )

    if path.stat().st_mtime_ns == mtime_ns:
        os.utime(path, ns=(mtime_ns + 1, mtime_ns + 1))

    config2 = loader.get()
    assert (
        config2.variables_for(product="CLDAS-V2.0", resolution="0.25")["TMP"].internal_var
        == "t2m"
    )

    assert loader.get() is config2

    config3 = loader.get(reload=True)
    assert (
        config3.variables_for(product="CLDAS-V2.0", resolution="0.25")["TMP"].internal_var
        == "t2m"
    )


def test_missing_file_raises(tmp_path: Path) -> None:
    from cldas.config import CldasMappingLoader

    missing = tmp_path / "does_not_exist.yaml"
    with pytest.raises(FileNotFoundError):
        CldasMappingLoader(missing).load()


def test_invalid_missing_strategy_config_raises(tmp_path: Path) -> None:
    from cldas.config import CldasMappingLoader

    path = tmp_path / "invalid.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "products:",
                "  CLDAS-V2.0:",
                "    resolutions:",
                '      "0.25":',
                "        variables:",
                "          - source_var: TMP",
                "            internal_var: air_temperature",
                "            unit: K",
                "            missing:",
                "              strategy: fill_value",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid CLDAS mapping config"):
        CldasMappingLoader(path).load()


def test_variables_for_unknown_product_and_resolution(tmp_path: Path) -> None:
    from cldas.config import CldasMappingLoader

    path = tmp_path / "mapping.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "products:",
                "  CLDAS-V2.0:",
                "    resolutions:",
                '      "0.25":',
                "        variables: []",
                "",
            ]
        ),
        encoding="utf-8",
    )

    config = CldasMappingLoader(path).load()

    with pytest.raises(KeyError, match="Unknown product"):
        config.variables_for(product="CLDAS-V2.2", resolution="0.25")

    with pytest.raises(KeyError, match="Unknown resolution"):
        config.variables_for(product="CLDAS-V2.0", resolution="0.5")


def test_duplicate_source_var_rejected(tmp_path: Path) -> None:
    from cldas.config import CldasMappingLoader

    path = tmp_path / "dup.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "products:",
                "  CLDAS-V2.0:",
                "    resolutions:",
                '      "0.25":',
                "        variables:",
                "          - source_var: TMP",
                "            internal_var: t2m",
                "            unit: K",
                "            missing:",
                "              strategy: interpolate",
                "          - source_var: TMP",
                "            internal_var: t2m_2",
                "            unit: K",
                "            missing:",
                "              strategy: interpolate",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate source_var"):
        CldasMappingLoader(path).load()


def test_unsupported_schema_version_rejected(tmp_path: Path) -> None:
    from cldas.config import CldasMappingLoader

    path = tmp_path / "v2.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 2",
                "products: {}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported schema_version"):
        CldasMappingLoader(path).load()


def test_applies_default_scale_offset_and_missing(tmp_path: Path) -> None:
    from cldas.config import CldasMappingLoader

    path = tmp_path / "defaults.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "defaults:",
                "  scale: 2.0",
                "  offset: 10.0",
                "  missing:",
                "    strategy: fill_value",
                "    fill_value: 123.0",
                "products:",
                "  CLDAS-V2.0:",
                "    resolutions:",
                '      "0.25":',
                "        variables:",
                "          - source_var: A",
                "            internal_var: a",
                "            unit: m",
                "",
            ]
        ),
        encoding="utf-8",
    )

    mapping = CldasMappingLoader(path).load().variables_for(product="CLDAS-V2.0", resolution="0.25")["A"]
    assert mapping.scale == 2.0
    assert mapping.offset == 10.0
    assert mapping.missing is not None
    assert mapping.missing.strategy == "fill_value"
    assert mapping.missing.fill_value == 123.0


def test_interpolate_strategy_rejects_fill_value(tmp_path: Path) -> None:
    from cldas.config import CldasMappingLoader

    path = tmp_path / "invalid_interpolate.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "products:",
                "  CLDAS-V2.0:",
                "    resolutions:",
                '      "0.25":',
                "        variables:",
                "          - source_var: TMP",
                "            internal_var: air_temperature",
                "            unit: K",
                "            missing:",
                "              strategy: interpolate",
                "              fill_value: 0.0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be omitted when strategy=interpolate"):
        CldasMappingLoader(path).load()


def test_duplicate_internal_var_rejected(tmp_path: Path) -> None:
    from cldas.config import CldasMappingLoader

    path = tmp_path / "dup_internal.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "products:",
                "  CLDAS-V2.0:",
                "    resolutions:",
                '      "0.25":',
                "        variables:",
                "          - source_var: TMP",
                "            internal_var: t2m",
                "            unit: K",
                "            missing:",
                "              strategy: interpolate",
                "          - source_var: TMP2",
                "            internal_var: t2m",
                "            unit: K",
                "            missing:",
                "              strategy: interpolate",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate internal_var"):
        CldasMappingLoader(path).load()


def test_rejects_non_mapping_yaml_top_level(tmp_path: Path) -> None:
    from cldas.config import CldasMappingLoader

    path = tmp_path / "not_mapping.yaml"
    path.write_text("- 1\n- 2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a mapping at top-level"):
        CldasMappingLoader(path).load()


def test_rejects_invalid_yaml_syntax(tmp_path: Path) -> None:
    from cldas.config import CldasMappingLoader

    path = tmp_path / "broken.yaml"
    path.write_text("products: [\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid YAML"):
        CldasMappingLoader(path).load()


def test_relative_paths_resolve_to_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from cldas.config import CldasMappingLoader

    monkeypatch.chdir(tmp_path)
    path = tmp_path / "mapping.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "products:",
                "  CLDAS-V2.0:",
                "    resolutions:",
                '      "0.25":',
                "        variables: []",
                "",
            ]
        ),
        encoding="utf-8",
    )

    loader = CldasMappingLoader("mapping.yaml")
    assert loader.path == path.resolve()
    assert loader.reload().schema_version == 1


def test_getters_cache_loader_instance() -> None:
    from cldas.config import get_cldas_mapping_config, get_cldas_mapping_loader

    first = get_cldas_mapping_loader()
    second = get_cldas_mapping_loader()
    assert first is second

    config = get_cldas_mapping_config(reload=True)
    assert "CLDAS-V2.0" in config.products
