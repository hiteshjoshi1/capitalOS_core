"""#442 (D-119): the 30-day refresh cookie is Secure when the browser came over HTTPS (the tailnet),
and not over plain http://localhost, where Safari would drop a Secure cookie."""

import pytest

from app.services.auth import refresh_cookie_name
from tests.test_auth import _cookie_value, _insert_user_with_password


@pytest.fixture
def login_env(monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.delenv("AUTH_COOKIE_SECURE", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")


def _login(client, db_engine, user_id: int, headers: dict | None = None):
    name = f"cookie_user_{user_id}"
    _insert_user_with_password(db_engine, user_id=user_id, username=name, password="CookiePass1!")
    res = client.post("/auth/login", json={"username": name, "password": "CookiePass1!"}, headers=headers or {})
    assert res.status_code == 200
    return res.headers.get("set-cookie", "")


def _secure(set_cookie: str) -> bool:
    return any(part.strip().lower() == "secure" for part in set_cookie.split(";"))


def test_plain_http_localhost_cookie_is_not_secure(client, db_engine, login_env):
    assert not _secure(_login(client, db_engine, 951))


def test_https_via_tailnet_cookie_is_secure(client, db_engine, login_env):
    assert _secure(_login(client, db_engine, 952, {"X-Forwarded-Proto": "https"}))


def test_forwarded_http_stays_not_secure(client, db_engine, login_env):
    assert not _secure(_login(client, db_engine, 953, {"X-Forwarded-Proto": "http"}))


def test_env_still_forces_secure(client, db_engine, login_env, monkeypatch):
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "1")
    assert _secure(_login(client, db_engine, 954))


def test_refresh_keeps_secure_over_https(client, db_engine, login_env):
    set_cookie = _login(client, db_engine, 955, {"X-Forwarded-Proto": "https"})
    # The test client is plain http, so it won't send a Secure cookie back by itself.
    name = refresh_cookie_name()
    token = _cookie_value(set_cookie, name)
    client.cookies.clear()
    res = client.post("/auth/refresh", headers={"X-Forwarded-Proto": "https"}, cookies={name: token})
    assert res.status_code == 200
    assert _secure(res.headers.get("set-cookie", ""))
