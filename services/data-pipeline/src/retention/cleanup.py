from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from retention.audit import AuditLogger
from retention.config import RetentionConfig
from retention.refs import load_tiles_references

logger = logging.getLogger(__name__)


def _assert_no_symlink(path: Path, *, label: str) -> None:
    if path.is_symlink():
        raise ValueError(f"Refusing to {label} symlink: {path}")


def _assert_resolved_within_root(path: Path, *, root: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(
            f"Refusing to {label} path outside root_dir: {resolved} (root_dir={root})"
        )
    return resolved


def _assert_no_symlink_components(path: Path, *, root: Path, label: str) -> None:
    try:
        rel = path.relative_to(root)
    except ValueError:
        raise ValueError(
            f"Refusing to {label} path outside root_dir: {path} (root_dir={root})"
        ) from None

    cursor = root
    for part in rel.parts:
        cursor = cursor / part
        _assert_no_symlink(cursor, label=label)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_run_time(value: str) -> Optional[datetime]:
    if len(value) == 10 and value.isdigit():
        try:
            return datetime.strptime(value, "%Y%m%d%H").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _parse_tile_version(value: str) -> Optional[datetime]:
    normalized = (value or "").strip()
    if normalized == "":
        return None
    try:
        return datetime.strptime(normalized, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


@dataclass(frozen=True)
class RetentionCleanupResult:
    run_id: str
    raw_deleted: list[Path] = field(default_factory=list)
    cube_deleted: list[Path] = field(default_factory=list)
    tiles_deleted: list[Path] = field(default_factory=list)

    @property
    def deleted_total(self) -> int:
        return len(self.raw_deleted) + len(self.cube_deleted) + len(self.tiles_deleted)


def _cleanup_run_tree(
    root_dir: Path,
    *,
    keep_n_runs: int,
    category: str,
    audit: AuditLogger,
    audit_run_id: str,
    now: Optional[datetime] = None,
) -> list[Path]:
    if keep_n_runs < 0:
        raise ValueError("keep_n_runs must be >= 0")

    root = root_dir.resolve()
    if not root.is_dir():
        return []

    deleted: list[Path] = []
    for source_dir in sorted(root.iterdir()):
        if not source_dir.is_dir():
            continue
        _assert_no_symlink(source_dir, label="traverse")

        source_dir_resolved = _assert_resolved_within_root(
            source_dir, root=root, label="traverse"
        )
        runs: list[tuple[datetime, Path]] = []
        for child in source_dir.iterdir():
            if not child.is_dir():
                continue
            parsed = _parse_run_time(child.name)
            if parsed is None:
                continue
            runs.append((parsed, child))

        runs.sort(key=lambda item: item[0])
        if keep_n_runs == 0:
            to_delete = [path for _, path in runs]
        else:
            to_delete = (
                [path for _, path in runs[:-keep_n_runs]]
                if len(runs) > keep_n_runs
                else []
            )

        for path in to_delete:
            _assert_no_symlink(path, label="delete")
            resolved = _assert_resolved_within_root(path, root=root, label="delete")
            if not resolved.is_relative_to(source_dir_resolved):
                raise ValueError(f"Refusing to delete path outside source_dir: {path}")
            shutil.rmtree(path)
            deleted.append(resolved)
            audit.record(
                event="retention.cleanup.deleted",
                run_id=audit_run_id,
                payload={
                    "category": category,
                    "source": source_dir.name,
                    "run_time": path.name,
                    "path": str(resolved),
                },
                now=now,
            )

    return deleted


def _discover_tile_layers(tiles_root: Path) -> list[Path]:
    root = tiles_root.resolve()
    if not root.is_dir():
        return []

    layers: list[Path] = []
    for legend_path in sorted(root.rglob("legend.json")):
        parent = legend_path.parent
        if parent.is_dir():
            layers.append(parent)
    return layers


def _cleanup_tiles_tree(
    tiles_root_dir: Path,
    *,
    keep_n_versions: int,
    referenced_versions: dict[str, set[str]],
    audit: AuditLogger,
    audit_run_id: str,
    now: Optional[datetime] = None,
) -> list[Path]:
    if keep_n_versions < 0:
        raise ValueError("keep_n_versions must be >= 0")

    root = tiles_root_dir.resolve()
    if not root.is_dir():
        return []

    deleted: list[Path] = []
    for layer_dir in _discover_tile_layers(root):
        _assert_no_symlink_components(layer_dir, root=root, label="traverse")
        layer_dir_resolved = _assert_resolved_within_root(
            layer_dir, root=root, label="traverse"
        )

        try:
            layer_key = layer_dir_resolved.relative_to(root).as_posix()
        except ValueError:
            raise ValueError(
                f"Layer directory escapes tiles_root: {layer_dir}"
            ) from None

        pinned = referenced_versions.get(layer_key, set())

        versions: list[tuple[datetime, Path]] = []
        for child in layer_dir.iterdir():
            if not child.is_dir():
                continue
            parsed = _parse_tile_version(child.name)
            if parsed is None:
                continue
            versions.append((parsed, child))

        versions.sort(key=lambda item: item[0])

        keep: set[str] = set(pinned)
        if keep_n_versions > 0 and versions:
            latest = (
                versions[-keep_n_versions:]
                if len(versions) > keep_n_versions
                else versions
            )
            keep.update([path.name for _, path in latest])

        for _, path in versions:
            if path.name in keep:
                continue
            _assert_no_symlink_components(path, root=root, label="delete")
            _assert_no_symlink(path, label="delete")
            resolved = _assert_resolved_within_root(path, root=root, label="delete")
            if not resolved.is_relative_to(layer_dir_resolved):
                raise ValueError(f"Refusing to delete path outside layer_dir: {path}")
            shutil.rmtree(path)
            deleted.append(resolved)
            audit.record(
                event="retention.cleanup.deleted",
                run_id=audit_run_id,
                payload={
                    "category": "tiles",
                    "layer": layer_key,
                    "version": path.name,
                    "path": str(resolved),
                },
                now=now,
            )

    return deleted


def run_retention_cleanup(
    config: RetentionConfig,
    *,
    audit: AuditLogger,
    now: Optional[datetime] = None,
) -> RetentionCleanupResult:
    started_at = now or _utc_now()
    run_id = audit.new_run_id()

    audit.record(
        event="retention.cleanup.started",
        run_id=run_id,
        payload={
            "raw": {
                "enabled": config.raw.enabled,
                "root_dir": str(config.raw.root_dir),
                "keep_n_runs": config.raw.keep_n_runs,
            },
            "cube": {
                "enabled": config.cube.enabled,
                "root_dir": str(config.cube.root_dir),
                "keep_n_runs": config.cube.keep_n_runs,
            },
            "tiles": {
                "enabled": config.tiles.enabled,
                "root_dir": str(config.tiles.root_dir),
                "keep_n_versions": config.tiles.keep_n_versions,
                "referenced_versions_path": (
                    None
                    if config.tiles.referenced_versions_path is None
                    else str(config.tiles.referenced_versions_path)
                ),
            },
        },
        now=started_at,
    )

    try:
        raw_deleted: list[Path] = []
        if config.raw.enabled:
            raw_deleted = _cleanup_run_tree(
                config.raw.root_dir,
                keep_n_runs=config.raw.keep_n_runs,
                category="raw",
                audit=audit,
                audit_run_id=run_id,
                now=now,
            )

        cube_deleted: list[Path] = []
        if config.cube.enabled:
            cube_deleted = _cleanup_run_tree(
                config.cube.root_dir,
                keep_n_runs=config.cube.keep_n_runs,
                category="cube",
                audit=audit,
                audit_run_id=run_id,
                now=now,
            )

        tiles_deleted: list[Path] = []
        if config.tiles.enabled:
            references: dict[str, set[str]] = {}
            if config.tiles.referenced_versions_path is not None:
                try:
                    references = load_tiles_references(
                        config.tiles.referenced_versions_path
                    )
                except FileNotFoundError:
                    references = {}
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "tiles_references_load_failed",
                        extra={
                            "path": str(config.tiles.referenced_versions_path),
                            "error": str(exc),
                        },
                    )
                    references = {}

            tiles_deleted = _cleanup_tiles_tree(
                config.tiles.root_dir,
                keep_n_versions=config.tiles.keep_n_versions,
                referenced_versions=references,
                audit=audit,
                audit_run_id=run_id,
                now=now,
            )

        result = RetentionCleanupResult(
            run_id=run_id,
            raw_deleted=raw_deleted,
            cube_deleted=cube_deleted,
            tiles_deleted=tiles_deleted,
        )
        audit.record(
            event="retention.cleanup.finished",
            run_id=run_id,
            payload={
                "deleted_total": result.deleted_total,
                "raw_deleted": len(result.raw_deleted),
                "cube_deleted": len(result.cube_deleted),
                "tiles_deleted": len(result.tiles_deleted),
            },
            now=now,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        audit.record(
            event="retention.cleanup.error",
            run_id=run_id,
            payload={"error": str(exc)},
            now=now,
        )
        raise
