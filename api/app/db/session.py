import os
import re
import time
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.orm import sessionmaker

import logging

logger = logging.getLogger("capitalos.db")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set")

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    # Allow SQLite usage in tests with FastAPI TestClient.
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

_SQL_TABLE_RE = re.compile(
    r"\b(?:from|join|update|into)\s+([A-Za-z_][A-Za-z0-9_$.]*)",
    re.IGNORECASE,
)


def db_slow_query_ms() -> int:
    raw = os.getenv("DB_SLOW_QUERY_MS", "500")
    try:
        return max(0, int(raw))
    except ValueError:
        return 500


def _safe_sql_operation(statement: str | None) -> str | None:
    if not statement:
        return None
    stripped = statement.lstrip()
    if not stripped:
        return None
    return stripped.split(None, 1)[0].lower()


def _safe_sql_table(statement: str | None) -> str | None:
    if not statement:
        return None
    match = _SQL_TABLE_RE.search(statement)
    if not match:
        return None
    table = match.group(1).strip('"')
    return table if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$.]*", table) else None


def _db_log_extra(
    event: str,
    *,
    statement: str | None = None,
    duration_ms: int | None = None,
    row_count: int | None = None,
    error: BaseException | None = None,
) -> dict[str, Any]:
    extra: dict[str, Any] = {
        "event": event,
        "operation": _safe_sql_operation(statement),
        "table": _safe_sql_table(statement),
    }
    if duration_ms is not None:
        extra["duration_ms"] = duration_ms
    if row_count is not None and row_count >= 0:
        extra["row_count"] = row_count
    if error is not None:
        extra["error_class"] = error.__class__.__name__
    return {key: value for key, value in extra.items() if value is not None}


def install_db_observability(app_engine) -> None:
    if getattr(app_engine, "_capitalos_db_observability_installed", False):
        return

    @sqlalchemy_event.listens_for(app_engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        context._capitalos_query_start = time.perf_counter()

    @sqlalchemy_event.listens_for(app_engine, "after_cursor_execute")
    def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        started = getattr(context, "_capitalos_query_start", None)
        if started is None:
            return
        duration_ms = int((time.perf_counter() - started) * 1000)
        if duration_ms < db_slow_query_ms():
            return
        logger.warning(
            "db_slow_query",
            extra=_db_log_extra(
                "db_slow_query",
                statement=statement,
                duration_ms=duration_ms,
                row_count=getattr(cursor, "rowcount", None),
            ),
        )

    @sqlalchemy_event.listens_for(app_engine, "handle_error")
    def _handle_error(exception_context):  # noqa: ANN001
        logger.error(
            "db_error",
            extra=_db_log_extra(
                "db_error",
                statement=getattr(exception_context, "statement", None),
                error=getattr(exception_context, "original_exception", None),
            ),
        )

    @sqlalchemy_event.listens_for(app_engine.pool, "checkout")
    def _pool_checkout(dbapi_connection, connection_record, connection_proxy):  # noqa: ANN001
        connection_record.info["_capitalos_checkout_start"] = time.perf_counter()

    setattr(app_engine, "_capitalos_db_observability_installed", True)


install_db_observability(engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
