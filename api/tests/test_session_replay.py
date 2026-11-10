"""#364 (#130 §8.6): a refresh-token replay ends every session; an in-window replay stays on its
own line of sessions; the live-updates socket follows the login after it connects."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.routers import realtime as realtime_router
from app.services.auth import hash_refresh_token
from tests.test_auth import _cookie_value, _insert_user_with_password


@pytest.fixture()
def auth_env(monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")
    monkeypatch.setenv("AUTH_REFRESH_GRACE_SECONDS", "30")


def _login(username: str, password: str) -> tuple[TestClient, str, dict]:
    device = TestClient(app)
    response = device.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return device, _cookie_value(response.headers.get("set-cookie", ""), "capitalos_refresh"), response.json()


def _sessions(db_engine, user_id: int) -> list[dict]:
    with db_engine.begin() as conn:
        return [
            dict(r)
            for r in conn.execute(
                text("SELECT id, revoked_at, revoke_reason FROM auth_sessions WHERE user_id = :u ORDER BY id"),
                {"u": user_id},
            ).mappings()
        ]


def _session_by_cookie(db_engine, cookie: str) -> dict:
    with db_engine.begin() as conn:
        return dict(
            conn.execute(
                text("SELECT id, revoked_at, revoke_reason FROM auth_sessions WHERE refresh_token_hash = :h"),
                {"h": hash_refresh_token(cookie)},
            ).mappings().one()
        )


def _refresh_with(cookie: str):
    return TestClient(app).post("/auth/refresh", cookies={"capitalos_refresh": cookie})


def test_replay_outside_grace_window_ends_every_session(auth_env, db_engine):
    _insert_user_with_password(db_engine, user_id=1640, username="replay_user", password="ReplayPass1!")
    _, phone_cookie, _ = _login("replay_user", "ReplayPass1!")
    _, laptop_cookie, _ = _login("replay_user", "ReplayPass1!")

    rotated = _refresh_with(phone_cookie)
    assert rotated.status_code == 200
    # The phone's old token was rotated a minute ago: well outside the 30s window.
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE auth_sessions SET revoked_at = :t WHERE user_id = 1640 AND revoke_reason = 'rotation'"),
            {"t": datetime.now(tz=timezone.utc) - timedelta(minutes=1)},
        )

    stolen = _refresh_with(phone_cookie)
    assert stolen.status_code == 401
    assert all(s["revoked_at"] is not None for s in _sessions(db_engine, 1640))
    assert {s["revoke_reason"] for s in _sessions(db_engine, 1640)} == {"rotation", "replay"}
    # The laptop, never involved, is signed out too.
    assert _refresh_with(laptop_cookie).status_code == 401


def test_replay_inside_grace_window_rotates_its_own_session_not_another_devices(auth_env, db_engine):
    _insert_user_with_password(db_engine, user_id=1641, username="two_devices", password="TwoDevices1!")
    _, phone_cookie, _ = _login("two_devices", "TwoDevices1!")
    first = _refresh_with(phone_cookie)
    assert first.status_code == 200
    phone_next = _cookie_value(first.headers.get("set-cookie", ""), "capitalos_refresh")
    # The laptop signs in after that, so its session is the user's newest one.
    _, laptop_cookie, _ = _login("two_devices", "TwoDevices1!")

    # Same old phone token again within the window (two tabs): it succeeds...
    second = _refresh_with(phone_cookie)
    assert second.status_code == 200
    # ...by rotating the phone's own successor; the laptop's session is untouched.
    assert _session_by_cookie(db_engine, laptop_cookie)["revoked_at"] is None
    assert _session_by_cookie(db_engine, phone_next)["revoke_reason"] == "rotation"
    assert _refresh_with(laptop_cookie).status_code == 200


def test_replay_inside_window_after_sign_out_refuses_without_ending_other_devices(auth_env, db_engine):
    _insert_user_with_password(db_engine, user_id=1642, username="signed_out", password="SignedOut1!")
    phone, phone_cookie, _ = _login("signed_out", "SignedOut1!")
    _, laptop_cookie, _ = _login("signed_out", "SignedOut1!")

    first = _refresh_with(phone_cookie)
    phone_next = _cookie_value(first.headers.get("set-cookie", ""), "capitalos_refresh")
    TestClient(app).post("/auth/logout", cookies={"capitalos_refresh": phone_next})

    assert _refresh_with(phone_cookie).status_code == 401
    assert _refresh_with(laptop_cookie).status_code == 200


@pytest.fixture()
def fast_socket(monkeypatch, db_engine):
    monkeypatch.setattr(realtime_router, "HEARTBEAT_INTERVAL_SECONDS", 0.2)
    # The socket opens its own sessions; point them at the test database.
    monkeypatch.setattr(realtime_router, "SessionLocal", sessionmaker(bind=db_engine))


def _close_code(ws) -> int:
    with pytest.raises(WebSocketDisconnect) as closed:
        for _ in range(50):
            message = ws.receive_json()
            assert message.get("type") in {"heartbeat", "subscribed"}, message
    return closed.value.code


def test_socket_closes_when_the_sessions_end(auth_env, fast_socket, db_engine):
    _insert_user_with_password(db_engine, user_id=1643, username="socket_user", password="SocketPass1!")
    _, _, body = _login("socket_user", "SocketPass1!")

    with TestClient(app).websocket_connect(f"/realtime/ws?access_token={body['access_token']}") as ws:
        assert ws.receive_json()["type"] == "heartbeat"  # still signed in: stays open
        with db_engine.begin() as conn:
            conn.execute(
                text("UPDATE auth_sessions SET revoked_at = :t, revoke_reason = 'replay' WHERE user_id = 1643"),
                {"t": datetime.now(tz=timezone.utc)},
            )
        assert _close_code(ws) == 4401


def test_socket_closes_when_the_access_token_expires(auth_env, fast_socket, db_engine, monkeypatch):
    _insert_user_with_password(db_engine, user_id=1644, username="expiring", password="Expiring1!")
    _, _, body = _login("expiring", "Expiring1!")
    # Pretend the token's expiry is now.
    monkeypatch.setattr(realtime_router, "_token_expiry", lambda _token: datetime.now(tz=timezone.utc).timestamp() + 0.3)

    with TestClient(app).websocket_connect(f"/realtime/ws?access_token={body['access_token']}") as ws:
        assert _close_code(ws) == 4401
