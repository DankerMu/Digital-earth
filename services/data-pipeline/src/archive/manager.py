from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from archive.config import get_archive_config
from archive.manifest import ManifestGenerator, _sha256_file


def _validate_segment(value: str, *, name: str) -> str:
    normalized = (value or "").strip()
    if normalized == "":
        raise ValueError(f"{name} must not be empty")
    normalized = normalized.replace("\\", "/")
    if "/" in normalized:
        raise ValueError(f"{name} must be a path segment, not a path: {value!r}")
    if normalized in {".", ".."}:
        raise ValueError(f"{name} must not be '.' or '..'")
    return normalized


def _parse_run_time(value: str) -> Optional[datetime]:
    if len(value) == 10 and value.isdigit():
        try:
            return datetime.strptime(value, "%Y%m%d%H").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


@dataclass(frozen=True)
class ChecksumMismatch:
    path: str
    expected: str
    actual: str


@dataclass(frozen=True)
class ManifestValidationResult:
    ok: bool
    missing_files: list[str] = field(default_factory=list)
    checksum_mismatches: list[ChecksumMismatch] = field(default_factory=list)
    extra_files: list[str] = field(default_factory=list)


class ArchiveManager:
    def __init__(
        self,
        raw_root_dir: Path,
        *,
        source: str,
        run_time: str,
        manifest_filename: str = "manifest.json",
        checksum_algorithm: str = "sha256",
    ) -> None:
        raw_root_dir = raw_root_dir.expanduser().resolve()
        self._raw_root_dir = raw_root_dir
        self._source = _validate_segment(source, name="source")
        self._run_time = _validate_segment(run_time, name="run_time")

        manifest_filename = (manifest_filename or "").strip()
        if manifest_filename == "":
            raise ValueError("manifest_filename must not be empty")
        self._manifest_filename = manifest_filename

        checksum_algorithm = (checksum_algorithm or "").strip().lower()
        if checksum_algorithm != "sha256":
            raise ValueError("Only checksum_algorithm='sha256' is supported")
        self._checksum_algorithm = checksum_algorithm

    @property
    def raw_root_dir(self) -> Path:
        return self._raw_root_dir

    @property
    def source(self) -> str:
        return self._source

    @property
    def run_time(self) -> str:
        return self._run_time

    @property
    def manifest_filename(self) -> str:
        return self._manifest_filename

    @classmethod
    def from_config(
        cls,
        *,
        source: str,
        run_time: str,
        path: Optional[Union[str, Path]] = None,
    ) -> "ArchiveManager":
        config = get_archive_config(path)
        return cls(
            config.raw_root_dir,
            source=source,
            run_time=run_time,
            manifest_filename=config.manifest_filename,
            checksum_algorithm=config.checksum_algorithm,
        )

    def run_dir(self) -> Path:
        return self._raw_root_dir / self._source / self._run_time

    def data_dir(self, variable: str, level: str) -> Path:
        var_seg = _validate_segment(variable, name="variable")
        level_seg = _validate_segment(level, name="level")
        return self.run_dir() / var_seg / level_seg

    def manifest_path(self) -> Path:
        return self.run_dir() / self._manifest_filename

    def generate_manifest(self) -> Path:
        run_dir = self.run_dir()
        generator = ManifestGenerator(checksum_algorithm=self._checksum_algorithm)
        generator.generate(
            run_dir,
            source=self._source,
            run_time=self._run_time,
            manifest_path=self.manifest_path(),
        )
        return self.manifest_path()

    def validate_manifest(self, *, strict: bool = False) -> ManifestValidationResult:
        run_dir = self.run_dir().resolve()
        manifest_path = self.manifest_path().resolve()
        manifest = ManifestGenerator.load(manifest_path)

        if manifest.source != self._source or manifest.run_time != self._run_time:
            raise ValueError(
                f"Manifest source/run_time mismatch (expected {self._source}/{self._run_time}, got {manifest.source}/{manifest.run_time})"
            )

        manifest_paths = {entry.path for entry in manifest.files}
        missing: list[str] = []
        mismatches: list[ChecksumMismatch] = []

        for entry in manifest.files:
            resolved = (run_dir / entry.path).resolve()
            if not resolved.is_relative_to(run_dir):
                raise ValueError(f"Manifest path escapes run_dir: {entry.path}")
            if not resolved.is_file():
                missing.append(entry.path)
                continue
            actual = _sha256_file(resolved)
            if actual != entry.checksum:
                mismatches.append(
                    ChecksumMismatch(
                        path=entry.path, expected=entry.checksum, actual=actual
                    )
                )

        extra: list[str] = []
        if strict:
            for path in sorted(run_dir.rglob("*")):
                if not path.is_file():
                    continue
                if path.resolve() == manifest_path:
                    continue
                rel = path.resolve().relative_to(run_dir).as_posix()
                if rel not in manifest_paths:
                    extra.append(rel)

        ok = not missing and not mismatches and (not strict or not extra)
        return ManifestValidationResult(
            ok=ok,
            missing_files=missing,
            checksum_mismatches=mismatches,
            extra_files=extra,
        )

    def cleanup_old_runs(self, *, keep_n: int = 5) -> list[Path]:
        if keep_n < 0:
            raise ValueError("keep_n must be >= 0")

        source_dir = (self._raw_root_dir / self._source).resolve()
        if not source_dir.is_dir():
            return []

        runs: list[tuple[datetime, Path]] = []
        for child in source_dir.iterdir():
            if not child.is_dir():
                continue
            parsed = _parse_run_time(child.name)
            if parsed is None:
                continue
            runs.append((parsed, child))

        runs.sort(key=lambda item: item[0])
        if keep_n == 0:
            to_delete = [path for _, path in runs]
        else:
            to_delete = (
                [path for _, path in runs[:-keep_n]] if len(runs) > keep_n else []
            )

        deleted: list[Path] = []
        for path in to_delete:
            resolved = path.resolve()
            if not resolved.is_relative_to(source_dir):
                raise ValueError(
                    f"Refusing to delete path outside source_dir: {resolved}"
                )
            shutil.rmtree(resolved)
            deleted.append(resolved)
        return deleted
