from __future__ import annotations

import asyncio
import json
import threading
from contextlib import contextmanager
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

import pytest


class _FlakyRangeServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_cls: type[BaseHTTPRequestHandler],
        *,
        content: bytes,
        fail_first_n: int = 0,
        drop_once_after_bytes: Optional[int] = None,
        omit_head_content_length: bool = False,
        ignore_range: bool = False,
    ) -> None:
        super().__init__(server_address, handler_cls)
        self.content = content
        self.fail_first_n = fail_first_n
        self.drop_once_after_bytes = drop_once_after_bytes
        self.omit_head_content_length = omit_head_content_length
        self.ignore_range = ignore_range
        self._did_drop = False
        self.seen_ranges: list[Optional[str]] = []


class _Handler(BaseHTTPRequestHandler):
    server: _FlakyRangeServer  # type: ignore[assignment]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def do_HEAD(self) -> None:  # noqa: N802
        if self.path != "/file.grib2":
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        if not self.server.omit_head_content_length:
            self.send_header("Content-Length", str(len(self.server.content)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/file.grib2":
            self.send_response(404)
            self.end_headers()
            return

        if self.server.fail_first_n > 0:
            self.server.fail_first_n -= 1
            self.send_response(503)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"temporary")
            return

        content = self.server.content
        range_header = self.headers.get("Range")
        self.server.seen_ranges.append(range_header)

        start = 0
        end = len(content) - 1
        status = 200
        if (
            not self.server.ignore_range
            and range_header
            and range_header.startswith("bytes=")
        ):
            spec = range_header[len("bytes=") :]
            if "," in spec:
                spec = spec.split(",", 1)[0]
            if "-" in spec:
                start_str, end_str = spec.split("-", 1)
                start = int(start_str or "0")
                if start >= len(content):
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{len(content)}")
                    self.end_headers()
                    return
                if end_str.strip().isdigit():
                    end = min(int(end_str), len(content) - 1)
            status = 206

        body = content[start : end + 1]
        truncate = (
            self.server.drop_once_after_bytes is not None
            and not self.server._did_drop
            and start == 0
        )
        if truncate:
            cutoff = self.server.drop_once_after_bytes or 0
            body = body[:cutoff]

        self.send_response(status)
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(content)}")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

        if truncate:
            # Simulate a flaky connection by returning a truncated body. The client
            # relies on HEAD size + Range resume to recover.
            self.server._did_drop = True
            self.wfile.write(body)
            return

        self.wfile.write(body)


@contextmanager
def _serve_bytes(
    *,
    content: bytes,
    fail_first_n: int = 0,
    drop_once_after_bytes: Optional[int] = None,
    omit_head_content_length: bool = False,
    ignore_range: bool = False,
):
    server = _FlakyRangeServer(
        ("127.0.0.1", 0),
        _Handler,
        content=content,
        fail_first_n=fail_first_n,
        drop_once_after_bytes=drop_once_after_bytes,
        omit_head_content_length=omit_head_content_length,
        ignore_range=ignore_range,
    )

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield server, f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def test_download_success_writes_manifest_and_log(tmp_path: Path) -> None:
    content = b"hello-ecmwf" * 1024
    expected_sha = _sha256_bytes(content)

    with _serve_bytes(content=content) as (server, base_url):
        from ecmwf.downloader import DownloadItem, RetryPolicy, download_ecmwf_run

        report = asyncio.run(
            download_ecmwf_run(
                run_id="20260116_00",
                items=[
                    DownloadItem(
                        url=f"{base_url}/file.grib2",
                        dest_path=Path("raw.grib2"),
                        expected_sha256=expected_sha,
                    )
                ],
                output_dir=tmp_path,
                retry_policy=RetryPolicy(max_attempts=3, backoff_base_s=0),
            )
        )

    dest = tmp_path / "20260116_00" / "raw.grib2"
    assert dest.read_bytes() == content
    assert report.stats["success"] == 1
    assert report.stats["failed"] == 0
    assert report.items[0].sha256 == expected_sha

    manifest_path = Path(report.manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["run_id"] == "20260116_00"
    assert manifest["stats"]["success"] == 1
    assert manifest["items"][0]["status"] == "success"

    log_path = Path(report.log_path or "")
    log_lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert any(json.loads(line)["event"] == "success" for line in log_lines)
    assert server.seen_ranges == [None]


def test_download_retries_on_503_then_succeeds(tmp_path: Path) -> None:
    content = b"a" * 4096
    with _serve_bytes(content=content, fail_first_n=1) as (_, base_url):
        from ecmwf.downloader import RetryPolicy, download_ecmwf_run

        report = asyncio.run(
            download_ecmwf_run(
                run_id="run-retry",
                items=[f"{base_url}/file.grib2"],
                output_dir=tmp_path,
                retry_policy=RetryPolicy(max_attempts=3, backoff_base_s=0),
            )
        )

    assert report.items[0].attempts >= 2
    assert (tmp_path / "run-retry" / "file.grib2").read_bytes() == content


def test_download_resumes_after_connection_drop(tmp_path: Path) -> None:
    content = b"b" * 100_000
    cutoff = 10_000

    with _serve_bytes(content=content, drop_once_after_bytes=cutoff) as (
        server,
        base_url,
    ):
        from ecmwf.downloader import RetryPolicy, download_ecmwf_run

        report = asyncio.run(
            download_ecmwf_run(
                run_id="run-resume",
                items=[f"{base_url}/file.grib2"],
                output_dir=tmp_path,
                retry_policy=RetryPolicy(max_attempts=5, backoff_base_s=0),
            )
        )

    assert report.items[0].status == "success"
    assert report.items[0].resumed is True
    assert (tmp_path / "run-resume" / "file.grib2").read_bytes() == content
    assert server.seen_ranges[0] is None
    assert any(
        r is not None and r.startswith(f"bytes={cutoff}-")
        for r in server.seen_ranges[1:]
    )


def test_download_checksum_mismatch_alerts_and_raises(tmp_path: Path) -> None:
    content = b"c" * 1024
    alerts: list[dict[str, Any]] = []

    def _alert(result: Any) -> None:
        alerts.append(asdict(result))

    with _serve_bytes(content=content) as (_, base_url):
        from ecmwf.downloader import DownloadItem, RetryPolicy, download_ecmwf_run

        with pytest.raises(Exception):
            asyncio.run(
                download_ecmwf_run(
                    run_id="run-badsha",
                    items=[
                        DownloadItem(
                            url=f"{base_url}/file.grib2",
                            dest_path=Path("bad.grib2"),
                            expected_sha256="0" * 64,
                        )
                    ],
                    output_dir=tmp_path,
                    retry_policy=RetryPolicy(max_attempts=2, backoff_base_s=0),
                    alert=_alert,
                )
            )

    assert alerts and alerts[0]["status"] == "failed"
    assert "Checksum mismatch" in (alerts[0]["error"] or "")


def test_download_handles_416_when_skip_existing_disabled(tmp_path: Path) -> None:
    content = b"d" * 2048

    with _serve_bytes(content=content) as (server, base_url):
        path = tmp_path / "run-416" / "file.grib2"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

        from ecmwf.downloader import RetryPolicy, download_ecmwf_run

        report = asyncio.run(
            download_ecmwf_run(
                run_id="run-416",
                items=[f"{base_url}/file.grib2"],
                output_dir=tmp_path,
                retry_policy=RetryPolicy(max_attempts=2, backoff_base_s=0),
                skip_existing=False,
            )
        )

    assert report.items[0].status == "skipped"
    assert server.seen_ranges and server.seen_ranges[0] == f"bytes={len(content)}-"


def test_skip_existing_redownloads_when_checksum_mismatch(tmp_path: Path) -> None:
    content = b"e" * 4096
    bad_content = b"x" * 4096
    expected_sha = _sha256_bytes(content)

    with _serve_bytes(content=content) as (_, base_url):
        run_dir = tmp_path / "run-corrupt"
        run_dir.mkdir(parents=True, exist_ok=True)
        dest = run_dir / "file.grib2"
        dest.write_bytes(bad_content)

        from ecmwf.downloader import DownloadItem, RetryPolicy, download_ecmwf_run

        report = asyncio.run(
            download_ecmwf_run(
                run_id="run-corrupt",
                items=[
                    DownloadItem(
                        url=f"{base_url}/file.grib2",
                        dest_path=Path("file.grib2"),
                        expected_sha256=expected_sha,
                    )
                ],
                output_dir=tmp_path,
                retry_policy=RetryPolicy(max_attempts=2, backoff_base_s=0),
            )
        )

    assert report.items[0].status == "success"
    assert (tmp_path / "run-corrupt" / "file.grib2").read_bytes() == content
    assert (tmp_path / "run-corrupt" / "file.grib2.corrupt").read_bytes() == bad_content


def test_remote_content_length_falls_back_to_range_get(tmp_path: Path) -> None:
    content = b"f" * 128

    with _serve_bytes(content=content, omit_head_content_length=True) as (
        server,
        base_url,
    ):
        from ecmwf.downloader import RetryPolicy, download_ecmwf_run

        report = asyncio.run(
            download_ecmwf_run(
                run_id="run-head-fallback",
                items=[f"{base_url}/file.grib2"],
                output_dir=tmp_path,
                retry_policy=RetryPolicy(max_attempts=2, backoff_base_s=0),
            )
        )

    assert report.items[0].status == "success"
    assert server.seen_ranges[:2] == ["bytes=0-0", None]


def test_range_ignored_restarts_from_scratch(tmp_path: Path) -> None:
    content = b"g" * 1024
    partial = b"g" * 10

    with _serve_bytes(content=content, ignore_range=True) as (server, base_url):
        run_dir = tmp_path / "run-ignore-range"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "file.grib2").write_bytes(partial)

        from ecmwf.downloader import RetryPolicy, download_ecmwf_run

        report = asyncio.run(
            download_ecmwf_run(
                run_id="run-ignore-range",
                items=[f"{base_url}/file.grib2"],
                output_dir=tmp_path,
                retry_policy=RetryPolicy(max_attempts=2, backoff_base_s=0),
                skip_existing=False,
            )
        )

    assert report.items[0].status == "success"
    assert (tmp_path / "run-ignore-range" / "file.grib2").read_bytes() == content
    assert server.seen_ranges and server.seen_ranges[0] == f"bytes={len(partial)}-"


def test_download_run_validates_retry_policy_and_checksum_flags(tmp_path: Path) -> None:
    from ecmwf.downloader import RetryPolicy, download_ecmwf_run

    with pytest.raises(ValueError, match="max_attempts"):
        asyncio.run(
            download_ecmwf_run(
                run_id="bad-attempts",
                items=[],
                output_dir=tmp_path,
                retry_policy=RetryPolicy(max_attempts=0),
            )
        )

    with pytest.raises(ValueError, match="compute_checksum"):
        asyncio.run(
            download_ecmwf_run(
                run_id="bad-checksum",
                items=[],
                output_dir=tmp_path,
                compute_checksum=False,
                verify_checksum=True,
            )
        )
