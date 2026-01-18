from __future__ import annotations

import asyncio
import json
import runpy
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _write_retention_yaml(
    path: Path,
    *,
    raw_keep: int = 2,
    cube_keep: int = 2,
    tiles_keep: int = 1,
    referenced_versions_path: str = "config/tiles-references.yaml",
    audit_log_path: str = ".cache/audit/retention.jsonl",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "raw:",
                "  enabled: true",
                "  root_dir: Data/raw",
                f"  keep_n_runs: {raw_keep}",
                "cube:",
                "  enabled: true",
                "  root_dir: Data/cube",
                f"  keep_n_runs: {cube_keep}",
                "tiles:",
                "  enabled: true",
                "  root_dir: Data/tiles",
                f"  keep_n_versions: {tiles_keep}",
                f"  referenced_versions_path: {referenced_versions_path}",
                "audit:",
                f"  log_path: {audit_log_path}",
                "scheduler:",
                "  enabled: false",
                '  cron: "0 3 * * *"',
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_retention_config_loads_and_resolves_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))

    retention_yaml = config_dir / "retention.yaml"
    _write_retention_yaml(retention_yaml, referenced_versions_path="config/pins.yaml")

    from retention.config import get_retention_config, load_retention_config

    cfg = load_retention_config(retention_yaml)
    assert cfg.raw.root_dir == (tmp_path / "Data" / "raw").resolve()
    assert cfg.cube.root_dir == (tmp_path / "Data" / "cube").resolve()
    assert cfg.tiles.root_dir == (tmp_path / "Data" / "tiles").resolve()
    assert (
        cfg.tiles.referenced_versions_path
        == (tmp_path / "config" / "pins.yaml").resolve()
    )
    assert (
        cfg.audit.log_path
        == (tmp_path / ".cache" / "audit" / "retention.jsonl").resolve()
    )

    get_retention_config.cache_clear()
    cfg2 = get_retention_config()
    assert cfg2.raw.keep_n_runs == cfg.raw.keep_n_runs


def test_retention_config_rejects_relative_escape(tmp_path: Path) -> None:
    from retention.config import load_retention_config

    retention_yaml = tmp_path / "config" / "retention.yaml"
    retention_yaml.parent.mkdir(parents=True, exist_ok=True)
    retention_yaml.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "raw:",
                "  root_dir: ../outside",
                "",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(
        ValueError, match="retention raw.root_dir must resolve within repo root"
    ):
        load_retention_config(retention_yaml)


def test_audit_logger_writes_jsonl(tmp_path: Path) -> None:
    from retention.audit import AuditLogger

    log_path = tmp_path / "audit.jsonl"
    audit = AuditLogger(log_path=log_path)

    ev = audit.record(event="test.event", run_id="r", payload={"x": 1})
    assert ev.event == "test.event"
    assert ev.run_id == "r"

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event"] == "test.event"
    assert payload["run_id"] == "r"
    assert payload["x"] == 1


def test_run_retention_cleanup_deletes_old_runs_and_unreferenced_tiles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))

    retention_yaml = config_dir / "retention.yaml"
    _write_retention_yaml(retention_yaml, raw_keep=2, cube_keep=2, tiles_keep=1)

    refs_path = config_dir / "tiles-references.yaml"
    refs_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "layers:",
                "  cldas/tmp:",
                "    - 20240101T000000Z",
                "",
            ]
        ),
        encoding="utf-8",
    )

    raw_root = tmp_path / "Data" / "raw"
    cube_root = tmp_path / "Data" / "cube"
    for root in (raw_root, cube_root):
        for source in ("ecmwf", "cldas"):
            source_dir = root / source
            source_dir.mkdir(parents=True, exist_ok=True)
            for run in ("2024010100", "2024010200", "2024010300"):
                run_dir = source_dir / run
                (run_dir / "x").mkdir(parents=True, exist_ok=True)
                (run_dir / "x" / "data.bin").write_bytes(run.encode())
            (source_dir / "notes").mkdir(parents=True, exist_ok=True)

    tiles_root = tmp_path / "Data" / "tiles"
    layer_dir = tiles_root / "cldas" / "tmp"
    layer_dir.mkdir(parents=True, exist_ok=True)
    (layer_dir / "legend.json").write_text("{}", encoding="utf-8")
    for version in ("20240101T000000Z", "20240102T000000Z", "20240103T000000Z"):
        (layer_dir / version / "6" / "0").mkdir(parents=True, exist_ok=True)
        (layer_dir / version / "6" / "0" / "0.png").write_bytes(b"png")

    other_layer = tiles_root / "foo"
    other_layer.mkdir(parents=True, exist_ok=True)
    (other_layer / "legend.json").write_text("{}", encoding="utf-8")
    for version in ("20240101T000000Z", "20240102T000000Z"):
        (other_layer / version).mkdir(parents=True, exist_ok=True)
        (other_layer / version / "ok").write_text("1", encoding="utf-8")

    from retention.audit import AuditLogger
    from retention.cleanup import run_retention_cleanup
    from retention.config import load_retention_config

    cfg = load_retention_config(retention_yaml)
    audit = AuditLogger(log_path=cfg.audit.log_path)
    fixed_now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = run_retention_cleanup(cfg, audit=audit, now=fixed_now)

    assert result.deleted_total > 0

    for source in ("ecmwf", "cldas"):
        assert not (raw_root / source / "2024010100").exists()
        assert (raw_root / source / "2024010200").exists()
        assert (raw_root / source / "2024010300").exists()
        assert (raw_root / source / "notes").exists()

        assert not (cube_root / source / "2024010100").exists()
        assert (cube_root / source / "2024010200").exists()
        assert (cube_root / source / "2024010300").exists()
        assert (cube_root / source / "notes").exists()

    # tiles: keep latest (20240103...) and pinned (20240101...), delete middle
    assert (layer_dir / "20240101T000000Z").exists()
    assert not (layer_dir / "20240102T000000Z").exists()
    assert (layer_dir / "20240103T000000Z").exists()

    # other layer: keep only latest
    assert not (other_layer / "20240101T000000Z").exists()
    assert (other_layer / "20240102T000000Z").exists()

    audit_lines = cfg.audit.log_path.read_text(encoding="utf-8").splitlines()
    parsed = [json.loads(line) for line in audit_lines]
    assert parsed[0]["event"] == "retention.cleanup.started"
    assert parsed[-1]["event"] == "retention.cleanup.finished"
    run_ids = {item["run_id"] for item in parsed}
    assert len(run_ids) == 1
    deleted = [item for item in parsed if item["event"] == "retention.cleanup.deleted"]
    assert any(item.get("category") == "raw" for item in deleted)
    assert any(item.get("category") == "cube" for item in deleted)
    assert any(item.get("category") == "tiles" for item in deleted)


def test_retention_cleanup_refuses_symlink_escape(tmp_path: Path) -> None:
    from retention.audit import AuditLogger
    from retention.cleanup import run_retention_cleanup
    from retention.config import RetentionConfig

    raw_root = tmp_path / "raw"
    source_dir = raw_root / "ecmwf"
    source_dir.mkdir(parents=True, exist_ok=True)

    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    (outside / "sentinel").write_text("x", encoding="utf-8")

    link = source_dir / "2024010100"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    cfg = RetentionConfig.model_validate(
        {
            "schema_version": 1,
            "raw": {"enabled": True, "root_dir": str(raw_root), "keep_n_runs": 0},
            "cube": {
                "enabled": False,
                "root_dir": str(tmp_path / "cube"),
                "keep_n_runs": 0,
            },
            "tiles": {
                "enabled": False,
                "root_dir": str(tmp_path / "tiles"),
                "keep_n_versions": 0,
            },
            "audit": {"log_path": str(tmp_path / "audit.jsonl")},
            "scheduler": {"enabled": False, "cron": "0 3 * * *"},
        }
    )
    audit = AuditLogger(log_path=cfg.audit.log_path)

    with pytest.raises(ValueError, match="Refusing to delete symlink"):
        run_retention_cleanup(cfg, audit=audit)

    assert (outside / "sentinel").exists()

    events = [
        json.loads(line)
        for line in cfg.audit.log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events[0]["event"] == "retention.cleanup.started"
    assert events[-1]["event"] == "retention.cleanup.error"


def test_retention_cleanup_refuses_symlink_source_dir(tmp_path: Path) -> None:
    from retention.audit import AuditLogger
    from retention.cleanup import run_retention_cleanup
    from retention.config import RetentionConfig

    raw_root = tmp_path / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)

    outside = tmp_path / "outside"
    run_dir = outside / "ecmwf" / "2024010100"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "sentinel").write_text("x", encoding="utf-8")

    source_link = raw_root / "ecmwf"
    try:
        source_link.symlink_to(outside / "ecmwf", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    cfg = RetentionConfig.model_validate(
        {
            "schema_version": 1,
            "raw": {"enabled": True, "root_dir": str(raw_root), "keep_n_runs": 0},
            "cube": {
                "enabled": False,
                "root_dir": str(tmp_path / "cube"),
                "keep_n_runs": 0,
            },
            "tiles": {
                "enabled": False,
                "root_dir": str(tmp_path / "tiles"),
                "keep_n_versions": 0,
            },
            "audit": {"log_path": str(tmp_path / "audit.jsonl")},
            "scheduler": {"enabled": False, "cron": "0 3 * * *"},
        }
    )
    audit = AuditLogger(log_path=cfg.audit.log_path)

    with pytest.raises(ValueError, match="Refusing to traverse symlink"):
        run_retention_cleanup(cfg, audit=audit)

    assert (run_dir / "sentinel").exists()


def test_retention_cleanup_refuses_symlink_run_dir_even_within_root(
    tmp_path: Path,
) -> None:
    from retention.audit import AuditLogger
    from retention.cleanup import run_retention_cleanup
    from retention.config import RetentionConfig

    raw_root = tmp_path / "raw"
    source_dir = raw_root / "ecmwf"
    source_dir.mkdir(parents=True, exist_ok=True)

    target_run = source_dir / "2024010200"
    target_run.mkdir(parents=True, exist_ok=True)
    (target_run / "sentinel").write_text("x", encoding="utf-8")

    link_run = source_dir / "2024010100"
    try:
        link_run.symlink_to(target_run, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    cfg = RetentionConfig.model_validate(
        {
            "schema_version": 1,
            "raw": {"enabled": True, "root_dir": str(raw_root), "keep_n_runs": 0},
            "cube": {
                "enabled": False,
                "root_dir": str(tmp_path / "cube"),
                "keep_n_runs": 0,
            },
            "tiles": {
                "enabled": False,
                "root_dir": str(tmp_path / "tiles"),
                "keep_n_versions": 0,
            },
            "audit": {"log_path": str(tmp_path / "audit.jsonl")},
            "scheduler": {"enabled": False, "cron": "0 3 * * *"},
        }
    )
    audit = AuditLogger(log_path=cfg.audit.log_path)

    with pytest.raises(ValueError, match="Refusing to delete symlink"):
        run_retention_cleanup(cfg, audit=audit)

    assert (target_run / "sentinel").exists()


def test_retention_cleanup_refuses_symlink_tiles_version(tmp_path: Path) -> None:
    from retention.audit import AuditLogger
    from retention.cleanup import run_retention_cleanup
    from retention.config import RetentionConfig

    tiles_root = tmp_path / "tiles"
    layer_dir = tiles_root / "cldas" / "tmp"
    layer_dir.mkdir(parents=True, exist_ok=True)
    (layer_dir / "legend.json").write_text("{}", encoding="utf-8")

    outside = tmp_path / "outside_version"
    outside.mkdir(parents=True, exist_ok=True)
    (outside / "sentinel").write_text("x", encoding="utf-8")

    symlink_version = layer_dir / "20240101T000000Z"
    try:
        symlink_version.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    (layer_dir / "20240102T000000Z").mkdir(parents=True, exist_ok=True)

    cfg = RetentionConfig.model_validate(
        {
            "schema_version": 1,
            "raw": {
                "enabled": False,
                "root_dir": str(tmp_path / "raw"),
                "keep_n_runs": 0,
            },
            "cube": {
                "enabled": False,
                "root_dir": str(tmp_path / "cube"),
                "keep_n_runs": 0,
            },
            "tiles": {
                "enabled": True,
                "root_dir": str(tiles_root),
                "keep_n_versions": 0,
            },
            "audit": {"log_path": str(tmp_path / "audit.jsonl")},
            "scheduler": {"enabled": False, "cron": "0 3 * * *"},
        }
    )
    audit = AuditLogger(log_path=cfg.audit.log_path)

    with pytest.raises(ValueError, match="Refusing to delete symlink"):
        run_retention_cleanup(cfg, audit=audit)

    assert (outside / "sentinel").exists()


def test_tiles_references_loader_supports_multiple_formats(tmp_path: Path) -> None:
    from retention.refs import load_tiles_references

    yaml_path = tmp_path / "refs.yaml"
    yaml_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "layers:",
                "  a/b:",
                "    - v1",
                "    - v2",
                "",
            ]
        ),
        encoding="utf-8",
    )
    refs = load_tiles_references(yaml_path)
    assert refs == {"a/b": {"v1", "v2"}}

    json_path = tmp_path / "refs.json"
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "references": [
                    {"layer": "a/b", "version": "v3"},
                    {"layer": "c", "version": "v1"},
                ],
            }
        ),
        encoding="utf-8",
    )
    refs2 = load_tiles_references(json_path)
    assert refs2["a/b"] == {"v3"}
    assert refs2["c"] == {"v1"}


def test_tiles_references_loader_handles_missing_and_invalid_files(
    tmp_path: Path,
) -> None:
    from retention.refs import load_tiles_references

    assert load_tiles_references(tmp_path / "missing.yaml") == {}

    bad = tmp_path / "bad.yaml"
    bad.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="references file must be a mapping"):
        load_tiles_references(bad)

    single = tmp_path / "single.yaml"
    single.write_text("foo: v1\n", encoding="utf-8")
    assert load_tiles_references(single) == {"foo": {"v1"}}


def test_retention_config_validates_schema_and_cron() -> None:
    from retention.config import RetentionConfig

    with pytest.raises(ValueError, match="Unsupported retention schema_version"):
        RetentionConfig.model_validate({"schema_version": 2})

    with pytest.raises(ValueError, match="scheduler.cron must not be empty"):
        RetentionConfig.model_validate(
            {"schema_version": 1, "scheduler": {"enabled": False, "cron": ""}}
        )


def test_retention_cleanup_skips_invalid_names_and_files(tmp_path: Path) -> None:
    from retention.audit import AuditLogger
    from retention.cleanup import run_retention_cleanup
    from retention.config import RetentionConfig

    raw_root = tmp_path / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    (raw_root / "README.txt").write_text("x", encoding="utf-8")

    source_dir = raw_root / "ecmwf"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "README.txt").write_text("x", encoding="utf-8")
    (source_dir / "2024010100").mkdir(parents=True, exist_ok=True)
    (source_dir / "2024013200").mkdir(parents=True, exist_ok=True)

    tiles_root = tmp_path / "tiles"
    layer_dir = tiles_root / "cldas" / "tmp"
    layer_dir.mkdir(parents=True, exist_ok=True)
    (layer_dir / "legend.json").write_text("{}", encoding="utf-8")
    (layer_dir / "unknown").mkdir(parents=True, exist_ok=True)
    (layer_dir / "README.txt").write_text("x", encoding="utf-8")
    (layer_dir / "20240101T000000Z").mkdir(parents=True, exist_ok=True)

    cfg = RetentionConfig.model_validate(
        {
            "schema_version": 1,
            "raw": {"enabled": True, "root_dir": str(raw_root), "keep_n_runs": 0},
            "cube": {
                "enabled": False,
                "root_dir": str(tmp_path / "cube"),
                "keep_n_runs": 0,
            },
            "tiles": {
                "enabled": True,
                "root_dir": str(tiles_root),
                "keep_n_versions": 0,
            },
            "audit": {"log_path": str(tmp_path / "audit.jsonl")},
            "scheduler": {"enabled": False, "cron": "0 3 * * *"},
        }
    )

    audit = AuditLogger(log_path=cfg.audit.log_path)
    run_retention_cleanup(cfg, audit=audit)

    assert not (source_dir / "2024010100").exists()
    assert (source_dir / "2024013200").exists()
    assert (layer_dir / "unknown").exists()


def test_retention_cleanup_scheduler_retries_and_uses_cron() -> None:
    from retention.scheduler import ExponentialBackoff, RetentionCleanupScheduler
    from retention.cleanup import RetentionCleanupResult

    sleep_calls: list[float] = []

    async def sleep(delay: float) -> None:
        sleep_calls.append(delay)

    attempts = {"count": 0}

    def cleanup() -> RetentionCleanupResult:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("transient")
        return RetentionCleanupResult(run_id="r")

    scheduler = RetentionCleanupScheduler(
        cron="0 * * * *",
        cleanup=cleanup,
        max_retries=3,
        backoff=ExponentialBackoff(base_seconds=1.0, factor=2.0, max_seconds=10.0),
        sleep=sleep,
        now=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    base = datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc)
    assert scheduler.next_run_after(base) == datetime(
        2026, 1, 1, 1, 0, tzinfo=timezone.utc
    )

    result = asyncio.run(scheduler.run_once())
    assert result.run_id == "r"
    assert sleep_calls == [1.0, 2.0]


def test_retention_cleanup_scheduler_run_forever_stops_on_event() -> None:
    from retention.cleanup import RetentionCleanupResult
    from retention.scheduler import RetentionCleanupScheduler

    scheduler = RetentionCleanupScheduler(
        cron="0 * * * *", cleanup=lambda: RetentionCleanupResult(run_id="r")
    )

    async def runner() -> None:
        stop_event = asyncio.Event()
        asyncio.get_running_loop().call_soon(stop_event.set)
        await scheduler.run_forever(stop_event=stop_event)

    asyncio.run(runner())


def test_retention_cli_cleanup_smoke(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))

    retention_yaml = config_dir / "retention.yaml"
    _write_retention_yaml(
        retention_yaml,
        raw_keep=0,
        cube_keep=0,
        tiles_keep=0,
        referenced_versions_path="",
        audit_log_path=".cache/audit/retention.jsonl",
    )

    from retention.main import main

    exit_code = main(["--config", str(retention_yaml), "cleanup"])
    assert exit_code == 0


def test_retention_module_entrypoint_smoke(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))

    retention_yaml = config_dir / "retention.yaml"
    _write_retention_yaml(
        retention_yaml,
        raw_keep=0,
        cube_keep=0,
        tiles_keep=0,
        referenced_versions_path="",
        audit_log_path=".cache/audit/retention.jsonl",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["retention", "--config", str(retention_yaml), "cleanup"],
    )
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("retention", run_name="__main__")
    assert exc.value.code == 0
