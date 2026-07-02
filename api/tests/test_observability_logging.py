from __future__ import annotations

import io
import logging

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.logging import (
    LogfmtFormatter,
    RedactionFilter,
    RequestIdMiddleware,
    bind_request_id,
    generate_request_id,
    get_request_id,
    normalize_logger_name,
    reset_request_id,
)
from app.main import app as api_app
from app.models.rag import RagQuery
from app.rag.query_logger import log_query


def _capture_logger(logger_name: str) -> tuple[logging.Logger, io.StringIO, logging.Handler, bool, int]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(LogfmtFormatter())
    handler.addFilter(RedactionFilter())
    logger = logging.getLogger(logger_name)
    old_propagate = logger.propagate
    old_level = logger.level
    logger.handlers.append(handler)
    logger.propagate = False
    logger.setLevel(logging.INFO)
    return logger, stream, handler, old_propagate, old_level


def _restore_logger(
    logger: logging.Logger,
    handler: logging.Handler,
    old_propagate: bool,
    old_level: int,
) -> None:
    logger.handlers.remove(handler)
    logger.propagate = old_propagate
    logger.setLevel(old_level)


def test_logfmt_formats_representative_fields() -> None:
    record = logging.LogRecord(
        name="app.services.realtime",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="service event",
        args=(),
        exc_info=None,
    )
    record.event = "service_event"
    record.request_id = "req-123"
    record.duration_ms = 42

    line = LogfmtFormatter().format(record)

    assert "level=info" in line
    assert "logger=capitalos.services.realtime" in line
    assert "event=service_event" in line
    assert "request_id=req-123" in line
    assert "duration_ms=42" in line
    assert 'msg="service event"' in line


def test_logger_name_normalization_preserves_uvicorn_namespace() -> None:
    assert normalize_logger_name("app.rag.query") == "capitalos.rag.query"
    assert normalize_logger_name("api.app.routers.rag") == "capitalos.routers.rag"
    assert normalize_logger_name("capitalos.crypto") == "capitalos.crypto"
    assert normalize_logger_name("uvicorn.error") == "uvicorn.error"


def test_redaction_filter_removes_sensitive_values_before_formatting() -> None:
    logger, stream, handler, old_propagate, old_level = _capture_logger("capitalos.tests.redaction")
    try:
        logger.info(
            "Authorization: Bearer secret-token Cookie: session=secret api_key=abc123 flex_query_id=987 %s",
            "access_token=arg-secret",
            extra={
                "authorization": "Bearer other-secret",
                "raw_rows": [{"account": "123456789", "amount": 10}],
                "url": "https://example.test/path?token=url-secret&ok=1",
            },
        )
    finally:
        _restore_logger(logger, handler, old_propagate, old_level)

    line = stream.getvalue()
    assert "secret-token" not in line
    assert "other-secret" not in line
    assert "abc123" not in line
    assert "987" not in line
    assert "url-secret" not in line
    assert "arg-secret" not in line
    assert "123456789" not in line
    assert "[REDACTED]" in line


def test_redaction_filter_preserves_uvicorn_access_args() -> None:
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1234", "GET", "/ws?access_token=secret", "1.1", 403),
        exc_info=None,
    )

    assert RedactionFilter().filter(record)

    assert len(record.args) == 5
    assert "secret" not in str(record.args)
    assert "[REDACTED]" in str(record.args)


def test_request_id_middleware_generates_and_returns_id_when_header_absent() -> None:
    local_app = FastAPI()
    local_app.add_middleware(RequestIdMiddleware)

    @local_app.get("/state/{item_id}")
    def read_state(request: Request, item_id: str) -> dict[str, str | None]:
        return {
            "item_id": item_id,
            "request_id": request.state.request_id,
            "context_request_id": get_request_id(),
        }

    response = TestClient(local_app).get("/state/abc")

    assert response.status_code == 200
    response_request_id = response.headers["x-request-id"]
    assert response_request_id
    assert response.json()["request_id"] == response_request_id
    assert response.json()["context_request_id"] == response_request_id
    assert get_request_id() is None


def test_request_id_middleware_accepts_safe_incoming_id() -> None:
    local_app = FastAPI()
    local_app.add_middleware(RequestIdMiddleware)

    @local_app.get("/state")
    def read_state(request: Request) -> dict[str, str]:
        return {"request_id": request.state.request_id}

    response = TestClient(local_app).get("/state", headers={"X-Request-ID": "client.req-123"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "client.req-123"
    assert response.json()["request_id"] == "client.req-123"


def test_request_id_middleware_rejects_unsafe_incoming_id() -> None:
    local_app = FastAPI()
    local_app.add_middleware(RequestIdMiddleware)

    @local_app.get("/state")
    def read_state(request: Request) -> dict[str, str]:
        return {"request_id": request.state.request_id}

    response = TestClient(local_app).get("/state", headers={"X-Request-ID": "bad value"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] != "bad value"
    assert response.json()["request_id"] == response.headers["x-request-id"]


def test_lower_level_logs_receive_active_request_id() -> None:
    local_app = FastAPI()
    local_app.add_middleware(RequestIdMiddleware)
    logger, stream, handler, old_propagate, old_level = _capture_logger("capitalos.tests.lower")

    @local_app.get("/log")
    def write_log() -> dict[str, bool]:
        logging.getLogger("capitalos.tests.lower").info("lower layer")
        return {"ok": True}

    try:
        response = TestClient(local_app).get("/log", headers={"X-Request-ID": "lower-req-1"})
    finally:
        _restore_logger(logger, handler, old_propagate, old_level)

    assert response.status_code == 200
    assert "request_id=lower-req-1" in stream.getvalue()


def test_request_context_token_reset_prevents_leaks() -> None:
    outer = bind_request_id("outer")
    try:
        inner = bind_request_id("inner")
        assert get_request_id() == "inner"
        reset_request_id(inner)
        assert get_request_id() == "outer"
    finally:
        reset_request_id(outer)
    assert get_request_id() is None


def test_rag_query_log_attaches_active_request_id(db_engine) -> None:
    token = bind_request_id("rag-req-1")
    db = Session(db_engine)
    try:
        query_id = log_query(db, "what is capital allocation?", "concept")
        assert query_id is not None
        row = db.get(RagQuery, query_id)
        assert row is not None
        assert row.request_id == "rag-req-1"
    finally:
        db.close()
        reset_request_id(token)


def test_health_endpoint_emits_logfmt_request_log(client: TestClient) -> None:
    logger, stream, handler, old_propagate, old_level = _capture_logger("capitalos.request")
    request_id = generate_request_id()
    try:
        response = client.get("/health", headers={"X-Request-ID": request_id})
    finally:
        _restore_logger(logger, handler, old_propagate, old_level)

    assert response.status_code == 200
    assert response.headers["x-request-id"] == request_id
    line = stream.getvalue()
    assert "event=http_request" in line
    assert "method=GET" in line
    assert "path=/health" in line
    assert "status=200" in line
    assert "duration_ms=" in line
    assert f"request_id={request_id}" in line
    assert "level=info" in line
    assert "logger=capitalos.request" in line
