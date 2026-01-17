from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

import httpx
import pytest


class _MockRangeServer:
    def __init__(
        self,
        *,
        content: bytes,
        fail_first_n: int = 0,
        drop_once_after_bytes: Optional[int] = None,
        omit_head_content_length: bool = False,
        ignore_range: bool = False,
        omit_get_content_range: bool = False,
        bad_get_content_range: Optional[str] = None,
        base_url: str = "https://example.invalid",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.content = content
        self.fail_first_n = fail_first_n
        self.drop_once_after_bytes = drop_once_after_bytes
        self.omit_head_content_length = omit_head_content_length
        self.ignore_range = ignore_range
        self.omit_get_content_range = omit_get_content_range
        self.bad_get_content_range = bad_get_content_range
        self._did_drop = False
        self.seen_ranges: list[Optional[str]] = []
        self.transport = httpx.MockTransport(self._handler)

    def url(self, path: str) -> str:
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{self.base_url}{path}"

    def _handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path != "/file.grib2":
            return httpx.Response(404, request=request)

        if request.method == "HEAD":
            headers = {"Accept-Ranges": "bytes"}
            if not self.omit_head_content_length:
                headers["Content-Length"] = str(len(self.content))
            return httpx.Response(200, headers=headers, request=request)

        if request.method != "GET":
            return httpx.Response(405, request=request)

        if self.fail_first_n > 0:
            self.fail_first_n -= 1
            return httpx.Response(
                503,
                headers={"Content-Type": "text/plain"},
                content=b"temporary",
                request=request,
            )

        content = self.content
        range_header = request.headers.get("Range")
        self.seen_ranges.append(range_header)

        start = 0
        end = len(content) - 1
        status = 200
        if not self.ignore_range and range_header and range_header.startswith("bytes="):
            spec = range_header[len("bytes=") :]
            if "," in spec:
                spec = spec.split(",", 1)[0]
            if "-" in spec:
                start_str, end_str = spec.split("-", 1)
                start = int(start_str or "0")
                if start >= len(content):
                    return httpx.Response(
                        416,
                        headers={
                            "Content-Range": f"bytes */{len(content)}",
                            "Accept-Ranges": "bytes",
                            "Content-Length": "0",
                        },
                        request=request,
                    )
                if end_str.strip().isdigit():
                    end = min(int(end_str), len(content) - 1)
            status = 206

        body = content[start : end + 1]
        if self.drop_once_after_bytes is not None and not self._did_drop and start == 0:
            body = body[: (self.drop_once_after_bytes or 0)]
            self._did_drop = True

        headers = {"Accept-Ranges": "bytes", "Content-Length": str(len(body))}
        if status == 206 and not self.omit_get_content_range:
            headers["Content-Range"] = self.bad_get_content_range or (
                f"bytes {start}-{end}/{len(content)}"
            )

        return httpx.Response(status, headers=headers, content=body, request=request)


def _sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def test_download_success_writes_manifest_and_log(tmp_path: Path) -> None:
    content = b"hello-ecmwf" * 1024
    expected_sha = _sha256_bytes(content)

    server = _MockRangeServer(content=content)

    from ecmwf.downloader import DownloadItem, RetryPolicy, download_ecmwf_run

    report = asyncio.run(
        download_ecmwf_run(
            run_id="20260116_00",
            items=[
                DownloadItem(
                    url=server.url("/file.grib2"),
                    dest_path=Path("raw.grib2"),
                    expected_sha256=expected_sha,
                )
            ],
            output_dir=tmp_path,
            retry_policy=RetryPolicy(max_attempts=3, backoff_base_s=0),
            transport=server.transport,
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
    server = _MockRangeServer(content=content, fail_first_n=1)

    from ecmwf.downloader import RetryPolicy, download_ecmwf_run

    report = asyncio.run(
        download_ecmwf_run(
            run_id="run-retry",
            items=[server.url("/file.grib2")],
            output_dir=tmp_path,
            retry_policy=RetryPolicy(max_attempts=3, backoff_base_s=0),
            transport=server.transport,
        )
    )

    assert report.items[0].attempts >= 2
    assert (tmp_path / "run-retry" / "file.grib2").read_bytes() == content


def test_download_resumes_after_connection_drop(tmp_path: Path) -> None:
    content = b"b" * 100_000
    cutoff = 10_000

    server = _MockRangeServer(content=content, drop_once_after_bytes=cutoff)

    from ecmwf.downloader import RetryPolicy, download_ecmwf_run

    report = asyncio.run(
        download_ecmwf_run(
            run_id="run-resume",
            items=[server.url("/file.grib2")],
            output_dir=tmp_path,
            retry_policy=RetryPolicy(max_attempts=5, backoff_base_s=0),
            transport=server.transport,
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

    server = _MockRangeServer(content=content)

    from ecmwf.downloader import DownloadItem, RetryPolicy, download_ecmwf_run

    with pytest.raises(Exception):
        asyncio.run(
            download_ecmwf_run(
                run_id="run-badsha",
                items=[
                    DownloadItem(
                        url=server.url("/file.grib2"),
                        dest_path=Path("bad.grib2"),
                        expected_sha256="0" * 64,
                    )
                ],
                output_dir=tmp_path,
                retry_policy=RetryPolicy(max_attempts=2, backoff_base_s=0),
                alert=_alert,
                transport=server.transport,
            )
        )

    assert alerts and alerts[0]["status"] == "failed"
    assert "Checksum mismatch" in (alerts[0]["error"] or "")


def test_download_handles_416_when_skip_existing_disabled(tmp_path: Path) -> None:
    content = b"d" * 2048

    server = _MockRangeServer(content=content)

    path = tmp_path / "run-416" / "file.grib2"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

    from ecmwf.downloader import RetryPolicy, download_ecmwf_run

    report = asyncio.run(
        download_ecmwf_run(
            run_id="run-416",
            items=[server.url("/file.grib2")],
            output_dir=tmp_path,
            retry_policy=RetryPolicy(max_attempts=2, backoff_base_s=0),
            skip_existing=False,
            transport=server.transport,
        )
    )

    assert report.items[0].status == "skipped"
    assert server.seen_ranges and server.seen_ranges[0] == f"bytes={len(content)}-"


def test_skip_existing_redownloads_when_checksum_mismatch(tmp_path: Path) -> None:
    content = b"e" * 4096
    bad_content = b"x" * 4096
    expected_sha = _sha256_bytes(content)

    server = _MockRangeServer(content=content)

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
                    url=server.url("/file.grib2"),
                    dest_path=Path("file.grib2"),
                    expected_sha256=expected_sha,
                )
            ],
            output_dir=tmp_path,
            retry_policy=RetryPolicy(max_attempts=2, backoff_base_s=0),
            transport=server.transport,
        )
    )

    assert report.items[0].status == "success"
    assert (tmp_path / "run-corrupt" / "file.grib2").read_bytes() == content
    assert (tmp_path / "run-corrupt" / "file.grib2.corrupt").read_bytes() == bad_content


def test_remote_content_length_falls_back_to_range_get(tmp_path: Path) -> None:
    content = b"f" * 128

    server = _MockRangeServer(content=content, omit_head_content_length=True)

    from ecmwf.downloader import RetryPolicy, download_ecmwf_run

    report = asyncio.run(
        download_ecmwf_run(
            run_id="run-head-fallback",
            items=[server.url("/file.grib2")],
            output_dir=tmp_path,
            retry_policy=RetryPolicy(max_attempts=2, backoff_base_s=0),
            transport=server.transport,
        )
    )

    assert report.items[0].status == "success"
    assert server.seen_ranges[:2] == ["bytes=0-0", None]


def test_range_ignored_restarts_from_scratch(tmp_path: Path) -> None:
    content = b"g" * 1024
    partial = b"g" * 10

    server = _MockRangeServer(content=content, ignore_range=True)

    run_dir = tmp_path / "run-ignore-range"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "file.grib2").write_bytes(partial)

    from ecmwf.downloader import RetryPolicy, download_ecmwf_run

    report = asyncio.run(
        download_ecmwf_run(
            run_id="run-ignore-range",
            items=[server.url("/file.grib2")],
            output_dir=tmp_path,
            retry_policy=RetryPolicy(max_attempts=2, backoff_base_s=0),
            skip_existing=False,
            transport=server.transport,
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


def test_download_run_rejects_run_id_path_traversal(tmp_path: Path) -> None:
    from ecmwf.downloader import download_ecmwf_run

    with pytest.raises(ValueError, match=r"run_id.*\.\."):
        asyncio.run(
            download_ecmwf_run(
                run_id="../evil",
                items=[],
                output_dir=tmp_path,
            )
        )


def test_download_run_rejects_absolute_run_id(tmp_path: Path) -> None:
    from ecmwf.downloader import download_ecmwf_run

    with pytest.raises(ValueError, match="absolute"):
        asyncio.run(
            download_ecmwf_run(
                run_id=str((tmp_path / "abs").resolve()),
                items=[],
                output_dir=tmp_path,
            )
        )


def test_download_run_rejects_dest_path_outside_run_dir(tmp_path: Path) -> None:
    from ecmwf.downloader import DownloadItem, download_ecmwf_run

    with pytest.raises(ValueError, match="dest_path"):
        asyncio.run(
            download_ecmwf_run(
                run_id="run-bad-path",
                items=[
                    DownloadItem(
                        url="https://example.invalid/file.grib2",
                        dest_path=Path("../outside.grib2"),
                    )
                ],
                output_dir=tmp_path,
            )
        )


def test_malformed_content_range_falls_back_to_full_download(tmp_path: Path) -> None:
    content = b"h" * 2048
    partial = content[:10]

    server = _MockRangeServer(content=content, omit_get_content_range=True)

    run_dir = tmp_path / "run-bad-content-range"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "file.grib2").write_bytes(partial)

    from ecmwf.downloader import RetryPolicy, download_ecmwf_run

    report = asyncio.run(
        download_ecmwf_run(
            run_id="run-bad-content-range",
            items=[server.url("/file.grib2")],
            output_dir=tmp_path,
            retry_policy=RetryPolicy(max_attempts=2, backoff_base_s=0),
            skip_existing=False,
            transport=server.transport,
        )
    )

    assert report.items[0].status == "success"
    assert (tmp_path / "run-bad-content-range" / "file.grib2").read_bytes() == content
    assert server.seen_ranges and server.seen_ranges[0] == f"bytes={len(partial)}-"
    assert any(r is None for r in server.seen_ranges[1:])
