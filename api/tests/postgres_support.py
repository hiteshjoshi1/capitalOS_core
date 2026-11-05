"""Postgres for the Postgres-marked tests (#154).

`make db-schema-check` (CI job "postgres") migrates an empty Postgres 16 with the real
migrations and runs `pytest -m postgres` with TEST_POSTGRES_URL pointing at it. Each test
gets its own copy of that migrated database (CREATE DATABASE ... TEMPLATE), dropped
afterwards, so tests can write freely and never see each other's rows. Without
TEST_POSTGRES_URL (the default SQLite run) these tests are skipped.

The app is pointed at the copy by overriding `get_db`, the same hook the SQLite suite uses.
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from typing import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker

from app.db.session import get_db, with_psycopg2_driver
from app.main import app

TEST_POSTGRES_URL = os.getenv("TEST_POSTGRES_URL", "").strip()
# The real stack and the test instance: never a target for these tests.
_REFUSED_PORTS = {5433, 5434}


def postgres_url() -> str:
    if not TEST_POSTGRES_URL:
        pytest.skip("Postgres tests need TEST_POSTGRES_URL (make db-schema-check sets it)")
    url = make_url(with_psycopg2_driver(TEST_POSTGRES_URL))
    if url.port in _REFUSED_PORTS:
        pytest.fail(f"TEST_POSTGRES_URL points at port {url.port}, a real or test-instance database")
    return url.render_as_string(hide_password=False)


@contextmanager
def migrated_database_copy() -> Iterator[Engine]:
    """An engine on a fresh copy of the migrated database, dropped on exit."""
    url = make_url(postgres_url())
    template = url.database
    copy_name = f"capitalos_test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{copy_name}" TEMPLATE "{template}"'))
        engine = create_engine(url.set(database=copy_name))
        try:
            yield engine
        finally:
            engine.dispose()
            with admin.connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{copy_name}" WITH (FORCE)'))
    finally:
        admin.dispose()


@contextmanager
def app_on(engine: Engine) -> Iterator[None]:
    """Serve the app's requests from `engine` (restores the suite's SQLite override after)."""
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def _get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _get_db
    try:
        yield
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous


@pytest.fixture()
def pg_engine() -> Iterator[Engine]:
    """A fresh migrated Postgres database for this test; the app serves from it."""
    with migrated_database_copy() as engine, app_on(engine):
        yield engine
