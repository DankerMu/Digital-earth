from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

SUPPORTED_MANIFEST_VERSIONS: Final[set[int]] = {1}

_TS14_RE: Final[re.Pattern[str]] = re.compile(r"(?P<ts>\d{14})")
_TS10_RE: Final[re.Pattern[str]] = re.compile(r"(?P<ts>\d{10})")


def _utc_now_iso() -> str:
    value = datetime.now(timezone.utc).isoformat()
    if value.endswith("+00:00"):
        value = value[:-6] + "Z"
    return value


def _format_time_iso(dt: datetime) -> str:
    value = dt.astimezone(timezone.utc).isoformat()
    if value.endswith("+00:00"):
        value = value[:-6] + "Z"
    return value


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _extract_times_from_path(path: str) -> list[datetime]:
    candidates: list[datetime] = []
    for match in _TS14_RE.finditer(path):
        ts = match.group("ts")
        try:
            parsed = datetime.strptime(ts, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            candidates.append(parsed)
        except ValueError:
            continue
    for match in _TS10_RE.finditer(path):
        ts = match.group("ts")
        try:
            parsed = datetime.strptime(ts, "%Y%m%d%H").replace(tzinfo=timezone.utc)
            candidates.append(parsed)
        except ValueError:
            continue
    return candidates


class TimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: Optional[str] = None
    end: Optional[str] = None


class ManifestFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    size_bytes: int = Field(ge=0)
    checksum: str

    @model_validator(mode="after")
    def _validate_path(self) -> "ManifestFile":
        normalized = (self.path or "").strip().replace("\\", "/")
        if normalized == "":
            raise ValueError("manifest file path must not be empty")
        if (
            normalized.startswith("/")
            or normalized.startswith("../")
            or "/../" in normalized
        ):
            raise ValueError("manifest file path must be a safe relative path")
        self.path = normalized
        return self


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    source: str
    run_time: str
    generated_at: str
    checksum_algorithm: str = "sha256"
    time_range: TimeRange = Field(default_factory=TimeRange)
    files: list[ManifestFile] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_schema(self) -> "Manifest":
        if self.version not in SUPPORTED_MANIFEST_VERSIONS:
            raise ValueError(
                f"Unsupported manifest version={self.version}; "
                f"supported versions: {sorted(SUPPORTED_MANIFEST_VERSIONS)}"
            )

        algo = (self.checksum_algorithm or "").strip().lower()
        if algo != "sha256":
            raise ValueError("Only checksum_algorithm='sha256' is supported")
        self.checksum_algorithm = algo

        if (self.source or "").strip() == "":
            raise ValueError("manifest source must not be empty")
        if (self.run_time or "").strip() == "":
            raise ValueError("manifest run_time must not be empty")

        self.source = self.source.strip()
        self.run_time = self.run_time.strip()

        return self


class ManifestGenerator:
    def __init__(
        self, *, checksum_algorithm: str = "sha256", manifest_version: int = 1
    ) -> None:
        checksum_algorithm = (checksum_algorithm or "").strip().lower()
        if checksum_algorithm != "sha256":
            raise ValueError("Only checksum_algorithm='sha256' is supported")
        if manifest_version not in SUPPORTED_MANIFEST_VERSIONS:
            raise ValueError(
                f"Unsupported manifest_version={manifest_version}; "
                f"supported versions: {sorted(SUPPORTED_MANIFEST_VERSIONS)}"
            )
        self._checksum_algorithm = checksum_algorithm
        self._manifest_version = manifest_version

    def generate(
        self,
        run_dir: Path,
        *,
        source: str,
        run_time: str,
        manifest_path: Optional[Path] = None,
    ) -> Manifest:
        run_dir_resolved = run_dir.resolve()
        if not run_dir_resolved.is_dir():
            raise FileNotFoundError(f"run_dir not found: {run_dir}")

        if manifest_path is None:
            manifest_path = run_dir_resolved / "manifest.json"
        manifest_path = manifest_path.resolve()

        files: list[ManifestFile] = []
        inferred_times: list[datetime] = []

        for path in sorted(run_dir_resolved.rglob("*")):
            if not path.is_file():
                continue
            if path.resolve() == manifest_path:
                continue
            rel = path.resolve().relative_to(run_dir_resolved)
            rel_posix = rel.as_posix()
            stat = path.stat()
            files.append(
                ManifestFile(
                    path=rel_posix,
                    size_bytes=int(stat.st_size),
                    checksum=_sha256_file(path),
                )
            )
            inferred_times.extend(_extract_times_from_path(rel_posix))

        if inferred_times:
            start = min(inferred_times)
            end = max(inferred_times)
            time_range = TimeRange(
                start=_format_time_iso(start), end=_format_time_iso(end)
            )
        elif files:
            mtimes: list[datetime] = []
            for entry in files:
                mtime_s = (run_dir_resolved / entry.path).stat().st_mtime
                mtimes.append(datetime.fromtimestamp(mtime_s, tz=timezone.utc))
            time_range = TimeRange(
                start=_format_time_iso(min(mtimes)), end=_format_time_iso(max(mtimes))
            )
        else:
            time_range = TimeRange()

        manifest = Manifest(
            version=self._manifest_version,
            source=source,
            run_time=run_time,
            generated_at=_utc_now_iso(),
            checksum_algorithm=self._checksum_algorithm,
            time_range=time_range,
            files=files,
        )

        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest.model_dump(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return manifest

    @staticmethod
    def load(path: Path) -> Manifest:
        raw = path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid manifest JSON: {path}") from exc
        try:
            return Manifest.model_validate(data)
        except ValidationError as exc:
            raise ValueError(f"Invalid manifest schema ({path}): {exc}") from exc
