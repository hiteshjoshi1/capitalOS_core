import os
import stat

import jwt
import pytest
from sqlalchemy import text

from app.services import auth as auth_service

PUBLIC_DEFAULT_SECRET = "capitalos-dev-insecure-secret"


@pytest.fixture()
def fresh_generated_secret(monkeypatch):
    """Forget any cached generated key so each test starts from a clean state."""
    monkeypatch.setattr(auth_service, "_generated_secret", None)


def test_secret_from_environment_is_used(monkeypatch, fresh_generated_secret):
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "  from-env  ")
    assert auth_service._jwt_secret() == "from-env"


def test_unset_secret_generates_a_private_stable_key(monkeypatch, tmp_path, fresh_generated_secret):
    monkeypatch.delenv("AUTH_ACCESS_TOKEN_SECRET", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    first = auth_service._jwt_secret()
    assert first != PUBLIC_DEFAULT_SECRET
    assert len(first) >= 32
    assert auth_service._jwt_secret() == first

    key_file = tmp_path / ".auth_secret"
    assert key_file.read_text().strip() == first
    assert stat.S_IMODE(os.stat(key_file).st_mode) == 0o600

    # A new process (cache cleared) reuses the stored key, so tokens survive restarts.
    monkeypatch.setattr(auth_service, "_generated_secret", None)
    assert auth_service._jwt_secret() == first


def test_unset_secret_with_unwritable_data_dir_fails_closed(monkeypatch, tmp_path, fresh_generated_secret):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x")
    monkeypatch.delenv("AUTH_ACCESS_TOKEN_SECRET", raising=False)
    monkeypatch.setenv("DATA_DIR", str(blocker / "data"))

    with pytest.raises(RuntimeError, match="AUTH_ACCESS_TOKEN_SECRET"):
        auth_service._jwt_secret()


def test_token_signed_with_the_old_public_secret_is_rejected(monkeypatch, fresh_generated_secret):
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")
    forged = jwt.encode(
        {"sub": "1", "type": "access", "username": "demo", "exp": 4102444800},
        PUBLIC_DEFAULT_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(jwt.PyJWTError):
        auth_service.decode_access_token(forged)

    genuine, _ = auth_service.create_access_token(user_id=1, username="demo")
    assert auth_service.decode_access_token(genuine)["sub"] == "1"


def test_signup_can_be_disabled(client, db_engine, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_SIGNUP", "0")

    response = client.post(
        "/auth/signup",
        json={"username": "blocked_user", "password": "BlockedPass123!", "display_name": "Blocked"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Signup is disabled"

    with db_engine.connect() as conn:
        created = conn.execute(
            text("SELECT COUNT(*) FROM users WHERE username = :u"), {"u": "blocked_user"}
        ).scalar()
    assert created == 0


@pytest.mark.parametrize("value", ["1", "true", "", "yes"])
def test_signup_stays_open_by_default(client, monkeypatch, value):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_SIGNUP", value)

    response = client.post(
        "/auth/signup",
        json={"username": f"open_{abs(hash(value)) % 10000}", "password": "OpenPass123!", "display_name": "Open"},
    )
    assert response.status_code == 200
