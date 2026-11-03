"""#146: /auth/login and /auth/refresh also return `user` and `preferences`, so a cold
page load is one round trip instead of refresh -> /auth/me -> /auth/preferences."""

from datetime import datetime, timezone

from sqlalchemy import text

from tests.test_auth import _cookie_value, _insert_user_with_password

TOKEN_KEYS = {"access_token", "token_type", "expires_in"}


def _env(monkeypatch, grace: str = "30") -> None:
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")
    monkeypatch.setenv("AUTH_REFRESH_GRACE_SECONDS", grace)


def _set_prefs(db_engine, user_id: int, theme: str, accent: str) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO user_preferences (user_id, theme, accent_color, updated_at) "
                "VALUES (:u, :t, :a, :now)"
            ),
            {"u": user_id, "t": theme, "a": accent, "now": datetime.now(tz=timezone.utc)},
        )


def test_login_returns_user_and_preferences(client, db_engine, monkeypatch):
    _env(monkeypatch)
    _insert_user_with_password(db_engine, user_id=1460, username="payload_user", password="PayloadPass1!")
    _set_prefs(db_engine, 1460, "light", "#2b6ddb")

    res = client.post("/auth/login", json={"username": "payload_user", "password": "PayloadPass1!"})
    assert res.status_code == 200
    body = res.json()
    assert TOKEN_KEYS <= body.keys()  # existing fields kept
    assert body["token_type"] == "bearer"
    assert body["user"] == {
        "id": 1460,
        "username": "payload_user",
        "display_name": "Payload_User",
        "email": None,
        "is_admin": False,
    }
    assert body["preferences"] == {"theme": "light", "accent_color": "#2b6ddb"}

    # Same shapes as the dedicated endpoints.
    auth = {"Authorization": f"Bearer {body['access_token']}"}
    assert client.get("/auth/me", headers=auth).json() == body["user"]
    assert client.get("/auth/preferences", headers=auth).json() == body["preferences"]


def test_refresh_returns_user_and_preferences(client, db_engine, monkeypatch):
    _env(monkeypatch, grace="0")
    _insert_user_with_password(db_engine, user_id=1461, username="refresh_payload", password="RefreshPay1!")
    _set_prefs(db_engine, 1461, "light", "#8650d9")
    assert client.post("/auth/login", json={"username": "refresh_payload", "password": "RefreshPay1!"}).status_code == 200

    res = client.post("/auth/refresh")
    assert res.status_code == 200
    body = res.json()
    assert TOKEN_KEYS <= body.keys()
    assert body["user"]["id"] == 1461
    assert body["user"]["username"] == "refresh_payload"
    assert body["preferences"] == {"theme": "light", "accent_color": "#8650d9"}


def test_refresh_without_stored_preferences_returns_defaults(client, db_engine, monkeypatch):
    _env(monkeypatch, grace="0")
    _insert_user_with_password(db_engine, user_id=1462, username="noprefs_user", password="NoPrefsPass1!")
    assert client.post("/auth/login", json={"username": "noprefs_user", "password": "NoPrefsPass1!"}).status_code == 200

    body = client.post("/auth/refresh").json()
    # Same as what GET /auth/preferences would return (and create) for this user.
    assert body["preferences"] == {"theme": "dark", "accent_color": "#0f7a5c"}


def test_grace_window_refresh_also_returns_user_and_preferences(client, db_engine, monkeypatch):
    _env(monkeypatch, grace="30")
    _insert_user_with_password(db_engine, user_id=1463, username="grace_payload", password="GracePay1!")
    _set_prefs(db_engine, 1463, "light", "#b5842a")
    login = client.post("/auth/login", json={"username": "grace_payload", "password": "GracePay1!"})
    original_cookie = _cookie_value(login.headers.get("set-cookie", ""), "capitalos_refresh")
    assert client.post("/auth/refresh").status_code == 200

    client.cookies.clear()
    second = client.post("/auth/refresh", cookies={"capitalos_refresh": original_cookie})
    assert second.status_code == 200
    body = second.json()
    assert body["user"]["username"] == "grace_payload"
    assert body["preferences"] == {"theme": "light", "accent_color": "#b5842a"}


def test_refresh_failure_paths_unchanged(client, db_engine, monkeypatch):
    _env(monkeypatch, grace="0")
    missing = client.post("/auth/refresh")
    assert missing.status_code == 401
    assert missing.json() == {"detail": "refresh token required"}

    _insert_user_with_password(db_engine, user_id=1464, username="stale_payload", password="StalePay1!")
    login = client.post("/auth/login", json={"username": "stale_payload", "password": "StalePay1!"})
    old_cookie = _cookie_value(login.headers.get("set-cookie", ""), "capitalos_refresh")
    assert client.post("/auth/refresh").status_code == 200

    client.cookies.clear()
    reused = client.post("/auth/refresh", cookies={"capitalos_refresh": old_cookie})
    assert reused.status_code == 401
    assert reused.json() == {"detail": "invalid or expired refresh token"}
    assert "user" not in reused.json()


def test_login_failure_unchanged(client, db_engine, monkeypatch):
    _env(monkeypatch)
    _insert_user_with_password(db_engine, user_id=1465, username="badlogin_user", password="BadLogin1!")
    res = client.post("/auth/login", json={"username": "badlogin_user", "password": "wrong-password"})
    assert res.status_code == 401
    assert res.json() == {"detail": "invalid credentials"}
