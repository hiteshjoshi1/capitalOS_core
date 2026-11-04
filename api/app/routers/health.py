import os
import re

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter()

_MIGRATION_FILE = re.compile(r"^\d{3}_.*\.sql$")


def _migrations_dir() -> str:
    # docker-compose.yml mounts ./migrations here read-only.
    return os.getenv("MIGRATIONS_DIR", "/app/migrations")


def latest_migration_file() -> str | None:
    """Newest numbered migration on disk, or None when the folder isn't there."""
    try:
        names = [n for n in os.listdir(_migrations_dir()) if _MIGRATION_FILE.match(n)]
    except OSError:
        return None
    return max(names) if names else None


@router.get("/health")
def health(response: Response, db: Session = Depends(get_db)):
    """Liveness plus the database (#155): one `SELECT 1` and one MAX over schema_migrations.

    200 with `status: "ok"` when the database answers; 503 with `status: "error"` when it
    doesn't. `migrations.current` is true when the newest applied migration is the newest
    file, false when they differ, null when either is unknown (no migrations folder, or no
    schema_migrations table, as in the SQLite tests).
    """
    latest_file = latest_migration_file()
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        db.rollback()
        response.status_code = 503
        return {
            "status": "error",
            "database": "unreachable",
            "migrations": {"applied": None, "latest_file": latest_file, "current": None},
        }
    applied: str | None
    try:
        applied = db.execute(text("SELECT MAX(filename) FROM schema_migrations")).scalar()
    except SQLAlchemyError:
        db.rollback()
        applied = None
    current = None if applied is None or latest_file is None else applied == latest_file
    return {
        "status": "ok",
        "database": "ok",
        "migrations": {"applied": applied, "latest_file": latest_file, "current": current},
    }
