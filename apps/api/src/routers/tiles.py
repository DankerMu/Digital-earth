from __future__ import annotations

import gzip
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import RedirectResponse, Response

from config import get_settings
from data_source import DataNotFoundError, DataSourceError
from http_cache import if_none_match_matches
from local.cldas_loader import CldasLocalLoadError, load_cldas_dataset
from local_data_service import get_data_source
from tiling.cldas_tiles import CLDASTileGenerator, CldasTilingError

logger = logging.getLogger("api.error")

router = APIRouter(prefix="/tiles", tags=["tiles"])

# ============================================================================
# CLDAS Tiles Endpoint (from PR #216)
# ============================================================================

SHORT_CACHE_CONTROL_HEADER = "public, max-age=60"

_TIME_KEY_RE = re.compile(r"^\d{8}T\d{6}Z$")
_TIMESTAMP_RE = re.compile(r"^\d{10}$")


def _handle_data_source_error(exc: Exception) -> HTTPException:
    if isinstance(exc, DataNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, DataSourceError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="Internal Server Error")


def _timestamp_from_time_key(value: str) -> Optional[str]:
    normalized = (value or "").strip()
    if _TIMESTAMP_RE.fullmatch(normalized):
        return normalized

    if _TIME_KEY_RE.fullmatch(normalized):
        return normalized[:8] + normalized[9:11]

    text = normalized
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y%m%d%H")


def _find_cldas_index_item(index: Any, *, timestamp: str, variable: str) -> Any | None:
    for item in getattr(index, "items", []):
        if getattr(item, "variable", None) != variable:
            continue
        meta = getattr(item, "meta", None)
        if isinstance(meta, dict) and meta.get("timestamp") == timestamp:
            return item
    return None


@router.get("/cldas/{time_key}/{var}/{z}/{x}/{y}.png")
def get_cldas_tile(
    request: Request,
    time_key: str,
    var: str,
    z: int = Path(..., ge=0, le=22),
    x: int = Path(..., ge=0),
    y: int = Path(..., ge=0),
) -> Response:
    timestamp = _timestamp_from_time_key(time_key)
    if timestamp is None:
        raise HTTPException(status_code=400, detail="Invalid time")

    variable = (var or "").strip().upper()
    if not variable or not re.fullmatch(r"[A-Za-z0-9_]+", variable):
        raise HTTPException(status_code=400, detail="Invalid var")

    ds = get_data_source()
    try:
        index = ds.list_files(kinds={"cldas"})
    except Exception as exc:  # noqa: BLE001
        logger.error("cldas_tiles_index_error", extra={"error": str(exc)})
        raise _handle_data_source_error(exc) from exc

    item = _find_cldas_index_item(index, timestamp=timestamp, variable=variable)
    if item is None:
        raise HTTPException(status_code=404, detail="Tile not found")

    relative_path = getattr(item, "relative_path", None)
    if not isinstance(relative_path, str) or relative_path.strip() == "":
        raise HTTPException(status_code=500, detail="Internal Server Error")

    etag_payload = (
        "\n".join(
            [
                relative_path,
                str(getattr(item, "mtime_ns", "")),
                str(getattr(item, "size", "")),
                variable,
                timestamp,
                f"{z}/{x}/{y}",
            ]
        )
        .encode("utf-8")
        .strip()
    )
    etag = f'"sha256-{hashlib.sha256(etag_payload).hexdigest()}"'
    headers = {"Cache-Control": SHORT_CACHE_CONTROL_HEADER, "ETag": etag}
    if if_none_match_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)

    try:
        source_path = ds.open_path(relative_path)
    except Exception as exc:  # noqa: BLE001
        logger.error("cldas_tiles_open_error", extra={"error": str(exc)})
        raise _handle_data_source_error(exc) from exc

    try:
        dataset = load_cldas_dataset(source_path, engine="h5netcdf")
    except CldasLocalLoadError as exc:
        logger.error("cldas_tiles_load_error", extra={"error": str(exc)})
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("cldas_tiles_load_error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc

    try:
        try:
            generator = CLDASTileGenerator(dataset, variable=variable)
            image = generator.render_tile(zoom=z, x=x, y=y)
        except (CldasLocalLoadError, CldasTilingError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        buf = BytesIO()
        image.save(buf, format="PNG", optimize=True)
        content = buf.getvalue()
    finally:
        dataset.close()

    return Response(content=content, media_type="image/png", headers=headers)


# ============================================================================
# Storage Tiles Endpoint (from PR #215)
# ============================================================================

_DEFAULT_CACHE_CONTROL = "public, max-age=3600"
_SIGNED_URL_EXPIRES_SECONDS = 900
_GZIP_MIN_BYTES = 1024


def _normalize_tile_key(tile_path: str) -> str:
    raw = (tile_path or "").strip()
    if raw == "" or raw.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid tile path")
    if "\\" in raw:
        raise HTTPException(status_code=400, detail="Invalid tile path")

    parts = [part for part in raw.split("/") if part]
    if not parts:
        raise HTTPException(status_code=400, detail="Invalid tile path")
    if any(part in {".", ".."} for part in parts):
        raise HTTPException(status_code=400, detail="Invalid tile path")

    key = "/".join(parts)
    if len(key) > 2048:
        raise HTTPException(status_code=400, detail="Invalid tile path")
    return key


def _accepts_gzip(header: Optional[str]) -> bool:
    if not header:
        return False

    gzip_q: float | None = None
    star_q: float | None = None

    for part in header.split(","):
        token = part.strip()
        if not token:
            continue

        coding, *param_parts = [p.strip() for p in token.split(";")]
        coding_lower = coding.lower()

        q = 1.0
        for param in param_parts:
            key, sep, value = param.partition("=")
            if sep != "=":
                continue
            if key.strip().lower() != "q":
                continue
            try:
                q = float(value.strip())
            except ValueError:
                q = 0.0
            break

        if q < 0:
            q = 0.0
        elif q > 1:
            q = 1.0

        if coding_lower == "gzip":
            gzip_q = max(gzip_q, q) if gzip_q is not None else q
        elif coding_lower == "*":
            star_q = max(star_q, q) if star_q is not None else q

    if gzip_q is not None:
        return gzip_q > 0
    if star_q is not None:
        return star_q > 0
    return False


def _accepts_webp(header: Optional[str]) -> bool:
    if not header:
        return False
    lowered = header.lower()
    # Only accept explicit image/webp, not image/* to avoid serving missing .webp files
    return "image/webp" in lowered


def _guess_media_type(key: str) -> str:
    lowered = key.lower()
    if lowered.endswith(".pbf") or lowered.endswith(".mvt"):
        return "application/x-protobuf"
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".webp"):
        return "image/webp"
    if lowered.endswith(".jpg") or lowered.endswith(".jpeg"):
        return "image/jpeg"
    if lowered.endswith(".json"):
        return "application/json"
    return "application/octet-stream"


def _is_compressible_content_type(content_type: str) -> bool:
    lowered = (content_type or "").lower()
    if lowered.startswith("image/"):
        return False
    return lowered.startswith(("text/", "application/json", "application/x-protobuf"))


def _maybe_swap_extension(key: str, from_ext: str, to_ext: str) -> str:
    lowered = key.lower()
    from_lower = from_ext.lower()
    if not lowered.endswith(from_lower):
        return key
    return key[: -len(from_ext)] + to_ext


def _vary_header(values: set[str]) -> str | None:
    if not values:
        return None
    return ", ".join(sorted(values))


@dataclass(frozen=True)
class _TileLocation:
    url: str
    is_signed: bool = False


def _build_tile_location(key: str) -> _TileLocation:
    settings = get_settings()
    storage = settings.storage

    if storage.tiles_base_url:
        base = storage.tiles_base_url.rstrip("/")
        return _TileLocation(url=f"{base}/{key}", is_signed=False)

    endpoint_url = (storage.endpoint_url or "").strip()
    access_key = (
        storage.access_key_id.get_secret_value()
        if storage.access_key_id is not None
        else None
    )
    secret_key = (
        storage.secret_access_key.get_secret_value()
        if storage.secret_access_key is not None
        else None
    )

    if access_key and secret_key:
        try:
            import boto3  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "boto3 is required for signed tiles URLs; install with `pip install boto3`"
            ) from exc

        client = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            endpoint_url=endpoint_url or None,
            region_name=storage.region_name,
        )

        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": storage.tiles_bucket, "Key": key},
            ExpiresIn=_SIGNED_URL_EXPIRES_SECONDS,
        )
        return _TileLocation(url=url, is_signed=True)

    if endpoint_url:
        base = endpoint_url.rstrip("/")
        return _TileLocation(
            url=f"{base}/{storage.tiles_bucket}/{key}", is_signed=False
        )

    raise RuntimeError(
        "Tiles storage is not configured; set DIGITAL_EARTH_STORAGE_TILES_BASE_URL or DIGITAL_EARTH_STORAGE_ENDPOINT_URL"
    )


def _s3_error_code(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return None
    err = response.get("Error")
    if not isinstance(err, dict):
        return None
    code = err.get("Code")
    if not isinstance(code, str):
        return None
    return code


def _s3_status_code(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return None
    meta = response.get("ResponseMetadata")
    if not isinstance(meta, dict):
        return None
    code = meta.get("HTTPStatusCode")
    if not isinstance(code, int):
        return None
    return code


def _is_s3_not_found(exc: Exception) -> bool:
    return _s3_status_code(exc) == 404 or _s3_error_code(exc) in {
        "NoSuchKey",
        "NotFound",
    }


def _fetch_tile_bytes_from_s3(*, key: str) -> tuple[bytes, dict[str, Any]]:
    settings = get_settings()
    storage = settings.storage

    access_key = (
        storage.access_key_id.get_secret_value()
        if storage.access_key_id is not None
        else None
    )
    secret_key = (
        storage.secret_access_key.get_secret_value()
        if storage.secret_access_key is not None
        else None
    )

    endpoint_url = (storage.endpoint_url or "").strip() or None

    try:
        import boto3  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "boto3 is required for proxy tiles; install with `pip install boto3`"
        ) from exc

    client = boto3.client(
        "s3",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        endpoint_url=endpoint_url,
        region_name=storage.region_name,
    )

    obj = client.get_object(Bucket=storage.tiles_bucket, Key=key)
    body = obj.get("Body")
    if body is None or not hasattr(body, "read"):
        raise RuntimeError("Unexpected S3 get_object response body")

    data = body.read()
    if not isinstance(data, (bytes, bytearray)):
        raise RuntimeError("Unexpected S3 get_object body type")

    return bytes(data), obj


@router.get("/{tile_path:path}")
def get_tile(
    tile_path: str,
    request: Request,
    redirect: bool = Query(
        default=True,
        description="Return 302 redirect to object storage when possible",
    ),
) -> Response:
    key = _normalize_tile_key(tile_path)
    accept = request.headers.get("accept")
    accept_encoding = request.headers.get("accept-encoding")

    vary: set[str] = set()
    negotiated_key = key

    if _accepts_webp(accept) and key.lower().endswith(".png"):
        negotiated_key = _maybe_swap_extension(key, ".png", ".webp")
        vary.add("Accept")

    wants_gzip = _accepts_gzip(accept_encoding)

    if redirect:
        try:
            location = _build_tile_location(negotiated_key)
        except RuntimeError as exc:
            logger.error("tiles_storage_error", extra={"error": str(exc)})
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        cache_control = _DEFAULT_CACHE_CONTROL
        if location.is_signed:
            # Use private cache for signed URLs to prevent shared cache replay
            cache_control = f"private, max-age={_SIGNED_URL_EXPIRES_SECONDS - 1}"

        headers: dict[str, str] = {"Cache-Control": cache_control}
        vary_header = _vary_header(vary)
        if vary_header:
            headers["Vary"] = vary_header

        return RedirectResponse(url=location.url, status_code=302, headers=headers)

    # Proxy mode: fetch from storage and return bytes (useful for local dev/tests)
    key_to_fetch = negotiated_key

    try:
        data, obj = _fetch_tile_bytes_from_s3(key=key_to_fetch)
    except Exception as exc:  # noqa: BLE001
        if _is_s3_not_found(exc) and key_to_fetch != key:
            data, obj = _fetch_tile_bytes_from_s3(key=key)
            key_to_fetch = key
        elif _is_s3_not_found(exc):
            raise HTTPException(status_code=404, detail="Not Found") from exc
        else:
            logger.error("tiles_proxy_error", extra={"error": str(exc)})
            raise HTTPException(
                status_code=500, detail="Internal Server Error"
            ) from exc

    content_type = obj.get("ContentType")
    if not isinstance(content_type, str) or content_type.strip() == "":
        content_type = _guess_media_type(key_to_fetch)

    cache_control = obj.get("CacheControl")
    cache_control_value = (
        cache_control.strip()
        if isinstance(cache_control, str) and cache_control.strip()
        else _DEFAULT_CACHE_CONTROL
    )
    headers = {"Cache-Control": cache_control_value}

    transformed = False

    content_encoding = obj.get("ContentEncoding")
    content_encoding_value = (
        content_encoding.strip()
        if isinstance(content_encoding, str) and content_encoding.strip()
        else None
    )
    if content_encoding_value:
        if content_encoding_value.lower() == "gzip":
            vary.add("Accept-Encoding")
            if not wants_gzip:
                try:
                    data = gzip.decompress(data)
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "tiles_gzip_decompress_failed", extra={"error": str(exc)}
                    )
                    raise HTTPException(
                        status_code=500, detail="Internal Server Error"
                    ) from exc
                transformed = True
            else:
                headers["Content-Encoding"] = "gzip"
        else:
            headers["Content-Encoding"] = content_encoding_value

    if (
        wants_gzip
        and "Content-Encoding" not in headers
        and len(data) >= _GZIP_MIN_BYTES
        and _is_compressible_content_type(content_type)
    ):
        data = gzip.compress(data)
        headers["Content-Encoding"] = "gzip"
        vary.add("Accept-Encoding")
        transformed = True

    etag = obj.get("ETag")
    if not transformed and isinstance(etag, str):
        if if_none_match_matches(request.headers.get("if-none-match"), etag):
            response_headers: dict[str, str] = {
                "Cache-Control": headers["Cache-Control"],
                "ETag": etag,
            }
            vary_header = _vary_header(vary)
            if vary_header:
                response_headers["Vary"] = vary_header
            return Response(status_code=304, headers=response_headers)
        headers["ETag"] = etag

    vary_header = _vary_header(vary)
    if vary_header:
        headers["Vary"] = vary_header

    return Response(content=data, media_type=content_type, headers=headers)
