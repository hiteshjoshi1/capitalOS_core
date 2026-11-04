"""Login posture (#152): demo login off, throttle, dummy hash, admin-only shared writes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from starlette.requests import Request

from app.main import app
from app.routers import auth as auth_router
from app.services import login_throttle as throttle_module
from app.services.auth import hash_password
from app.services.login_throttle import LoginThrottle, client_ip, login_throttle

PASSWORD = "Correct-Horse-1"


def _insert_user(db_engine, *, user_id: int, username: str, admin: bool = False, active: bool = True) -> None:
    now = datetime.now(tz=timezone.utc)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, display_name, is_active, is_admin, created_at, updated_at) "
                "VALUES (:id, :u, :u, :active, :admin, :now, :now)"
            ),
            {"id": user_id, "u": username, "active": 1 if active else 0, "admin": 1 if admin else 0, "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO user_credentials (user_id, password_hash, password_algo, password_updated_at) "
                "VALUES (:id, :h, 'argon2id', :now)"
            ),
            {"id": user_id, "h": hash_password(PASSWORD), "now": now},
        )


def _login(client, username: str, password: str = PASSWORD, headers: dict | None = None):
    return client.post("/auth/login", json={"username": username, "password": password}, headers=headers or {})


@pytest.fixture()
def real_auth(monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(login_throttle, "_clock", fake)
    return fake


# ---- Dummy hash: unknown and inactive users cost a password check too ----


def test_unknown_and_inactive_users_still_check_a_password(client, db_engine, real_auth, monkeypatch):
    _insert_user(db_engine, user_id=701, username="sleeping", active=False)
    checked: list[str] = []
    real_verify = auth_router.verify_password

    def counting_verify(password: str, password_hash: str) -> bool:
        checked.append(password_hash)
        return real_verify(password, password_hash)

    monkeypatch.setattr(auth_router, "verify_password", counting_verify)

    for username, password in (("nobody_here", PASSWORD), ("sleeping", PASSWORD)):
        response = _login(client, username, password)
        assert response.status_code == 401
        assert response.json()["detail"] == "invalid credentials"
    # Both checked against the one dummy hash (a real argon2/pbkdf2 hash), never the stored one.
    assert len(checked) == 2
    assert checked[0] == checked[1] == auth_router._dummy_hash()
    assert checked[0].startswith(("$argon2", "pbkdf2_sha256$"))


# ---- Throttle ----


def test_username_is_locked_out_after_repeated_failures_then_backs_off(client, db_engine, real_auth, clock, monkeypatch):
    monkeypatch.setenv("AUTH_LOGIN_MAX_FAILURES_PER_USER", "3")
    _insert_user(db_engine, user_id=702, username="target")

    for _ in range(3):
        assert _login(client, "target", "wrong-password").status_code == 401

    # Locked: even the right password is refused, with Retry-After, before any check.
    locked = _login(client, "TARGET", PASSWORD)
    assert locked.status_code == 429
    assert locked.headers["retry-after"] == "30"

    clock.now += 31
    # One more failure doubles the wait.
    assert _login(client, "target", "wrong-password").status_code == 401
    assert _login(client, "target", PASSWORD).headers.get("retry-after") == "60"

    clock.now += 61
    assert _login(client, "target", PASSWORD).status_code == 200
    # Success clears the username's counter.
    assert _login(client, "target", "wrong-password").status_code == 401
    assert _login(client, "target", PASSWORD).status_code == 200


def test_failures_expire_after_the_window(client, db_engine, real_auth, clock, monkeypatch):
    monkeypatch.setenv("AUTH_LOGIN_MAX_FAILURES_PER_USER", "2")
    monkeypatch.setenv("AUTH_LOGIN_WINDOW_SECONDS", "60")
    _insert_user(db_engine, user_id=703, username="patient")
    assert _login(client, "patient", "nope-nope-1").status_code == 401
    clock.now += 61
    assert _login(client, "patient", "nope-nope-2").status_code == 401
    # The first failure fell out of the window: one counted, not locked.
    assert _login(client, "patient", PASSWORD).status_code == 200


def test_lockout_is_capped(clock, monkeypatch):
    monkeypatch.setenv("AUTH_LOGIN_MAX_FAILURES_PER_USER", "1")
    monkeypatch.setenv("AUTH_LOGIN_LOCKOUT_MAX_SECONDS", "120")
    throttle = LoginThrottle(clock=clock)
    for _ in range(20):
        throttle.record_failure(username="u", ip="203.0.113.9")
    assert throttle.retry_after(username="u", ip="198.51.100.1") == 120


def test_ip_is_locked_out_across_usernames(client, db_engine, real_auth, clock, monkeypatch):
    monkeypatch.setenv("AUTH_LOGIN_MAX_FAILURES_PER_IP", "4")
    _insert_user(db_engine, user_id=704, username="innocent")
    for i in range(4):
        assert _login(client, f"spray_{i}", "wrong-password").status_code == 401
    # Same client (TestClient's peer), a username it never tried: refused.
    assert _login(client, "innocent", PASSWORD).status_code == 429


def test_forwarded_for_is_honoured_only_from_a_trusted_proxy(db_engine, real_auth, clock, monkeypatch):
    monkeypatch.setenv("AUTH_LOGIN_MAX_FAILURES_PER_IP", "2")
    _insert_user(db_engine, user_id=705, username="via_proxy")
    # The Vite proxy reaches the API from a local address and appends the browser's address.
    proxy = TestClient(app, client=("192.168.65.1", 50000))
    attacker = {"X-Forwarded-For": "203.0.113.50"}
    for _ in range(2):
        assert _login(proxy, "nobody", "wrong-password", headers=attacker).status_code == 401
    assert _login(proxy, "via_proxy", PASSWORD, headers=attacker).status_code == 429
    # Another browser behind the same proxy is not affected.
    assert _login(proxy, "via_proxy", PASSWORD, headers={"X-Forwarded-For": "203.0.113.51"}).status_code == 200

    # An untrusted peer can't dodge its own counter by inventing X-Forwarded-For.
    direct = TestClient(app, client=("203.0.113.77", 50000))
    for i in range(2):
        assert _login(direct, "nobody", "wrong-password", headers={"X-Forwarded-For": f"10.9.9.{i}"}).status_code == 401
    assert _login(direct, "via_proxy", PASSWORD, headers={"X-Forwarded-For": "10.9.9.200"}).status_code == 429


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


def test_client_ip_resolution(monkeypatch):
    monkeypatch.delenv("AUTH_TRUSTED_PROXIES", raising=False)
    # Trusted peer: the right-most entry (the one the proxy appended), not a client-sent one.
    assert client_ip(_request("127.0.0.1", "6.6.6.6, 100.101.102.103")) == "100.101.102.103"
    assert client_ip(_request("::ffff:172.17.0.1", "198.51.100.4")) == "198.51.100.4"
    assert client_ip(_request("127.0.0.1")) == "127.0.0.1"
    assert client_ip(_request("127.0.0.1", "not-an-ip")) == "127.0.0.1"
    # Untrusted peer: the header is ignored.
    assert client_ip(_request("198.51.100.8", "127.0.0.1")) == "198.51.100.8"
    # Trust can be narrowed or turned off.
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "")
    assert client_ip(_request("127.0.0.1", "198.51.100.4")) == "127.0.0.1"
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "10.0.0.0/8")
    assert client_ip(_request("10.1.2.3", "198.51.100.4")) == "198.51.100.4"
    assert client_ip(_request("127.0.0.1", "198.51.100.4")) == "127.0.0.1"


def test_tracked_keys_are_bounded(clock, monkeypatch):
    monkeypatch.setattr(throttle_module, "_MAX_TRACKED_KEYS", 10)
    throttle = LoginThrottle(clock=clock)
    for i in range(50):
        clock.now += 1
        throttle.record_failure(username=f"user{i}", ip=f"198.51.100.{i}")
    assert len(throttle._entries) <= 10


# ---- Admin-only shared writes ----


def _token(client, username: str) -> dict[str, str]:
    response = _login(client, username)
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


SHARED_WRITES = [
    ("/currencies", {"code": "XTS", "name": "Test currency"}),
    ("/platforms", {"code": "TESTBANK", "name": "Test Bank", "platform_type": "BANK", "country": "SG"}),
    ("/crypto/allowlist", {"chain": "ethereum", "contract_address": "0x" + "1" * 40}),
    ("/market-data/refresh-now", None),
]


@pytest.mark.parametrize("path,body", SHARED_WRITES)
def test_shared_writes_are_admin_only(client, db_engine, real_auth, monkeypatch, path, body):
    _insert_user(db_engine, user_id=706, username="plain_user")
    called: list[str] = []
    monkeypatch.setattr("app.routers.crypto.price_by_contract", lambda *a, **k: called.append("price") or {})
    monkeypatch.setattr("app.routers.market_data.run_all_exchanges", lambda db: called.append("run") or {})

    response = client.post(path, json=body, headers=_token(client, "plain_user"))
    assert response.status_code == 403
    assert "Admin only" in response.json()["detail"]
    assert called == []


def test_admin_can_make_shared_writes(client, db_engine, real_auth, monkeypatch):
    _insert_user(db_engine, user_id=707, username="the_admin", admin=True)
    monkeypatch.setattr("app.routers.market_data.run_all_exchanges", lambda db: {"exchanges": []})
    monkeypatch.setattr("app.routers.market_data.publish_portfolio_refresh", lambda *a, **k: None)
    auth = _token(client, "the_admin")

    assert client.post("/currencies", json={"code": "XTS"}, headers=auth).status_code == 200
    assert client.post(
        "/platforms",
        json={"code": "TESTBANK", "name": "Test Bank", "platform_type": "BANK", "country": "SG"},
        headers=auth,
    ).status_code == 200
    assert client.post("/market-data/refresh-now", headers=auth).status_code == 200
    # Reading shared data stays open to everyone.
    _insert_user(db_engine, user_id=708, username="reader")
    assert client.get("/currencies", headers=_token(client, "reader")).status_code == 200


# ---- make user-create / user-grant-admin ----


def test_user_admin_script_creates_and_grants(client, db_engine, real_auth, monkeypatch, capsys):
    from sqlalchemy.orm import sessionmaker

    from app.scripts import user_admin as script

    monkeypatch.setattr(script, "SessionLocal", sessionmaker(bind=db_engine))
    answers = iter([PASSWORD, PASSWORD])
    monkeypatch.setattr(script.getpass, "getpass", lambda prompt="": next(answers))

    monkeypatch.setattr("sys.argv", ["user_admin", "create", "new_owner", "--admin"])
    assert script.main() == 0
    assert _login(client, "new_owner").status_code == 200
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT is_admin FROM users WHERE username = 'new_owner'")).scalar() == 1

    monkeypatch.setattr("sys.argv", ["user_admin", "create", "NEW_OWNER"])
    assert script.main() == 1  # already exists (case-insensitive)

    monkeypatch.setattr("sys.argv", ["user_admin", "revoke-admin", "New_Owner"])
    assert script.main() == 0
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT is_admin FROM users WHERE username = 'new_owner'")).scalar() == 0
    monkeypatch.setattr("sys.argv", ["user_admin", "grant-admin", "new_owner"])
    assert script.main() == 0
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT is_admin FROM users WHERE username = 'new_owner'")).scalar() == 1

    monkeypatch.setattr("sys.argv", ["user_admin", "grant-admin", "ghost"])
    assert script.main() == 1

    answers = iter(["short", "short"])
    monkeypatch.setattr("sys.argv", ["user_admin", "create", "weak_user"])
    assert script.main() == 1
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM users WHERE username = 'weak_user'")).scalar() == 0
    capsys.readouterr()


# ---- Migration 072 and make demo-enable (SQL run against SQLite) ----


def _sql_file(*parts: str) -> str:
    here = Path(__file__).resolve()
    for root in (here.parents[2], Path("/app")):
        candidate = root.joinpath(*parts)
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").replace("NOW()", "CURRENT_TIMESTAMP")
    pytest.skip(f"{'/'.join(parts)} is not in this container (checked on Postgres by make db-migrate)")


def _run_sql(db_engine, sql: str) -> None:
    conn = db_engine.raw_connection()
    try:
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()


def test_migration_072_disables_demo_and_demo_enable_restores_it(client, db_engine, real_auth):
    disable = _sql_file("migrations", "072_disable_seeded_demo_user.sql")
    enable = _sql_file("scripts", "demo-enable.sql")
    _run_sql(db_engine, enable)  # a fresh install: 033 seeded demo / Test@1234
    _insert_user(db_engine, user_id=99709, username="owner")
    assert _login(client, "demo", "Test@1234").status_code == 200
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO auth_sessions (user_id, refresh_token_hash, expires_at) "
                "SELECT id, 'synthetic-hash', :exp FROM users WHERE username = 'demo'"
            ),
            {"exp": datetime.now(tz=timezone.utc) + timedelta(days=1)},
        )

    _run_sql(db_engine, disable)
    _run_sql(db_engine, disable)  # idempotent
    assert _login(client, "demo", "Test@1234").status_code == 401
    with db_engine.connect() as conn:
        demo = conn.execute(text("SELECT id, is_active FROM users WHERE username = 'demo'")).one()
        assert demo.is_active == 0
        open_sessions = conn.execute(
            text("SELECT COUNT(*) FROM auth_sessions WHERE user_id = :id AND revoked_at IS NULL"), {"id": demo.id}
        ).scalar()
        assert open_sessions == 0
        # Other users untouched.
        assert conn.execute(text("SELECT is_active FROM users WHERE username = 'owner'")).scalar() == 1
    assert _login(client, "owner").status_code == 200

    # Turning it back on by hand isn't enough: the published password is gone too.
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE users SET is_active = 1 WHERE username = 'demo'"))
    assert _login(client, "demo", "Test@1234").status_code == 401

    _run_sql(db_engine, enable)
    assert _login(client, "demo", "Test@1234").status_code == 200
