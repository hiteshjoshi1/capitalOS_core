from datetime import datetime, timezone

from sqlalchemy import text

from app.services.auth import hash_password


def _insert_user_with_password(db_engine, *, user_id: int, username: str, password: str) -> None:
    now = datetime.now(tz=timezone.utc)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO users (id, username, display_name, is_active, is_admin, created_at, updated_at)
                VALUES (:id, :username, :display_name, 1, 0, :now, :now)
                """
            ),
            {"id": user_id, "username": username, "display_name": username.title(), "now": now},
        )
        conn.execute(
            text(
                """
                INSERT INTO user_credentials (user_id, password_hash, password_algo, password_updated_at)
                VALUES (:user_id, :password_hash, 'argon2id', :now)
                """
            ),
            {"user_id": user_id, "password_hash": hash_password(password), "now": now},
        )


def _auth_header(client, username: str, password: str) -> dict:
    login = client.post("/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200, f"Login failed: {login.text}"
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_get_preferences_creates_defaults_on_first_read(client, db_engine, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")

    _insert_user_with_password(db_engine, user_id=2001, username="pref_user1", password="PrefPass1!")
    headers = _auth_header(client, "pref_user1", "PrefPass1!")

    resp = client.get("/auth/preferences", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["theme"] == "dark"
    assert body["accent_color"] == "#0f7a5c"

    # Row should now exist in DB
    with db_engine.begin() as conn:
        row = conn.execute(
            text("SELECT theme, accent_color FROM user_preferences WHERE user_id = 2001")
        ).fetchone()
    assert row is not None
    assert row[0] == "dark"
    assert row[1] == "#0f7a5c"


def test_get_preferences_returns_existing_row(client, db_engine, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")

    _insert_user_with_password(db_engine, user_id=2002, username="pref_user2", password="PrefPass2!")
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO user_preferences (user_id, theme, accent_color, updated_at)
                VALUES (2002, 'light', '#2b6ddb', :now)
                """
            ),
            {"now": datetime.now(tz=timezone.utc)},
        )
    headers = _auth_header(client, "pref_user2", "PrefPass2!")

    resp = client.get("/auth/preferences", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["theme"] == "light"
    assert body["accent_color"] == "#2b6ddb"


def test_patch_preferences_updates_theme(client, db_engine, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")

    _insert_user_with_password(db_engine, user_id=2003, username="pref_user3", password="PrefPass3!")
    headers = _auth_header(client, "pref_user3", "PrefPass3!")

    resp = client.patch("/auth/preferences", json={"theme": "light"}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["theme"] == "light"
    assert body["accent_color"] == "#0f7a5c"  # default preserved


def test_patch_preferences_updates_accent_color(client, db_engine, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")

    _insert_user_with_password(db_engine, user_id=2004, username="pref_user4", password="PrefPass4!")
    headers = _auth_header(client, "pref_user4", "PrefPass4!")

    resp = client.patch("/auth/preferences", json={"accent_color": "#8650d9"}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["theme"] == "dark"  # default preserved
    assert body["accent_color"] == "#8650d9"


def test_patch_preferences_updates_both_fields(client, db_engine, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")

    _insert_user_with_password(db_engine, user_id=2005, username="pref_user5", password="PrefPass5!")
    headers = _auth_header(client, "pref_user5", "PrefPass5!")

    resp = client.patch("/auth/preferences", json={"theme": "light", "accent_color": "#b5842a"}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["theme"] == "light"
    assert body["accent_color"] == "#b5842a"


def test_patch_preferences_rejects_invalid_theme(client, db_engine, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")

    _insert_user_with_password(db_engine, user_id=2006, username="pref_user6", password="PrefPass6!")
    headers = _auth_header(client, "pref_user6", "PrefPass6!")

    resp = client.patch("/auth/preferences", json={"theme": "solarized"}, headers=headers)
    assert resp.status_code == 422


def test_patch_preferences_rejects_invalid_accent_color(client, db_engine, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")

    _insert_user_with_password(db_engine, user_id=2007, username="pref_user7", password="PrefPass7!")
    headers = _auth_header(client, "pref_user7", "PrefPass7!")

    resp = client.patch("/auth/preferences", json={"accent_color": "#ff0000"}, headers=headers)
    assert resp.status_code == 422


def test_patch_preferences_preserves_existing_on_partial_update(client, db_engine, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")

    _insert_user_with_password(db_engine, user_id=2008, username="pref_user8", password="PrefPass8!")
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO user_preferences (user_id, theme, accent_color, updated_at)
                VALUES (2008, 'light', '#2b6ddb', :now)
                """
            ),
            {"now": datetime.now(tz=timezone.utc)},
        )
    headers = _auth_header(client, "pref_user8", "PrefPass8!")

    # Patch only theme — accent should be preserved
    resp = client.patch("/auth/preferences", json={"theme": "dark"}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["theme"] == "dark"
    assert body["accent_color"] == "#2b6ddb"


def test_preferences_require_authentication(client, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")

    get_resp = client.get("/auth/preferences")
    assert get_resp.status_code == 401

    patch_resp = client.patch("/auth/preferences", json={"theme": "light"})
    assert patch_resp.status_code == 401


def test_get_preferences_is_idempotent(client, db_engine, monkeypatch):
    """Calling GET /auth/preferences multiple times should always return the same row."""
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")

    _insert_user_with_password(db_engine, user_id=2009, username="pref_user9", password="PrefPass9!")
    headers = _auth_header(client, "pref_user9", "PrefPass9!")

    first = client.get("/auth/preferences", headers=headers)
    second = client.get("/auth/preferences", headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()

    with db_engine.begin() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM user_preferences WHERE user_id = 2009")
        ).scalar_one()
    assert int(count) == 1
