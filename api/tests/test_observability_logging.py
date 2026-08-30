from __future__ import annotations

import io
import logging
import re

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logging import (
    LogfmtFormatter,
    RedactionFilter,
    RequestIdMiddleware,
    bind_request_id,
    generate_request_id,
    get_job_id,
    get_request_id,
    high_frequency_log_enabled,
    job_context,
    normalize_logger_name,
    reset_job_id,
    reset_request_id,
)
from app.main import app as api_app
from app.models.import_job import ImportJob


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
    assert normalize_logger_name("app.portfolio.scheduler") == "capitalos.portfolio.scheduler"
    assert normalize_logger_name("api.app.routers.accounts") == "capitalos.routers.accounts"
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


def test_job_context_propagates_to_logfmt() -> None:
    logger, stream, handler, old_propagate, old_level = _capture_logger("capitalos.tests.job")
    try:
        with job_context("job-test-1"):
            logger.info("job event", extra={"event": "job_event"})
            assert get_job_id() == "job-test-1"
    finally:
        _restore_logger(logger, handler, old_propagate, old_level)

    line = stream.getvalue()
    assert "event=job_event" in line
    assert "job_id=job-test-1" in line
    assert get_job_id() is None


def test_job_context_token_reset_prevents_leaks() -> None:
    outer = job_context("outer-job")
    outer.__enter__()
    try:
        token = resettable = None
        from app.core.logging import bind_job_id

        token = bind_job_id("inner-job")
        resettable = token
        assert get_job_id() == "inner-job"
        reset_job_id(resettable)
        assert get_job_id() == "outer-job"
    finally:
        outer.__exit__(None, None, None)
    assert get_job_id() is None


def test_high_frequency_sampling_never_samples_warnings(monkeypatch) -> None:
    monkeypatch.setenv("LOG_SAMPLE_RATE_HIGH_FREQ", "0")

    assert high_frequency_log_enabled(logging.INFO) is False
    assert high_frequency_log_enabled(logging.DEBUG) is False
    assert high_frequency_log_enabled(logging.WARNING) is True
    assert high_frequency_log_enabled(logging.ERROR) is True


def test_db_slow_query_log_excludes_parameters(monkeypatch, db_engine) -> None:
    from app.db.session import install_db_observability

    install_db_observability(db_engine)
    monkeypatch.setenv("DB_SLOW_QUERY_MS", "0")
    logger, stream, handler, old_propagate, old_level = _capture_logger("capitalos.db")
    try:
        with db_engine.connect() as conn:
            conn.execute(text("SELECT :secret_value AS value"), {"secret_value": "acct-123456789"})
    finally:
        _restore_logger(logger, handler, old_propagate, old_level)

    line = stream.getvalue()
    assert "event=db_slow_query" in line
    assert "operation=select" in line
    assert "acct-123456789" not in line
    assert "secret_value" not in line
    assert "SELECT" not in line


def test_ibkr_scheduler_lifecycle_logs_job_id(monkeypatch) -> None:
    from app.portfolio import scheduler as portfolio_scheduler

    class FakeDb:
        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(portfolio_scheduler, "SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(
        portfolio_scheduler,
        "_active_accounts",
        lambda db: [{"user_id": 1, "legacy_account_id": 2}],
    )
    monkeypatch.setattr(
        portfolio_scheduler,
        "run_ibkr_flex_import_from_config",
        lambda *args, **kwargs: {"import_run_id": 9, "counts": {"positions": 3}},
    )

    logger, stream, handler, old_propagate, old_level = _capture_logger("capitalos.portfolio.ibkr_flex")
    try:
        portfolio_scheduler._run_daily_imports()
    finally:
        _restore_logger(logger, handler, old_propagate, old_level)

    output = stream.getvalue()
    assert "event=ibkr_flex_refresh_started" in output
    assert "event=ibkr_flex_refresh_succeeded" in output
    assert "provider=ibkr_flex" in output
    job_ids = set(re.findall(r"job_id=([A-Za-z0-9._:-]+)", output))
    assert len(job_ids) == 1


def test_quote_scheduler_lifecycle_logs_job_id(monkeypatch) -> None:
    from app.market_data import scheduler as market_scheduler

    class FakeDb:
        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(market_scheduler, "SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(
        market_scheduler,
        "run_all_exchanges",
        lambda *args, **kwargs: {
            "exchanges": [
                {
                    "status": "success",
                    "requested_symbols": 4,
                    "upserted_rows": 3,
                    "missing_symbols": 1,
                }
            ]
        },
    )

    logger, stream, handler, old_propagate, old_level = _capture_logger("capitalos.market_data")
    try:
        market_scheduler._run_window("test_window", ["US"])
    finally:
        _restore_logger(logger, handler, old_propagate, old_level)

    output = stream.getvalue()
    assert "event=quote_refresh_started" in output
    assert "event=quote_refresh_succeeded" in output
    assert "provider=market_data" in output
    job_ids = set(re.findall(r"job_id=([A-Za-z0-9._:-]+)", output))
    assert len(job_ids) == 1


def test_upload_ingestion_failed_branch_logs_warning(db_engine, tmp_path) -> None:
    from app.ingestion.runner import run_ingestion

    db = Session(db_engine)
    job = ImportJob(
        account_id=1,
        platform="DBS",
        original_filename="missing.csv",
        stored_path=str(tmp_path / "missing.csv"),
        file_sha256="sha",
        status="UPLOADED",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    logger, stream, handler, old_propagate, old_level = _capture_logger("capitalos.ingestion")
    try:
        report = run_ingestion(db, int(job.id), str(tmp_path))
    finally:
        _restore_logger(logger, handler, old_propagate, old_level)
        db.close()

    output = stream.getvalue()
    assert report["status"] == "FAILED"
    assert "event=upload_ingest_started" in output
    assert "event=upload_ingest_failed" in output
    assert "level=warning" in output
    assert "job_db_id=" in output
    assert "job_id=" in output
    assert "missing.csv" not in output


def test_upload_ingestion_needs_mapping_branch_logs_warning(monkeypatch, db_engine, tmp_path) -> None:
    from app.ingestion import runner

    stored = tmp_path / "statement.csv"
    stored.write_text("header\nvalue\n", encoding="utf-8")
    db = Session(db_engine)
    job = ImportJob(
        account_id=1,
        platform="DBS",
        original_filename="statement.csv",
        stored_path=str(stored),
        file_sha256="sha",
        status="UPLOADED",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    monkeypatch.setattr(runner, "compute_format_signature", lambda *args, **kwargs: ("sig-safe", {"delimiter": ","}))
    monkeypatch.setattr(runner, "lookup_parser_key", lambda *args, **kwargs: None)

    logger, stream, handler, old_propagate, old_level = _capture_logger("capitalos.ingestion")
    try:
        report = runner.run_ingestion(db, int(job.id), str(tmp_path))
    finally:
        _restore_logger(logger, handler, old_propagate, old_level)
        db.close()

    output = stream.getvalue()
    assert report["status"] == "NEEDS_MAPPING"
    assert "event=upload_ingest_needs_mapping" in output
    assert "level=warning" in output
    assert "format_signature=sig-safe" in output
    assert "statement.csv" not in output


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
