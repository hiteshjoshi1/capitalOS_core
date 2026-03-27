from __future__ import annotations

import pytest

from orchestration.services import persistence


def test_get_checkpointer_requires_sqlite_dependency_when_db_path_requested(monkeypatch):
    monkeypatch.setattr(persistence, "SqliteSaver", None)

    with pytest.raises(RuntimeError, match="SQLite checkpointer unavailable"):
        persistence.get_checkpointer(".task-flow/langgraph.sqlite")
