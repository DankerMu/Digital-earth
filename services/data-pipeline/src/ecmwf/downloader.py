from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence, Union
from urllib.parse import urlparse

import httpx

from ecmwf.config import get_ecmwf_variables_config

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES: set[int] = {408, 425, 429, 500, 502, 503, 504}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


_UNSAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_filename(value: str) -> str:
    sanitized = value.strip().replace("\\", "_").replace("/", "_")
    sanitized = _UNSAFE_FILENAME_RE.sub("_", sanitized)
    sanitized = sanitized.strip(" ._")
    if sanitized in {"", ".", ".."}:
        return "download"
    return sanitized


def _safe_filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name
    if name:
        return _sanitize_filename(name)
    normalized = parsed.path.strip("/").replace("/", "_") or "download"
    return _sanitize_filename(f"{parsed.netloc}_{normalized}")


def _parse_content_range_total(value: str) -> Optional[int]:
    # e.g. "bytes 0-0/1234" or "bytes */1234"
    try:
        _, rest = value.split(" ", 1)
        _, total_str = rest.split("/", 1)
    except ValueError:
        return None
    total_str = total_str.strip()
    if total_str.isdigit():
        return int(total_str)
    return None


def _parse_content_range_start(value: str) -> Optional[int]:
    # e.g. "bytes 100-199/1234"
    try:
        _, rest = value.split(" ", 1)
        range_part, _ = rest.split("/", 1)
        start_str, _ = range_part.split("-", 1)
    except ValueError:
        return None
    start_str = start_str.strip()
    if start_str.isdigit():
        return int(start_str)
    return None


async def _remote_content_length(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: Mapping[str, str],
    timeout_s: float,
) -> Optional[int]:
    try:
        resp = await client.head(url, headers=headers, timeout=httpx.Timeout(timeout_s))
    except httpx.RequestError:
        resp = None

    if resp is not None and resp.status_code < 400:
        content_length = resp.headers.get("Content-Length")
        if content_length and content_length.isdigit():
            return int(content_length)

    # Fallback: fetch a single byte and parse Content-Range.
    try:
        resp = await client.get(
            url,
            headers={**dict(headers), "Range": "bytes=0-0"},
            timeout=httpx.Timeout(timeout_s),
        )
    except httpx.RequestError:
        return None
    if resp.status_code == 206:
        content_range = resp.headers.get("Content-Range")
        if content_range:
            return _parse_content_range_total(content_range)
    if resp.status_code < 400:
        content_length = resp.headers.get("Content-Length")
        if content_length and content_length.isdigit():
            return int(content_length)
    return None


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    backoff_base_s: float = 0.5
    backoff_factor: float = 2.0
    backoff_max_s: float = 10.0
    jitter_s: float = 0.0

    def backoff_s(self, attempt: int) -> float:
        if attempt <= 1:
            return 0.0
        delay = self.backoff_base_s * (self.backoff_factor ** (attempt - 2))
        delay = min(self.backoff_max_s, delay)
        if self.jitter_s <= 0:
            return delay
        return delay + random.random() * self.jitter_s


@dataclass(frozen=True)
class DownloadItem:
    url: str
    dest_path: Path
    expected_size: Optional[int] = None
    expected_sha256: Optional[str] = None
    headers: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class DownloadResult:
    url: str
    dest_path: str
    status: str  # success|skipped|failed
    attempts: int
    resumed: bool
    bytes_written: int
    expected_size: Optional[int]
    final_size: Optional[int]
    sha256: Optional[str]
    started_at: str
    finished_at: str
    error: Optional[str] = None


@dataclass
class RunDownloadReport:
    run_id: str
    started_at: str
    finished_at: str
    duration_s: float
    stats: Mapping[str, Any]
    variables_config: Optional[Mapping[str, Any]]
    items: list[DownloadResult]
    manifest_path: str
    log_path: Optional[str]


class DownloadRunError(RuntimeError):
    def __init__(self, message: str, *, report: RunDownloadReport) -> None:
        super().__init__(message)
        self.report = report


class JsonlDownloadLogger:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    @property
    def path(self) -> Path:
        return self._path

    async def write(self, event: Mapping[str, Any]) -> None:
        payload = json.dumps(event, ensure_ascii=False)
        async with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(payload + "\n")


def _should_retry_status(status_code: int) -> bool:
    return status_code in RETRYABLE_STATUS_CODES


def _iter_retryable_exceptions() -> tuple[type[BaseException], ...]:
    return (
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.RemoteProtocolError,
        httpx.DecodingError,
        httpx.ReadError,
        httpx.WriteError,
        httpx.PoolTimeout,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.ConnectError,
        httpx.HTTPError,
    )


async def _download_one(
    client: httpx.AsyncClient,
    item: DownloadItem,
    *,
    retry_policy: RetryPolicy,
    timeout_s: float,
    resume: bool,
    skip_existing: bool,
    compute_checksum: bool,
    verify_checksum: bool,
    verify_size: bool,
    chunk_size: int,
    log: Optional[JsonlDownloadLogger],
    run_id: str,
) -> DownloadResult:
    started_at = _utc_now_iso()

    dest_path = item.dest_path
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    headers = dict(item.headers)
    expected_size = item.expected_size
    if expected_size is None and verify_size:
        expected_size = await _remote_content_length(
            client, item.url, headers=headers, timeout_s=timeout_s
        )

    def local_size() -> int:
        try:
            return dest_path.stat().st_size
        except FileNotFoundError:
            return 0

    bytes_written_total = 0
    resumed_any = False

    if skip_existing and dest_path.exists():
        existing = local_size()
        if expected_size is not None and existing == expected_size:
            sha256 = _sha256_file(dest_path) if compute_checksum else None
            if (
                verify_checksum
                and item.expected_sha256
                and sha256 is not None
                and sha256 != item.expected_sha256
            ):
                # Treat as corrupted; re-download from scratch.
                backup = dest_path.with_suffix(dest_path.suffix + ".corrupt")
                dest_path.replace(backup)
            else:
                finished_at = _utc_now_iso()
                if log:
                    await log.write(
                        {
                            "ts": finished_at,
                            "run_id": run_id,
                            "event": "skipped",
                            "url": item.url,
                            "path": str(dest_path),
                            "size": existing,
                        }
                    )
                return DownloadResult(
                    url=item.url,
                    dest_path=str(dest_path),
                    status="skipped",
                    attempts=0,
                    resumed=False,
                    bytes_written=0,
                    expected_size=expected_size,
                    final_size=existing,
                    sha256=sha256,
                    started_at=started_at,
                    finished_at=finished_at,
                )

    last_error: Optional[str] = None
    for attempt in range(1, retry_policy.max_attempts + 1):
        current_size = local_size()
        request_headers = dict(headers)
        requested_range = False
        if resume and current_size > 0:
            request_headers["Range"] = f"bytes={current_size}-"
            requested_range = True
        did_fallback_to_full = False

        if log:
            await log.write(
                {
                    "ts": _utc_now_iso(),
                    "run_id": run_id,
                    "event": "attempt",
                    "attempt": attempt,
                    "url": item.url,
                    "path": str(dest_path),
                    "range": request_headers.get("Range"),
                }
            )

        abort_attempts = False
        try:
            while True:
                async with client.stream(
                    "GET",
                    item.url,
                    headers=request_headers,
                    timeout=httpx.Timeout(timeout_s),
                ) as resp:
                    status = resp.status_code
                    if (
                        status == 416
                        and expected_size is not None
                        and current_size == expected_size
                    ):
                        # Remote says "range not satisfiable" but we already have full file.
                        sha256 = _sha256_file(dest_path) if compute_checksum else None
                        finished_at = _utc_now_iso()
                        return DownloadResult(
                            url=item.url,
                            dest_path=str(dest_path),
                            status="skipped",
                            attempts=attempt,
                            resumed=True,
                            bytes_written=0,
                            expected_size=expected_size,
                            final_size=current_size,
                            sha256=sha256,
                            started_at=started_at,
                            finished_at=finished_at,
                        )

                    if status >= 400:
                        body_preview = (await resp.aread())[:200].decode(
                            errors="replace"
                        )
                        if (
                            _should_retry_status(status)
                            and attempt < retry_policy.max_attempts
                        ):
                            last_error = f"HTTP {status}: {body_preview}"
                            raise httpx.HTTPStatusError(
                                last_error, request=resp.request, response=resp
                            )
                        last_error = f"HTTP {status}: {body_preview}"
                        abort_attempts = True
                        break

                    mode = "wb"
                    if status == 206:
                        content_range = resp.headers.get("Content-Range")
                        start = (
                            _parse_content_range_start(content_range)
                            if content_range is not None
                            else None
                        )
                        if start is None or start != current_size:
                            if not did_fallback_to_full:
                                did_fallback_to_full = True
                                request_headers = dict(headers)
                                requested_range = False
                                current_size = 0
                                continue
                            last_error = (
                                f"Malformed Content-Range header: {content_range!r}"
                            )
                            abort_attempts = True
                            break
                        mode = "ab" if start > 0 else "wb"
                    elif status == 200 and requested_range and current_size > 0:
                        current_size = 0

                    if current_size == 0 and dest_path.exists():
                        dest_path.unlink(missing_ok=True)

                    bytes_written = 0
                    with dest_path.open(mode) as handle:
                        async for chunk in resp.aiter_bytes(chunk_size=chunk_size):
                            handle.write(chunk)
                            bytes_written += len(chunk)

                    bytes_written_total += bytes_written
                    resumed_any = resumed_any or (mode == "ab")
                break

        except _iter_retryable_exceptions() as exc:
            last_error = str(exc)
            if attempt >= retry_policy.max_attempts:
                break
            delay = retry_policy.backoff_s(attempt + 1)
            if log:
                await log.write(
                    {
                        "ts": _utc_now_iso(),
                        "run_id": run_id,
                        "event": "retry",
                        "attempt": attempt,
                        "url": item.url,
                        "path": str(dest_path),
                        "error": last_error,
                        "sleep_s": delay,
                    }
                )
            if delay > 0:
                await asyncio.sleep(delay)
            continue

        if abort_attempts:
            break

        final_size = local_size()
        if expected_size is not None and verify_size and final_size != expected_size:
            last_error = f"Size mismatch: expected={expected_size} actual={final_size}"
            if attempt < retry_policy.max_attempts:
                if final_size > expected_size:
                    backup = dest_path.with_suffix(dest_path.suffix + ".oversize")
                    dest_path.replace(backup)
                delay = retry_policy.backoff_s(attempt + 1)
                if delay > 0:
                    await asyncio.sleep(delay)
                continue
            break

        sha256 = _sha256_file(dest_path) if compute_checksum else None
        if verify_checksum and item.expected_sha256 and sha256 != item.expected_sha256:
            last_error = "Checksum mismatch"
            if attempt < retry_policy.max_attempts:
                backup = dest_path.with_suffix(dest_path.suffix + ".badsha")
                dest_path.replace(backup)
                delay = retry_policy.backoff_s(attempt + 1)
                if delay > 0:
                    await asyncio.sleep(delay)
                continue
            break

        finished_at = _utc_now_iso()
        if log:
            await log.write(
                {
                    "ts": finished_at,
                    "run_id": run_id,
                    "event": "success",
                    "url": item.url,
                    "path": str(dest_path),
                    "attempts": attempt,
                    "size": final_size,
                    "sha256": sha256,
                }
            )
        return DownloadResult(
            url=item.url,
            dest_path=str(dest_path),
            status="success",
            attempts=attempt,
            resumed=resumed_any,
            bytes_written=bytes_written_total,
            expected_size=expected_size,
            final_size=final_size,
            sha256=sha256,
            started_at=started_at,
            finished_at=finished_at,
        )

    finished_at = _utc_now_iso()
    if log:
        await log.write(
            {
                "ts": finished_at,
                "run_id": run_id,
                "event": "failed",
                "url": item.url,
                "path": str(dest_path),
                "attempts": retry_policy.max_attempts,
                "error": last_error,
            }
        )
    return DownloadResult(
        url=item.url,
        dest_path=str(dest_path),
        status="failed",
        attempts=retry_policy.max_attempts,
        resumed=resumed_any,
        bytes_written=bytes_written_total,
        expected_size=expected_size,
        final_size=local_size() if dest_path.exists() else None,
        sha256=_sha256_file(dest_path)
        if dest_path.exists() and compute_checksum
        else None,
        started_at=started_at,
        finished_at=finished_at,
        error=last_error or "download failed",
    )


def _serialize_variables_config() -> Mapping[str, Any]:
    config = get_ecmwf_variables_config()
    return {
        "version": config.version,
        "variables": {
            "sfc": list(config.variables.sfc),
            "pl": list(config.variables.pl),
        },
        "pressure_levels_hpa": list(config.pressure_levels_hpa),
        "lead_times_hours": config.lead_times_hours(),
    }


def _validate_run_id(run_id: str) -> None:
    normalized = run_id.strip()
    if normalized == "":
        raise ValueError("run_id must not be empty")

    candidate = Path(normalized)
    if candidate.is_absolute():
        raise ValueError("run_id must not be an absolute path")

    parts = [part for part in normalized.replace("\\", "/").split("/") if part != ""]
    if any(part == ".." for part in parts):
        raise ValueError("run_id must not contain '..'")


def _validate_dest_path(dest_path: Path, *, run_dir: Path) -> Path:
    resolved = dest_path.resolve()
    if not resolved.is_relative_to(run_dir):
        raise ValueError(
            f"dest_path must resolve within run directory ({run_dir}): {dest_path}"
        )
    return resolved


async def download_ecmwf_run(
    *,
    run_id: str,
    items: Union[Sequence[DownloadItem], Sequence[str]],
    output_dir: Path,
    concurrency: int = 4,
    timeout_s: float = 60.0,
    retry_policy: Optional[RetryPolicy] = None,
    resume: bool = True,
    skip_existing: bool = True,
    compute_checksum: bool = True,
    verify_checksum: bool = True,
    verify_size: bool = True,
    chunk_size: int = 1024 * 256,
    trust_env: bool = False,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    log_path: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
    alert: Optional[Callable[[DownloadResult], None]] = None,
    raise_on_error: bool = True,
) -> RunDownloadReport:
    """
    Download ECMWF raw files for a given run_id.

    - Supports retry/timeout, checksum/size verification, and Range resume.
    - Persists a JSON manifest for traceability, plus an optional JSONL event log.
    """

    retry_policy = retry_policy or RetryPolicy()
    if retry_policy.max_attempts <= 0:
        raise ValueError("retry_policy.max_attempts must be > 0")

    _validate_run_id(run_id)
    output_dir_resolved = output_dir.resolve()
    run_dir = (output_dir_resolved / run_id).resolve()
    if not run_dir.is_relative_to(output_dir_resolved):
        raise ValueError(
            f"run_id must resolve within output_dir ({output_dir_resolved}): {run_id}"
        )
    run_dir.mkdir(parents=True, exist_ok=True)

    if log_path is None:
        log_path = run_dir / "download.log.jsonl"
    log_writer = JsonlDownloadLogger(log_path) if log_path else None

    if manifest_path is None:
        manifest_path = run_dir / "manifest.json"

    normalized_items: list[DownloadItem] = []
    if items and isinstance(items[0], str):  # type: ignore[index]
        for url in items:  # type: ignore[assignment]
            filename = _safe_filename_from_url(str(url))
            dest_path = _validate_dest_path(run_dir / filename, run_dir=run_dir)
            normalized_items.append(DownloadItem(url=str(url), dest_path=dest_path))
    else:
        for item in items:  # type: ignore[assignment]
            dest_path = item.dest_path
            if not dest_path.is_absolute():
                dest_path = run_dir / dest_path
            dest_path = _validate_dest_path(dest_path, run_dir=run_dir)
            normalized_items.append(
                DownloadItem(
                    url=item.url,
                    dest_path=dest_path,
                    expected_size=item.expected_size,
                    expected_sha256=item.expected_sha256,
                    headers=item.headers,
                    metadata=item.metadata,
                )
            )

    started_at = _utc_now_iso()
    t0 = time.perf_counter()

    variables_config: Optional[Mapping[str, Any]]
    try:
        variables_config = _serialize_variables_config()
    except Exception as exc:  # pragma: no cover - best-effort metadata
        logger.warning("Failed to load ECMWF variables config: %s", exc)
        variables_config = None

    if verify_checksum and not compute_checksum:
        raise ValueError(
            "compute_checksum must be enabled when verify_checksum is True"
        )

    async with httpx.AsyncClient(
        follow_redirects=True,
        trust_env=trust_env,
        transport=transport,
    ) as client:
        semaphore = asyncio.Semaphore(concurrency)

        async def run_one(download_item: DownloadItem) -> DownloadResult:
            item_started_at = _utc_now_iso()
            async with semaphore:
                try:
                    return await _download_one(
                        client,
                        download_item,
                        retry_policy=retry_policy,
                        timeout_s=timeout_s,
                        resume=resume,
                        skip_existing=skip_existing,
                        compute_checksum=compute_checksum,
                        verify_checksum=verify_checksum,
                        verify_size=verify_size,
                        chunk_size=chunk_size,
                        log=log_writer,
                        run_id=run_id,
                    )
                except asyncio.CancelledError:
                    raise
                except httpx.HTTPError:
                    raise
                except Exception as exc:  # pragma: no cover - defensive isolation
                    item_finished_at = _utc_now_iso()
                    return DownloadResult(
                        url=download_item.url,
                        dest_path=str(download_item.dest_path),
                        status="failed",
                        attempts=0,
                        resumed=False,
                        bytes_written=0,
                        expected_size=download_item.expected_size,
                        final_size=None,
                        sha256=None,
                        started_at=item_started_at,
                        finished_at=item_finished_at,
                        error=str(exc),
                    )

        raw_results = await asyncio.gather(
            *(run_one(download_item) for download_item in normalized_items),
            return_exceptions=True,
        )

    results: list[DownloadResult] = []
    for download_item, raw in zip(normalized_items, raw_results):
        if isinstance(raw, DownloadResult):
            results.append(raw)
            continue
        finished_at = _utc_now_iso()
        results.append(
            DownloadResult(
                url=download_item.url,
                dest_path=str(download_item.dest_path),
                status="failed",
                attempts=0,
                resumed=False,
                bytes_written=0,
                expected_size=download_item.expected_size,
                final_size=None,
                sha256=None,
                started_at=finished_at,
                finished_at=finished_at,
                error=str(raw),
            )
        )

    success = sum(1 for result in results if result.status in {"success", "skipped"})
    failed = [result for result in results if result.status == "failed"]
    total_bytes = sum((result.final_size or 0) for result in results)
    bytes_written = sum(result.bytes_written for result in results)

    duration_s = time.perf_counter() - t0
    finished_at = _utc_now_iso()

    stats: dict[str, Any] = {
        "total": len(results),
        "success": success,
        "failed": len(failed),
        "bytes_written": bytes_written,
        "bytes_total": total_bytes,
        "duration_s": duration_s,
    }

    report = RunDownloadReport(
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        duration_s=duration_s,
        stats=stats,
        variables_config=variables_config,
        items=results,
        manifest_path=str(manifest_path),
        log_path=str(log_path) if log_path else None,
    )

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": report.run_id,
                "started_at": report.started_at,
                "finished_at": report.finished_at,
                "duration_s": report.duration_s,
                "stats": dict(report.stats),
                "variables_config": report.variables_config,
                "log_path": report.log_path,
                "items": [asdict(item) for item in report.items],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    if failed and alert is not None:
        for result in failed:
            alert(result)

    if failed and raise_on_error:
        raise DownloadRunError(
            f"ECMWF run download failed for run_id={run_id!r} ({len(failed)} files)",
            report=report,
        )

    return report
