"""The migration chain on Postgres (#154): run by `make db-schema-check` on a database that
`make db-migrate` built from empty. (The same job has already checked that a second run is a
no-op and that the schema matches migrations/schema.sql.)"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import text

from app.routers.health import _migrations_dir
from tests.postgres_support import pg_engine  # noqa: F401  (fixture)

pytestmark = pytest.mark.postgres

_NUMBERED = re.compile(r"^\d{3}_.*\.sql$")


def _migration_files() -> list[str]:
    return sorted(p.name for p in Path(_migrations_dir()).iterdir() if _NUMBERED.match(p.name))


def test_every_migration_file_is_recorded_once_in_order(pg_engine):  # noqa: F811
    files = _migration_files()
    assert files, "no migrations mounted at /app/migrations"
    with pg_engine.connect() as conn:
        applied = [row[0] for row in conn.execute(text("SELECT filename FROM schema_migrations ORDER BY filename"))]
    assert applied == files


def test_health_reports_the_database_current(anon_client, pg_engine):  # noqa: F811
    body = anon_client.get("/health").json()
    assert body["database"] == "ok"
    assert body["migrations"]["applied"] == _migration_files()[-1]
    assert body["migrations"]["current"] is True


def test_owned_tables_require_an_owner(pg_engine):  # noqa: F811
    """Production has no NULL-owner accounts (034), which is why the tests now run with
    AUTH_ALLOW_LEGACY_NULL_OWNERSHIP=0 (#154)."""
    with pg_engine.connect() as conn:
        nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'accounts' AND column_name = 'user_id'"
            )
        ).scalar_one()
    assert nullable == "NO"


def test_no_float_columns(pg_engine):  # noqa: F811
    """The SQLite test schema uses REAL for money columns; the real schema has no float
    column at all (numeric), so these Postgres tests see the real arithmetic (#130 9.1)."""
    with pg_engine.connect() as conn:
        float_columns = conn.execute(
            text(
                "SELECT table_name || '.' || column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND data_type IN ('real', 'double precision') ORDER BY 1"
            )
        ).scalars().all()
    assert float_columns == []
