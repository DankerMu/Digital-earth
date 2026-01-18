from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class TileStorageError(RuntimeError):
    pass


def _normalize_prefix(prefix: str) -> str:
    normalized = prefix.strip().strip("/")
    return normalized


def guess_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".json":
        return "application/json"
    return "application/octet-stream"


def build_s3_key(prefix: str, relative_path: Path) -> str:
    normalized = _normalize_prefix(prefix)
    rel = relative_path.as_posix().lstrip("/")
    if normalized:
        return f"{normalized}/{rel}"
    return rel


@dataclass(frozen=True)
class S3UploadConfig:
    bucket: str
    prefix: str
    endpoint_url: Optional[str] = None
    region_name: Optional[str] = None
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    cache_control: Optional[str] = None


def upload_directory_to_s3(
    local_dir: str | Path,
    *,
    config: S3UploadConfig,
) -> int:
    root = Path(local_dir)
    if not root.is_dir():
        raise TileStorageError(f"Tile directory not found: {root}")

    try:
        import boto3  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        raise TileStorageError(
            "boto3 is required for S3 upload; install with `pip install boto3`"
        ) from exc

    endpoint_url = config.endpoint_url or os.environ.get(
        "DIGITAL_EARTH_STORAGE_ENDPOINT_URL"
    )

    client = boto3.client(
        "s3",
        aws_access_key_id=config.access_key_id,
        aws_secret_access_key=config.secret_access_key,
        endpoint_url=endpoint_url,
        region_name=config.region_name,
    )

    uploaded = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        key = build_s3_key(config.prefix, rel)
        extra_args: dict[str, str] = {"ContentType": guess_content_type(path)}
        if config.cache_control:
            extra_args["CacheControl"] = config.cache_control
        client.upload_file(str(path), config.bucket, key, ExtraArgs=extra_args)
        uploaded += 1

    return uploaded
