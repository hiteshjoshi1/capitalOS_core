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


def _cookie_value(set_cookie_header: str, name: str) -> str:
    for raw in set_cookie_header.split(","):
        first = raw.strip().split(";", 1)[0]
        if first.startswith(f"{name}="):
            return first.split("=", 1)[1]
    raise AssertionError(f"Cookie {name} not found in header: {set_cookie_header}")


def test_auth_signup_login_me_logout(client, db_engine, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")

    signup = client.post(
        "/auth/signup",
        json={"username": "alpha_user", "password": "AlphaPass123!", "display_name": "Alpha"},
    )
    assert signup.status_code == 200
    payload = signup.json()
    assert payload["username"] == "alpha_user"
    assert payload["display_name"] == "Alpha"

    duplicate = client.post(
        "/auth/signup",
        json={"username": "alpha_user", "password": "AlphaPass123!", "display_name": "Alpha"},
    )
    assert duplicate.status_code == 409

    invalid_login = client.post(
        "/auth/login",
        json={"username": "alpha_user", "password": "wrong-password"},
    )
    assert invalid_login.status_code == 401

    login = client.post(
        "/auth/login",
        json={"username": "alpha_user", "password": "AlphaPass123!"},
    )
    assert login.status_code == 200
    login_payload = login.json()
    assert login_payload["token_type"] == "bearer"
    assert login_payload["access_token"]
    assert login_payload["expires_in"] > 0
    assert "capitalos_refresh" in login.headers.get("set-cookie", "")
    assert "SameSite=Strict" in login.headers.get("set-cookie", "")

    me_unauthorized = client.get("/auth/me")
    assert me_unauthorized.status_code == 401

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {login_payload['access_token']}"})
    assert me.status_code == 200
    assert me.json()["username"] == "alpha_user"

    logout = client.post("/auth/logout")
    assert logout.status_code == 200
    assert logout.json()["status"] == "ok"

    with db_engine.begin() as conn:
        revoked = conn.execute(
            text("SELECT COUNT(*) FROM auth_sessions WHERE revoked_at IS NOT NULL")
        ).scalar_one()
        assert int(revoked) == 1


def test_auth_refresh_rotates_session(client, db_engine, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")
    monkeypatch.setenv("AUTH_REFRESH_GRACE_SECONDS", "0")  # disable grace window for strict rotation test

    _insert_user_with_password(db_engine, user_id=900, username="refresh_user", password="RefreshPass1!")
    login = client.post("/auth/login", json={"username": "refresh_user", "password": "RefreshPass1!"})
    assert login.status_code == 200
    old_cookie = _cookie_value(login.headers.get("set-cookie", ""), "capitalos_refresh")

    refreshed = client.post("/auth/refresh")
    assert refreshed.status_code == 200
    second_token = refreshed.json()["access_token"]
    assert second_token
    new_cookie = _cookie_value(refreshed.headers.get("set-cookie", ""), "capitalos_refresh")
    assert new_cookie
    assert new_cookie != old_cookie

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {second_token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "refresh_user"

    with db_engine.begin() as conn:
        active = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM auth_sessions
                WHERE user_id = 900
                  AND revoked_at IS NULL
                """
            )
        ).scalar_one()
        revoked = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM auth_sessions
                WHERE user_id = 900
                  AND revoked_at IS NOT NULL
                """
            )
        ).scalar_one()
        assert int(active) == 1
        assert int(revoked) == 1

    client.cookies.clear()
    reused = client.post("/auth/refresh", cookies={"capitalos_refresh": old_cookie})
    assert reused.status_code == 401


def test_auth_refresh_grace_window_concurrent(client, db_engine, monkeypatch):
    """Two concurrent refresh requests with the same token: second should succeed via grace window."""
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")
    monkeypatch.setenv("AUTH_REFRESH_GRACE_SECONDS", "30")

    _insert_user_with_password(db_engine, user_id=901, username="concurrent_user", password="ConcPass1!")
    login = client.post("/auth/login", json={"username": "concurrent_user", "password": "ConcPass1!"})
    assert login.status_code == 200
    original_cookie = _cookie_value(login.headers.get("set-cookie", ""), "capitalos_refresh")

    # First refresh: succeeds and rotates the session
    first = client.post("/auth/refresh")
    assert first.status_code == 200
    first_token = first.json()["access_token"]
    assert first_token

    # Simulate concurrent second request with the original cookie (race condition)
    # This should succeed because the original token was rotated within the grace window
    client.cookies.clear()
    second = client.post("/auth/refresh", cookies={"capitalos_refresh": original_cookie})
    assert second.status_code == 200, f"Concurrent refresh should succeed within grace window, got: {second.json()}"
    second_token = second.json()["access_token"]
    assert second_token

    # After concurrent refresh, there should be exactly 1 active session
    with db_engine.begin() as conn:
        active = conn.execute(
            text(
                "SELECT COUNT(*) FROM auth_sessions WHERE user_id = 901 AND revoked_at IS NULL"
            )
        ).scalar_one()
        assert int(active) == 1


def test_auth_refresh_grace_window_logout_not_recovered(client, db_engine, monkeypatch):
    """After explicit logout, even within grace window, refresh with old token should fail."""
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")
    monkeypatch.setenv("AUTH_REFRESH_GRACE_SECONDS", "30")

    _insert_user_with_password(db_engine, user_id=902, username="logout_user", password="LogoutPass1!")
    login = client.post("/auth/login", json={"username": "logout_user", "password": "LogoutPass1!"})
    assert login.status_code == 200
    original_cookie = _cookie_value(login.headers.get("set-cookie", ""), "capitalos_refresh")

    # Explicit logout
    client.post("/auth/logout")

    # Attempt to refresh with old cookie immediately after logout: should fail
    client.cookies.clear()
    reuse = client.post("/auth/refresh", cookies={"capitalos_refresh": original_cookie})
    assert reuse.status_code == 401, "Logout-revoked tokens must not be recovered"

    with db_engine.begin() as conn:
        reason = conn.execute(
            text(
                "SELECT revoke_reason FROM auth_sessions WHERE user_id = 902 ORDER BY id DESC LIMIT 1"
            )
        ).scalar_one()
        assert reason == "logout"


def test_auth_refresh_requires_cookie(client, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")

    res = client.post("/auth/refresh")
    assert res.status_code == 401


def test_auth_refresh_cookie_samesite_can_be_overridden(client, db_engine, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")
    monkeypatch.setenv("AUTH_COOKIE_SAMESITE", "lax")

    _insert_user_with_password(db_engine, user_id=903, username="samesite_user", password="SameSitePass1!")
    login = client.post("/auth/login", json={"username": "samesite_user", "password": "SameSitePass1!"})
    assert login.status_code == 200
    assert "SameSite=Lax" in login.headers.get("set-cookie", "")


def test_accounts_are_user_scoped(client, db_engine, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")

    _insert_user_with_password(db_engine, user_id=11, username="owner_a", password="OwnerAPass1!")
    _insert_user_with_password(db_engine, user_id=22, username="owner_b", password="OwnerBPass1!")

    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country)
                VALUES
                  (1, 'A DBS', 'DBS', 11, 'BANK', 'SGD', 'SG'),
                  (2, 'B UOB', 'UOB', 22, 'BANK', 'SGD', 'SG'),
                  (3, 'Legacy', 'OCBC', NULL, 'BANK', 'SGD', 'SG')
                """
            )
        )

    login_a = client.post("/auth/login", json={"username": "owner_a", "password": "OwnerAPass1!"})
    assert login_a.status_code == 200
    token_a = login_a.json()["access_token"]

    accounts_a = client.get("/accounts", headers={"Authorization": f"Bearer {token_a}"})
    assert accounts_a.status_code == 200
    ids = [row["id"] for row in accounts_a.json()]
    assert ids == [1]


def test_accounts_can_include_legacy_null_owner_when_enabled(client, db_engine, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "1")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")

    _insert_user_with_password(db_engine, user_id=31, username="legacy_a", password="LegacyAPass1!")
    _insert_user_with_password(db_engine, user_id=32, username="legacy_b", password="LegacyBPass1!")

    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country)
                VALUES
                  (1, 'Owned A', 'DBS', 31, 'BANK', 'SGD', 'SG'),
                  (2, 'Owned B', 'UOB', 32, 'BANK', 'SGD', 'SG'),
                  (3, 'Legacy', 'OCBC', NULL, 'BANK', 'SGD', 'SG')
                """
            )
        )

    login_a = client.post("/auth/login", json={"username": "legacy_a", "password": "LegacyAPass1!"})
    assert login_a.status_code == 200
    token_a = login_a.json()["access_token"]

    accounts_a = client.get("/accounts", headers={"Authorization": f"Bearer {token_a}"})
    assert accounts_a.status_code == 200
    ids = [row["id"] for row in accounts_a.json()]
    assert ids == [1, 3]


def test_reassign_legacy_ownership_service(db_engine):
    _insert_user_with_password(db_engine, user_id=101, username="personal", password="PersonalPass123!")

    with db_engine.begin() as conn:
        now = datetime.now(tz=timezone.utc)
        conn.execute(
            text(
                """
                INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country)
                VALUES
                  (1, 'Legacy A', 'DBS', NULL, 'BANK', 'SGD', 'SG'),
                  (2, 'Owned B', 'UOB', 101, 'BANK', 'SGD', 'SG')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO crypto_wallets (id, user_id, chain_type, chain, address, label, status, created_at)
                VALUES
                  ('wallet-1', NULL, 'evm', 'ethereum', '0xabc', 'w1', 'active', :now),
                  ('wallet-2', 101, 'evm', 'ethereum', '0xdef', 'w2', 'active', :now)
                """
            ),
            {"now": now},
        )
        conn.execute(
            text(
                """
                INSERT INTO crypto_user_networth (id, user_id, as_of_date, total_usd, crypto_usd, updated_at)
                VALUES
                  (1, NULL, '2026-03-01', 100, 100, :now),
                  (2, 101, '2026-03-01', 200, 200, :now)
                """
            ),
            {"now": now},
        )

    from app.db.session import SessionLocal
    from app.services.ownership import reassign_legacy_ownership

    db = SessionLocal()
    try:
        dry_run = reassign_legacy_ownership(db, target_user_id=101, dry_run=True)
        assert dry_run.accounts_updated == 1
        assert dry_run.wallets_updated == 1
        assert dry_run.crypto_networth_updated == 1

        applied = reassign_legacy_ownership(db, target_user_id=101, dry_run=False)
        assert applied.accounts_updated == 1
        assert applied.wallets_updated == 1
        assert applied.crypto_networth_updated == 1
    finally:
        db.close()

    with db_engine.begin() as conn:
        owned_accounts = conn.execute(
            text("SELECT COUNT(*) FROM accounts WHERE user_id = 101")
        ).scalar_one()
        owned_wallets = conn.execute(
            text("SELECT COUNT(*) FROM crypto_wallets WHERE user_id = 101")
        ).scalar_one()
        owned_networth = conn.execute(
            text("SELECT COUNT(*) FROM crypto_user_networth WHERE user_id = 101")
        ).scalar_one()
        assert int(owned_accounts) == 2
        assert int(owned_wallets) == 2
        assert int(owned_networth) == 2
