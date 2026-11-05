"""Sign-in helpers for tests (#154): the suite runs with the login bypass off, so a
request is authenticated the way production authenticates it, with a bearer token
whose user row exists and is active."""

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.main import app
from app.services.auth import create_access_token


def ensure_user(engine: Engine, user_id: int, username: str | None = None, *, admin: bool = False) -> None:
    """Create the user row if it doesn't exist yet (a token for a missing user is a 401)."""
    with engine.begin() as conn:
        if conn.execute(text("SELECT 1 FROM users WHERE id = :id"), {"id": user_id}).first() is None:
            conn.execute(
                text("INSERT INTO users (id, username, is_active, is_admin) VALUES (:id, :username, :active, :admin)"),
                {"id": user_id, "username": username or f"test-user-{user_id}", "active": True, "admin": admin},
            )


def auth_headers(user_id: int, username: str | None = None) -> dict[str, str]:
    """A real access token for user_id, checked by the API like any other login."""
    token, _ = create_access_token(user_id=user_id, username=username or f"test-user-{user_id}")
    return {"Authorization": f"Bearer {token}"}


def signed_in_client(engine: Engine, user_id: int, *, admin: bool = False) -> TestClient:
    """A TestClient whose every request carries user_id's access token."""
    ensure_user(engine, user_id, admin=admin)
    test_client = TestClient(app)
    test_client.headers.update(auth_headers(user_id))
    return test_client
