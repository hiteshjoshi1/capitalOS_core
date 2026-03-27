from __future__ import annotations

import atexit
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

try:
    from langgraph.checkpoint.sqlite import SqliteSaver
except Exception:  # pragma: no cover
    SqliteSaver = None


# Keep SQLite context managers alive for the lifetime of the process.
# Otherwise the underlying DB connection may be closed after __enter__().
_SQLITE_CONTEXTS: list[object] = []


def _cleanup_sqlite_contexts() -> None:
    while _SQLITE_CONTEXTS:
        ctx = _SQLITE_CONTEXTS.pop()
        try:
            ctx.__exit__(None, None, None)
        except Exception:
            pass


atexit.register(_cleanup_sqlite_contexts)


def get_checkpointer(db_path: str | None = None):
    """
    Local default:
    - SQLite if available
    - otherwise InMemorySaver

    Important:
    In this LangGraph version, SqliteSaver.from_conn_string(...)
    returns a context manager. We must keep that context manager alive
    for as long as the saver is in use, otherwise the DB connection closes.
    """
    if db_path:
        if SqliteSaver is None:
            raise RuntimeError(
                "SQLite checkpointer unavailable. Install the LangGraph SQLite "
                "checkpoint package so workflow state can persist to disk."
            )

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        ctx = SqliteSaver.from_conn_string(str(db_path))
        saver = ctx.__enter__()
        _SQLITE_CONTEXTS.append(ctx)
        return saver

    return InMemorySaver()
