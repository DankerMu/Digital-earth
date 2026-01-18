from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import Response

from data_source import DataNotFoundError, DataSourceError
from http_cache import if_none_match_matches
from local.cldas_loader import CldasLocalLoadError, load_cldas_dataset
from local_data_service import get_data_source
from tiling.cldas_tiles import CLDASTileGenerator, CldasTilingError

logger = logging.getLogger("api.error")

router = APIRouter(prefix="/tiles", tags=["tiles"])

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
