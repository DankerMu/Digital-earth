from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Final, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

TRACE_ID_HEADER_NAME: Final[str] = "X-Trace-Id"

_trace_id_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "trace_id", default=None
)


def generate_trace_id() -> str:
    return uuid.uuid4().hex


def get_trace_id() -> Optional[str]:
    return _trace_id_ctx.get()


def ensure_trace_id() -> str:
    return get_trace_id() or generate_trace_id()


def _coerce_trace_id(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if len(stripped) > 128:
        return None
    return stripped


class TraceIdMiddleware:
    def __init__(self, app: ASGIApp, header_name: str = TRACE_ID_HEADER_NAME) -> None:
        self.app = app
        self.header_name = header_name
        self.logger = logging.getLogger("api.request")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        incoming = _coerce_trace_id(headers.get(self.header_name))
        trace_id = incoming or generate_trace_id()

        token = _trace_id_ctx.set(trace_id)
        start = time.perf_counter()
        status_code: Optional[int] = None

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                response_headers = MutableHeaders(scope=message)
                response_headers[self.header_name] = trace_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logging.getLogger("api.error").exception(
                "request.unhandled_error",
                extra={"method": scope.get("method"), "path": scope.get("path")},
            )
            api_error = make_api_error(status_code=500)
            response = JSONResponse(
                status_code=api_error.status_code,
                content={
                    "error_code": api_error.error_code,
                    "message": api_error.message,
                    "trace_id": api_error.trace_id,
                },
            )
            await response(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            self.logger.info(
                "request.completed",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            _trace_id_ctx.reset(token)


_STANDARD_RECORD_ATTRS: Final[set[str]] = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "trace_id",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        trace_id = getattr(record, "trace_id", None) or "-"
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        if timestamp.endswith("+00:00"):
            timestamp = timestamp[:-6] + "Z"

        extra: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_ATTRS:
                continue
            extra[key] = value

        if record.exc_info:
            extra["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            extra["stack"] = self.formatStack(record.stack_info)

        payload = {
            "timestamp": timestamp,
            "level": record.levelname.lower(),
            "trace_id": trace_id,
            "message": record.getMessage(),
            "extra": extra,
        }
        return json.dumps(payload, ensure_ascii=False, default=str)


_LOGGING_CONFIGURED = False
_ORIGINAL_LOG_RECORD_FACTORY = logging.getLogRecordFactory()


def _log_record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
    record = _ORIGINAL_LOG_RECORD_FACTORY(*args, **kwargs)
    record.trace_id = get_trace_id() or "-"
    return record


def configure_logging(*, debug: bool = False, log_level: Optional[str] = None) -> None:
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    level = (log_level or ("DEBUG" if debug else "INFO")).upper()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    logging.setLogRecordFactory(_log_record_factory)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers = []
        logger.propagate = True

    _LOGGING_CONFIGURED = True


@dataclass(frozen=True)
class ApiError:
    status_code: int
    error_code: int
    message: str
    trace_id: str


def _default_message_for_status(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Error"


def _error_code_for_status(status_code: int) -> int:
    if status_code == 400:
        return 40000
    if status_code == 403:
        return 40300
    if status_code == 404:
        return 40400
    if status_code == 500:
        return 50000
    if 400 <= status_code < 500:
        return 40000
    return 50000


def make_api_error(*, status_code: int, message: Optional[str] = None) -> ApiError:
    resolved_trace_id = ensure_trace_id()
    resolved_message = message or _default_message_for_status(status_code)
    return ApiError(
        status_code=status_code,
        error_code=_error_code_for_status(status_code),
        message=resolved_message,
        trace_id=resolved_trace_id,
    )


def register_exception_handlers(app: FastAPI) -> None:
    logger = logging.getLogger("api.error")

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else None
        api_error = make_api_error(status_code=int(exc.status_code), message=message)
        return JSONResponse(
            status_code=api_error.status_code,
            content={
                "error_code": api_error.error_code,
                "message": api_error.message,
                "trace_id": api_error.trace_id,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.warning(
            "request.validation_error",
            extra={
                "path": request.url.path,
                "method": request.method,
                "errors": exc.errors(),
            },
        )
        api_error = make_api_error(status_code=400)
        return JSONResponse(
            status_code=api_error.status_code,
            content={
                "error_code": api_error.error_code,
                "message": api_error.message,
                "trace_id": api_error.trace_id,
            },
        )
