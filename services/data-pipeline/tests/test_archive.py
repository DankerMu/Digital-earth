from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from archive.config import get_archive_config, load_archive_config
from archive.manager import ArchiveManager
from archive.manifest import ManifestGenerator


def _write_archive_yaml(path: Path, *, raw_root_dir: str = "Data/raw") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                f"raw_root_dir: {raw_root_dir}",
                "keep_n_runs: 5",
                "checksum_algorithm: sha256",
                "manifest_filename: manifest.json",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_archive_config_loads_and_resolves_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    archive_yaml = config_dir / "archive.yaml"
    _write_archive_yaml(archive_yaml)

    cfg = load_archive_config(archive_yaml)
    assert cfg.raw_root_dir == (tmp_path / "Data" / "raw").resolve()
    assert cfg.keep_n_runs == 5
    assert cfg.checksum_algorithm == "sha256"
    assert cfg.manifest_filename == "manifest.json"

    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_archive_config.cache_clear()
    cfg2 = get_archive_config()
    assert cfg2.raw_root_dir == cfg.raw_root_dir
    manager = ArchiveManager.from_config(source="ecmwf", run_time="2024010100")
    assert manager.raw_root_dir == cfg.raw_root_dir
    assert manager.source == "ecmwf"
    assert manager.run_time == "2024010100"

    monkeypatch.setenv("DIGITAL_EARTH_ARCHIVE_CONFIG", str(archive_yaml))
    cfg3 = load_archive_config()
    assert cfg3.raw_root_dir == cfg.raw_root_dir


def test_archive_config_rejects_relative_escape(tmp_path: Path) -> None:
    archive_yaml = tmp_path / "config" / "archive.yaml"
    _write_archive_yaml(archive_yaml, raw_root_dir="../outside")
    with pytest.raises(ValueError, match="raw_root_dir must resolve within repo root"):
        load_archive_config(archive_yaml)


def test_archive_config_supports_relative_paths_and_reports_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    archive_yaml = tmp_path / "config" / "archive.yaml"

    _write_archive_yaml(archive_yaml)
    cfg = load_archive_config(Path("config/archive.yaml"))
    assert cfg.raw_root_dir == (tmp_path / "Data" / "raw").resolve()

    monkeypatch.setenv("DIGITAL_EARTH_ARCHIVE_CONFIG", "config/archive.yaml")
    cfg2 = load_archive_config()
    assert cfg2.raw_root_dir == cfg.raw_root_dir

    missing = tmp_path / "config" / "missing.yaml"
    with pytest.raises(FileNotFoundError, match="archive config file not found"):
        load_archive_config(missing)

    _write_archive_yaml(archive_yaml, raw_root_dir=str(tmp_path / "abs-raw"))
    cfg_abs = load_archive_config(archive_yaml)
    assert cfg_abs.raw_root_dir == (tmp_path / "abs-raw").resolve()

    archive_yaml.write_text("schema_version: [", encoding="utf-8")
    with pytest.raises(ValueError, match="Failed to load archive YAML"):
        load_archive_config(archive_yaml)

    archive_yaml.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="archive config must be a mapping"):
        load_archive_config(archive_yaml)

    archive_yaml.write_text("", encoding="utf-8")
    cfg_empty = load_archive_config(archive_yaml)
    assert cfg_empty.keep_n_runs == 5

    archive_yaml.write_text("keep_n_runs: -1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid archive config"):
        load_archive_config(archive_yaml)

    archive_yaml.write_text("schema_version: 999\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid archive config"):
        load_archive_config(archive_yaml)

    archive_yaml.write_text("checksum_algorithm: md5\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid archive config"):
        load_archive_config(archive_yaml)

    archive_yaml.write_text('manifest_filename: ""\n', encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid archive config"):
        load_archive_config(archive_yaml)

    archive_yaml.write_text("manifest_filename: /abs/manifest.json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid archive config"):
        load_archive_config(archive_yaml)

    monkeypatch.delenv("DIGITAL_EARTH_ARCHIVE_CONFIG", raising=False)
    get_archive_config.cache_clear()
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(tmp_path / "no-such-config"))
    with pytest.raises(FileNotFoundError, match="archive config file not found"):
        get_archive_config()


def test_manifest_generate_and_validate_success(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    manager = ArchiveManager(raw_root, source="ecmwf", run_time="2024010100")

    data_dir = manager.data_dir("temperature", "surface")
    data_dir.mkdir(parents=True, exist_ok=True)

    file_a = data_dir / "data_2024010100.bin"
    file_b = data_dir / "data_2024010200.bin"
    file_a.write_bytes(b"alpha")
    file_b.write_bytes(b"beta")

    manifest_path = manager.generate_manifest()
    assert manifest_path.is_file()

    manifest = ManifestGenerator.load(manifest_path)
    assert manifest.version == 1
    assert manifest.source == "ecmwf"
    assert manifest.run_time == "2024010100"
    assert manifest.checksum_algorithm == "sha256"
    assert manifest.time_range.start == "2024-01-01T00:00:00Z"
    assert manifest.time_range.end == "2024-01-02T00:00:00Z"

    paths = {entry.path for entry in manifest.files}
    assert "temperature/surface/data_2024010100.bin" in paths
    assert "temperature/surface/data_2024010200.bin" in paths

    result = manager.validate_manifest(strict=True)
    assert result.ok
    assert result.missing_files == []
    assert result.checksum_mismatches == []
    assert result.extra_files == []


def test_validate_manifest_reports_issues(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    manager = ArchiveManager(raw_root, source="ecmwf", run_time="2024010100")

    data_dir = manager.data_dir("temperature", "surface")
    data_dir.mkdir(parents=True, exist_ok=True)

    file_a = data_dir / "data_2024010100.bin"
    file_b = data_dir / "data_2024010200.bin"
    file_a.write_bytes(b"alpha")
    file_b.write_bytes(b"beta")

    manager.generate_manifest()

    file_a.write_bytes(b"ALPHA")  # checksum mismatch
    file_b.unlink()  # missing
    (data_dir / "extra.bin").write_bytes(b"extra")

    result = manager.validate_manifest()
    assert not result.ok
    assert result.missing_files == ["temperature/surface/data_2024010200.bin"]
    assert [m.path for m in result.checksum_mismatches] == [
        "temperature/surface/data_2024010100.bin"
    ]
    assert result.extra_files == []

    strict_result = manager.validate_manifest(strict=True)
    assert not strict_result.ok
    assert strict_result.extra_files == ["temperature/surface/extra.bin"]

    bad_manifest = manager.manifest_path()
    payload = json.loads(bad_manifest.read_text(encoding="utf-8"))
    payload["files"].append(
        {"path": "../escape.bin", "size_bytes": 0, "checksum": "00"}
    )
    bad_manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid manifest schema"):
        manager.validate_manifest()


def test_validate_manifest_rejects_source_run_time_mismatch(tmp_path: Path) -> None:
    manager = ArchiveManager(tmp_path / "raw", source="ecmwf", run_time="2024010100")
    data_dir = manager.data_dir("temperature", "surface")
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "data_2024010100.bin").write_bytes(b"alpha")

    manager.generate_manifest()
    manifest_path = manager.manifest_path()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["source"] = "cldas"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="Manifest source/run_time mismatch"):
        manager.validate_manifest()


def test_validate_manifest_rejects_symlink_escape(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    manager = ArchiveManager(raw_root, source="ecmwf", run_time="2024010100")
    run_dir = manager.run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)

    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    outside_file = outside / "outside.bin"
    outside_file.write_bytes(b"outside")

    link_dir = run_dir / "linked"
    try:
        link_dir.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "source": "ecmwf",
                "run_time": "2024010100",
                "generated_at": "2024-01-01T00:00:00Z",
                "checksum_algorithm": "sha256",
                "time_range": {"start": None, "end": None},
                "files": [
                    {
                        "path": "linked/outside.bin",
                        "size_bytes": outside_file.stat().st_size,
                        "checksum": "00",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="escapes run_dir"):
        manager.validate_manifest()


def test_manifest_generator_covers_mtime_and_schema_errors(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "manifest.json").write_text("old\n", encoding="utf-8")

    file_a = run_dir / "a.bin"
    file_b = run_dir / "b.bin"
    file_a.write_bytes(b"a")
    file_b.write_bytes(b"b")

    ts1 = 1704067200  # 2024-01-01T00:00:00Z
    ts2 = 1704153600  # 2024-01-02T00:00:00Z
    os.utime(file_a, (ts1, ts1))
    os.utime(file_b, (ts2, ts2))

    generator = ManifestGenerator()
    manifest = generator.generate(run_dir, source="ecmwf", run_time="2024010100")
    assert manifest.time_range.start == "2024-01-01T00:00:00Z"
    assert manifest.time_range.end == "2024-01-02T00:00:00Z"
    assert {entry.path for entry in manifest.files} == {"a.bin", "b.bin"}

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir(parents=True, exist_ok=True)
    empty_manifest = generator.generate(
        empty_dir, source="ecmwf", run_time="2024010100"
    )
    assert empty_manifest.files == []
    assert empty_manifest.time_range.start is None
    assert empty_manifest.time_range.end is None

    with pytest.raises(ValueError, match="Only checksum_algorithm"):
        ManifestGenerator(checksum_algorithm="md5")
    with pytest.raises(ValueError, match="Unsupported manifest_version"):
        ManifestGenerator(manifest_version=2)
    with pytest.raises(FileNotFoundError, match="run_dir not found"):
        generator.generate(tmp_path / "missing", source="ecmwf", run_time="2024010100")

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid manifest JSON"):
        ManifestGenerator.load(bad_json)

    invalid_schema = tmp_path / "invalid.json"
    base_manifest = {
        "version": 1,
        "source": "ecmwf",
        "run_time": "2024010100",
        "generated_at": "2024-01-01T00:00:00Z",
        "checksum_algorithm": "sha256",
        "time_range": {"start": None, "end": None},
        "files": [{"path": "a.bin", "size_bytes": 0, "checksum": "00"}],
    }

    for patch in (
        {"version": 2},
        {"checksum_algorithm": "md5"},
        {"source": ""},
        {"run_time": ""},
    ):
        invalid_schema.write_text(
            json.dumps({**base_manifest, **patch}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Invalid manifest schema"):
            ManifestGenerator.load(invalid_schema)

    ts_dir = tmp_path / "ts-run"
    ts_dir.mkdir(parents=True, exist_ok=True)
    (ts_dir / "good_20240101000000.bin").write_bytes(b"good")
    (ts_dir / "bad14_20240101009999.bin").write_bytes(b"bad14")
    (ts_dir / "bad10_2024013200.bin").write_bytes(b"bad10")

    ts_manifest = generator.generate(ts_dir, source="ecmwf", run_time="2024010100")
    assert ts_manifest.time_range.start == "2024-01-01T00:00:00Z"
    assert ts_manifest.time_range.end == "2024-01-01T00:00:00Z"


def test_cleanup_old_runs(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    manager = ArchiveManager(raw_root, source="ecmwf", run_time="2024010300")
    source_dir = raw_root / "ecmwf"
    source_dir.mkdir(parents=True, exist_ok=True)

    for run in ("2024010100", "2024010200", "2024010300"):
        run_dir = source_dir / run
        (run_dir / "temperature" / "surface").mkdir(parents=True, exist_ok=True)
        (run_dir / "temperature" / "surface" / f"{run}.bin").write_bytes(run.encode())

    (source_dir / "notes").mkdir(parents=True, exist_ok=True)

    deleted = manager.cleanup_old_runs(keep_n=2)
    assert {path.name for path in deleted} == {"2024010100"}
    assert not (source_dir / "2024010100").exists()
    assert (source_dir / "2024010200").exists()
    assert (source_dir / "2024010300").exists()
    assert (source_dir / "notes").exists()

    deleted_all = manager.cleanup_old_runs(keep_n=0)
    assert {path.name for path in deleted_all} == {"2024010200", "2024010300"}
    assert (source_dir / "notes").exists()

    with pytest.raises(ValueError, match="keep_n must be >= 0"):
        manager.cleanup_old_runs(keep_n=-1)


def test_archive_manager_validates_segments_and_refuses_unsafe_cleanup(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="source must not be empty"):
        ArchiveManager(tmp_path / "raw", source="", run_time="2024010100")
    with pytest.raises(ValueError, match="run_time must be a path segment"):
        ArchiveManager(tmp_path / "raw", source="ecmwf", run_time="2024/010100")

    manager = ArchiveManager(tmp_path / "raw", source="ecmwf", run_time="2024010100")
    assert manager.manifest_filename == "manifest.json"

    with pytest.raises(ValueError, match="variable must not be '.' or '..'"):
        manager.data_dir("..", "surface")

    with pytest.raises(ValueError, match="manifest_filename must not be empty"):
        ArchiveManager(
            tmp_path / "raw",
            source="ecmwf",
            run_time="2024010100",
            manifest_filename="",
        )
    with pytest.raises(ValueError, match="Only checksum_algorithm"):
        ArchiveManager(
            tmp_path / "raw",
            source="ecmwf",
            run_time="2024010100",
            checksum_algorithm="md5",
        )

    assert manager.cleanup_old_runs(keep_n=1) == []

    source_dir = manager.raw_root_dir / "ecmwf"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "file.txt").write_text("x", encoding="utf-8")
    (source_dir / "2024013200").mkdir(parents=True, exist_ok=True)

    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    link = source_dir / "2024010100"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    with pytest.raises(ValueError, match="Refusing to delete path outside source_dir"):
        manager.cleanup_old_runs(keep_n=0)
