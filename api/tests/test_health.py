from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db.session import get_db
from app.main import app
from app.routers.health import latest_migration_file


@pytest.fixture()
def migrations_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in ("001_init.sql", "002_more.sql", "seed_dummy.sql", "README.md"):
        (tmp_path / name).write_text("-- synthetic\n")
    monkeypatch.setenv("MIGRATIONS_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture()
def schema_migrations(db_engine) -> Iterator[None]:
    with db_engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE schema_migrations (filename TEXT PRIMARY KEY, applied_at TEXT)")
        conn.exec_driver_sql("INSERT INTO schema_migrations (filename) VALUES ('001_init.sql'), ('002_more.sql')")
    yield
    with db_engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE schema_migrations")


def test_health_ok(client: TestClient, migrations_dir: Path):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    # The original field is kept as it was (#155 only adds fields).
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    # No schema_migrations table in the SQLite tests: applied unknown, so current unknown.
    assert body["migrations"] == {"applied": None, "latest_file": "002_more.sql", "current": None}


def test_health_migrations_current(client: TestClient, migrations_dir: Path, schema_migrations):
    body = client.get("/health").json()
    assert body["migrations"] == {"applied": "002_more.sql", "latest_file": "002_more.sql", "current": True}


def test_health_migrations_pending(client: TestClient, migrations_dir: Path, schema_migrations):
    (migrations_dir / "003_new.sql").write_text("-- synthetic\n")
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["migrations"] == {"applied": "002_more.sql", "latest_file": "003_new.sql", "current": False}


class _DownSession:
    def execute(self, *_args, **_kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    def rollback(self) -> None:
        pass


def test_health_database_down_is_503(client: TestClient, migrations_dir: Path):
    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = lambda: _DownSession()
    try:
        resp = client.get("/health")
    finally:
        app.dependency_overrides[get_db] = previous
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "error"
    assert body["database"] == "unreachable"
    # Callers that grep for "ok" (scripts/status.sh) must not see one.
    assert '"ok"' not in resp.text


def test_latest_migration_file_without_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MIGRATIONS_DIR", str(tmp_path / "absent"))
    assert latest_migration_file() is None
