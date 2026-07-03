from __future__ import annotations

import contextvars
import json
import logging
import os
import random
import re
import secrets
import string
import sys
import time
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_MAX_LENGTH = 128
_REQUEST_ID_SAFE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "capitalos_request_id",
    default=None,
)
_job_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "capitalos_job_id",
    default=None,
)
_old_record_factory = logging.getLogRecordFactory()
_configured = False

_STANDARD_RECORD_ATTRS = {
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
    "message",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}
_LOGFMT_SAFE = re.compile(r"^[A-Za-z0-9_./:@%+-]+$")
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "x-api-key",
    "access_token",
    "refresh_token",
    "token",
    "secret",
    "password",
    "flex_token",
    "flex_query_id",
    "flex_reference_code",
    "ibkr_token",
    "ibkr_query_id",
    "ibkr_ref_code",
    "query_id",
    "reference_code",
    "ref_code",
)
_BULK_CONTENT_KEY_PARTS = (
    "file_content",
    "file_contents",
    "uploaded_file",
    "raw_statement",
    "raw_rows",
    "statement_rows",
    "sql_rows",
)
_REDACTION_PATTERNS = (
    re.compile(r"(?i)\b(authorization\s*[:=]\s*)(bearer\s+)?[^,\s;\"]+"),
    re.compile(r"(?i)\b(cookie\s*[:=]\s*)[^,\n\"]+"),
    re.compile(
        r"(?i)\b(api[_-]?key|x-api-key|access[_-]?token|refresh[_-]?token|token|secret|password)"
        r"(\s*[:=]\s*)[^,\s;&\"]+"
    ),
    re.compile(
        r"(?i)\b(flex[_-]?token|flex[_-]?query[_-]?id|flex[_-]?reference[_-]?code|"
        r"ibkr[_-]?token|ibkr[_-]?query[_-]?id|ibkr[_-]?ref(?:erence)?[_-]?code|"
        r"query[_-]?id|reference[_-]?code|ref[_-]?code)(\s*[:=]\s*)[^,\s;&\"]+"
    ),
    re.compile(
        r"(?i)([?&](?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|"
        r"flex[_-]?token|flex[_-]?query[_-]?id|query[_-]?id|reference[_-]?code|ref[_-]?code)=)"
        r"[^&\s\"]+"
    ),
)


def generate_request_id() -> str:
    return secrets.token_urlsafe(18)


def is_safe_request_id(value: str | None) -> bool:
    return bool(value and _REQUEST_ID_SAFE.fullmatch(value))


def resolve_request_id(incoming: str | None) -> str:
    candidate = incoming.strip() if incoming else None
    if is_safe_request_id(candidate):
        return candidate[:_REQUEST_ID_MAX_LENGTH]
    return generate_request_id()


def get_request_id() -> str | None:
    return _request_id_var.get()


def bind_request_id(request_id: str | None) -> contextvars.Token[str | None]:
    return _request_id_var.set(request_id)


def reset_request_id(token: contextvars.Token[str | None]) -> None:
    _request_id_var.reset(token)


def generate_job_id() -> str:
    return str(uuid4())


def get_job_id() -> str | None:
    return _job_id_var.get()


def bind_job_id(job_id: str | None) -> contextvars.Token[str | None]:
    return _job_id_var.set(job_id)


def reset_job_id(token: contextvars.Token[str | None]) -> None:
    _job_id_var.reset(token)


@contextmanager
def job_context(job_id: str | None = None):
    token: contextvars.Token[str | None] | None = None
    if get_job_id() is None:
        token = bind_job_id(job_id or generate_job_id())
    try:
        yield get_job_id()
    finally:
        if token is not None:
            reset_job_id(token)


def high_frequency_log_enabled(level: int | str = logging.INFO, rate: float | None = None) -> bool:
    if isinstance(level, str):
        level_no = logging._checkLevel(level.upper())
    else:
        level_no = int(level)
    if level_no >= logging.WARNING:
        return True
    sample_rate = log_sample_rate_high_freq() if rate is None else rate
    return random.random() < max(0.0, min(sample_rate, 1.0))


def log_sample_rate_high_freq() -> float:
    raw = os.getenv("LOG_SAMPLE_RATE_HIGH_FREQ", "0.10")
    try:
        return float(raw)
    except ValueError:
        return 0.10


def normalize_logger_name(name: str) -> str:
    if name.startswith("capitalos.") or name == "capitalos":
        return name
    if name.startswith("app."):
        return f"capitalos.{name[4:]}"
    if name.startswith("api.app."):
        return f"capitalos.{name[8:]}"
    return name


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: "[REDACTED]" if _is_sensitive_key(str(key)) else redact(child)
            for key, child in value.items()
        }
    if isinstance(value, tuple):
        return tuple(redact(child) for child in value)
    if isinstance(value, list):
        return [redact(child) for child in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS + _BULK_CONTENT_KEY_PARTS)


def _redact_string(value: str) -> str:
    redacted = value
    for pattern in _REDACTION_PATTERNS:
        redacted = pattern.sub(_replace_sensitive_match, redacted)
    return redacted


def _replace_sensitive_match(match: re.Match[str]) -> str:
    groups = match.groups()
    if len(groups) == 1:
        return f"{groups[0]}[REDACTED]"
    if len(groups) >= 2:
        middle = groups[1] or ""
        return f"{groups[0]}{middle}[REDACTED]"
    return "[REDACTED]"


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.args = redact(record.args)
        if record.name == "uvicorn.access":
            record.msg = redact(record.msg)
        else:
            try:
                record.msg = _redact_string(record.getMessage())
                record.args = ()
            except Exception:
                record.msg = redact(record.msg)
        for key, value in list(record.__dict__.items()):
            if key in _STANDARD_RECORD_ATTRS:
                continue
            record.__dict__[key] = "[REDACTED]" if _is_sensitive_key(key) else redact(value)
        return True


class LogfmtFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.message = _redact_string(record.getMessage())
        fields: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "logger": normalize_logger_name(record.name),
        }
        request_id = getattr(record, "request_id", None) or get_request_id()
        if request_id:
            fields["request_id"] = request_id
        job_id = getattr(record, "job_id", None) or get_job_id()
        if job_id:
            fields["job_id"] = job_id
        for key, value in self._extra_fields(record).items():
            if key not in fields and value is not None:
                fields[key] = value
        if record.message:
            fields["msg"] = record.message
        if record.exc_info:
            fields["exc_info"] = _redact_string(self.formatException(record.exc_info))
        if record.stack_info:
            fields["stack"] = _redact_string(self.formatStack(record.stack_info))
        return " ".join(f"{key}={_format_logfmt_value(redact(value))}" for key, value in fields.items())

    def _extra_fields(self, record: logging.LogRecord) -> dict[str, Any]:
        return {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_RECORD_ATTRS and not key.startswith("_")
        }


def _format_logfmt_value(value: Any) -> str:
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, Mapping | list | tuple):
        value = json.dumps(value, separators=(",", ":"), default=str)
    else:
        value = str(value)
    if value == "":
        return '""'
    if _LOGFMT_SAFE.fullmatch(value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
    record = _old_record_factory(*args, **kwargs)
    record.name = normalize_logger_name(record.name)
    return record


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    formatter: logging.Formatter
    if os.getenv("LOG_FORMAT", "logfmt").lower() == "logfmt":
        formatter = LogfmtFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    handler.addFilter(RedactionFilter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]
    logging.setLogRecordFactory(_record_factory)
    _install_redaction_on_existing_handlers()
    _configured = True


def _install_redaction_on_existing_handlers() -> None:
    for logger in [logging.getLogger(), *logging.Logger.manager.loggerDict.values()]:
        if not isinstance(logger, logging.Logger):
            continue
        for handler in logger.handlers:
            if not any(isinstance(existing, RedactionFilter) for existing in handler.filters):
                handler.addFilter(RedactionFilter())


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.log = logging.getLogger("capitalos.request")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        request_id = resolve_request_id(headers.get(b"x-request-id", b"").decode("latin-1"))
        scope.setdefault("state", {})["request_id"] = request_id
        token = bind_request_id(request_id)
        start = time.perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            self._log_request(scope, status_code, start, request_id)
            raise
        else:
            self._log_request(scope, status_code, start, request_id)
        finally:
            reset_request_id(token)

    def _log_request(self, scope: Scope, status_code: int, start: float, request_id: str) -> None:
        duration_ms = int((time.perf_counter() - start) * 1000)
        route = scope.get("route")
        route_path = getattr(route, "path", None) or scope.get("path", "")
        user = scope.get("state", {}).get("current_user")
        extra: dict[str, Any] = {
            "event": "http_request",
            "method": scope.get("method"),
            "path": route_path,
            "status": status_code,
            "duration_ms": duration_ms,
            "request_id": request_id,
        }
        if user is not None and getattr(user, "id", None) is not None:
            extra["user_id"] = getattr(user, "id")
        self.log.info("http_request", extra=extra)
