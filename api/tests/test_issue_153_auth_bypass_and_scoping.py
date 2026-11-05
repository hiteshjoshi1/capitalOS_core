"""#153: the login bypass needs an explicit test flag, shared read endpoints are
scoped to the caller, and parser registration is validated and admin-only."""

import logging
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.auth_context import (
    AuthBypassConfigError,
    CurrentUser,
    check_auth_bypass_config,
    require_current_user,
)
from app.main import app
from app.models.parser_registry import ParserRegistry

API_DIR = Path(__file__).resolve().parents[1]

USER_A = 2
USER_B = 3


@contextmanager
def act_as(user_id: int, *, admin: bool = False):
    app.dependency_overrides[require_current_user] = lambda: CurrentUser(
        id=user_id, username=f"user{user_id}", is_admin=admin
    )
    try:
        yield
    finally:
        app.dependency_overrides.pop(require_current_user, None)


# ─── (1) AUTH_BYPASS_USER_ID guard ──────────────────────────────────────────


def test_bypass_off_when_unset(monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.delenv("AUTH_BYPASS_ALLOW", raising=False)
    assert check_auth_bypass_config() is None


def test_bypass_without_test_flag_refuses(monkeypatch):
    monkeypatch.setenv("AUTH_BYPASS_USER_ID", "1")
    monkeypatch.delenv("AUTH_BYPASS_ALLOW", raising=False)
    with pytest.raises(AuthBypassConfigError, match="AUTH_BYPASS_ALLOW=test"):
        check_auth_bypass_config()
    monkeypatch.setenv("AUTH_BYPASS_ALLOW", "yes")
    with pytest.raises(AuthBypassConfigError):
        check_auth_bypass_config()


def test_bypass_with_non_integer_id_refuses(monkeypatch):
    monkeypatch.setenv("AUTH_BYPASS_USER_ID", "admin")
    monkeypatch.setenv("AUTH_BYPASS_ALLOW", "test")
    with pytest.raises(AuthBypassConfigError, match="not an integer"):
        check_auth_bypass_config()


def test_bypass_with_test_flag_is_active_and_warns(monkeypatch, caplog):
    monkeypatch.setenv("AUTH_BYPASS_USER_ID", "7")
    monkeypatch.setenv("AUTH_BYPASS_ALLOW", "test")
    with caplog.at_level(logging.WARNING, logger="capitalos.auth"):
        assert check_auth_bypass_config() == 7
    assert any("AUTH BYPASS ACTIVE" in record.getMessage() for record in caplog.records)


def test_bypass_ignored_at_request_time_without_flag(monkeypatch, anon_client):
    """Fail closed: without the flag the bypass grants nothing; login applies."""
    client = anon_client  # these checks need a request with no credentials (#154)
    monkeypatch.setenv("AUTH_BYPASS_USER_ID", "1")
    monkeypatch.delenv("AUTH_BYPASS_ALLOW", raising=False)
    with pytest.raises(HTTPException) as exc:
        require_current_user(db=None, authorization=None)
    assert exc.value.status_code == 401
    assert client.get("/platforms/options").status_code == 401


def test_api_refuses_to_start_with_unflagged_bypass(tmp_path):
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"AUTH_BYPASS_ALLOW", "AUTH_BYPASS_USER_ID"}
    }
    env.update(
        {
            "AUTH_BYPASS_USER_ID": "1",
            "DATABASE_URL": f"sqlite+pysqlite:///{tmp_path / 'refuse.db'}",
            "AUTH_ACCESS_TOKEN_SECRET": "test-access-secret",
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=API_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode != 0
    assert "AuthBypassConfigError" in result.stderr


# ─── (2) market data scoped to the caller's holdings ────────────────────────


@pytest.fixture()
def two_users_two_tickers(db_engine):
    """User A holds AAAA (legacy position); user B holds BBBB (canonical position
    snapshot) and traded CCCC (transaction). DDDD is held by nobody."""
    now = datetime.now(tz=timezone.utc)
    fresh_ts = now - timedelta(days=1)
    with db_engine.begin() as conn:
        for user_id in (USER_A, USER_B):
            conn.execute(
                text(
                    "INSERT INTO users (id, username, display_name, is_active, is_admin, created_at, updated_at) "
                    "VALUES (:id, :u, :u, 1, 0, :now, :now)"
                ),
                {"id": user_id, "u": f"user{user_id}", "now": now},
            )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES "
                "(1531, 'A Broker', 'BROKER_A', 'BROKER', 'USD', 'ZA', :a), "
                "(1532, 'B Broker', 'BROKER_B', 'BROKER', 'USD', 'ZB', :b)"
            ),
            {"a": USER_A, "b": USER_B},
        )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(15301, 'AAAA', 'Synthetic A', 'STOCK', 'USD', 'US'), "
                "(15302, 'BBBB', 'Synthetic B', 'STOCK', 'USD', 'US'), "
                "(15303, 'CCCC', 'Synthetic C', 'STOCK', 'USD', 'US'), "
                "(15304, 'DDDD', 'Synthetic D', 'STOCK', 'USD', 'US')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO market_symbol_map (asset_id, exchange_code, exchange_symbol, quote_currency, is_active) VALUES "
                "(15301, 'US', 'AAAA', 'USD', 1), (15302, 'US', 'BBBB', 'USD', 1), "
                "(15303, 'US', 'CCCC', 'USD', 1), (15304, 'US', 'DDDD', 'USD', 1)"
            )
        )
        for asset_id in (15301, 15302, 15303, 15304):
            conn.execute(
                text(
                    "INSERT INTO prices (asset_id, ts, price, currency, source, trade_date, exchange_code, provider_symbol) "
                    "VALUES (:asset_id, :ts, 10, 'USD', 'yahoo_market', :trade_date, 'US', 'X')"
                ),
                {"asset_id": asset_id, "ts": fresh_ts, "trade_date": fresh_ts.date()},
            )
        conn.execute(
            text(
                "INSERT INTO positions (account_id, asset_id, as_of, quantity, avg_cost, cost_basis_base) "
                "VALUES (1531, 15301, :ts, 5, 10, 50)"
            ),
            {"ts": now},
        )
        conn.execute(
            text(
                "INSERT INTO transactions (ts, account_id, type, amount, currency, asset_id, quantity, source) "
                "VALUES (:ts, 1532, 'BUY', -10, 'USD', 15303, 1, 'MANUAL')"
            ),
            {"ts": now},
        )
        conn.execute(
            text(
                "INSERT INTO broker_connections (id, user_id, platform_code, connection_type, status) "
                "VALUES (1530, :b, 'BROKER_B', 'upload', 'active')"
            ),
            {"b": USER_B},
        )
        conn.execute(
            text(
                "INSERT INTO broker_accounts (id, connection_id, legacy_account_id, broker_account_id, base_currency) "
                "VALUES (1530, 1530, 1532, 'SYN-B', 'USD')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO broker_instruments (id, platform_code, broker_instrument_id, asset_id, symbol) "
                "VALUES (1530, 'BROKER_B', 'SYN-BBBB', 15302, 'BBBB')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO broker_import_runs (id, broker_account_id, legacy_account_id, platform_code, source_type, status) "
                "VALUES (1530, 1530, 1532, 'BROKER_B', 'upload', 'completed')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO portfolio_position_snapshots (broker_account_id, legacy_account_id, broker_instrument_id, "
                "import_run_id, report_date, quantity, currency, market_value_local, market_value_base, fx_rate_to_base) "
                "VALUES (1530, 1532, 1530, 1530, :d, 3, 'USD', 30, 30, 1)"
            ),
            {"d": now.date()},
        )


def _us_symbols(client) -> tuple[set[str], dict]:
    resp = client.get("/market-data/status")
    assert resp.status_code == 200
    us = next(row for row in resp.json()["status"] if row["exchange_code"] == "US")
    return {item["symbol"] for item in us["symbols"]}, us["diagnostics_summary"]


def test_market_data_status_only_shows_the_callers_tickers(client, two_users_two_tickers, monkeypatch):
    monkeypatch.setenv("STOCK_EXCHANGES", "US")
    with act_as(USER_A):
        symbols_a, summary_a = _us_symbols(client)
    with act_as(USER_B):
        symbols_b, summary_b = _us_symbols(client)

    assert symbols_a == {"AAAA"}
    assert summary_a["active_symbols"] == 1
    assert summary_a["fresh"] == 1
    # B sees its canonical snapshot holding and its traded asset, never A's ticker.
    assert symbols_b == {"BBBB", "CCCC"}
    assert "AAAA" not in symbols_b
    assert summary_b["active_symbols"] == 2


def test_market_data_status_admin_sees_every_symbol(client, two_users_two_tickers, monkeypatch):
    monkeypatch.setenv("STOCK_EXCHANGES", "US")
    with act_as(USER_A, admin=True):
        symbols, summary = _us_symbols(client)
    assert symbols == {"AAAA", "BBBB", "CCCC", "DDDD"}
    assert summary["active_symbols"] == 4


def test_market_data_status_response_shape_unchanged_for_a_user_with_no_holdings(client, db_engine, monkeypatch):
    monkeypatch.setenv("STOCK_EXCHANGES", "US")
    with act_as(99):
        resp = client.get("/market-data/status")
    assert resp.status_code == 200
    us = resp.json()["status"][0]
    assert us["exchange_code"] == "US"
    assert us["symbols"] == []
    assert set(us["diagnostics_summary"]) == {
        "active_symbols", "refreshed", "failed", "deferred", "fresh", "stale", "missing",
    }


def test_market_data_refresh_diagnostics_scoped_for_non_admin(client, two_users_two_tickers, monkeypatch):
    monkeypatch.setenv("STOCK_EXCHANGES", "US")
    monkeypatch.delenv("STOCK_ADMIN_KEY", raising=False)
    monkeypatch.delenv("CRYPTO_ADMIN_KEY", raising=False)
    monkeypatch.setattr(
        "app.routers.market_data.run_all_exchanges",
        lambda db: {
            "exchanges": [
                {
                    "exchange_code": "US",
                    "status": "success",
                    "diagnostics": {
                        "exchange_code": "US",
                        "diagnostics_summary": {},
                        "symbols": [
                            {"asset_id": 15301, "symbol": "AAAA", "freshness_status": "fresh", "refresh_status": "refreshed"},
                            {"asset_id": 15304, "symbol": "DDDD", "freshness_status": "stale", "refresh_status": "failed"},
                        ],
                    },
                }
            ]
        },
    )
    monkeypatch.setattr("app.routers.market_data.publish_portfolio_refresh", lambda *a, **k: None)
    # #152 made refresh-now admin-only (D-n in the batch), so a non-admin can't
    # reach the per-user diagnostics scoping any more: it gets 403 instead.
    with act_as(USER_A):
        resp = client.post("/market-data/refresh-now")
    assert resp.status_code == 403


def test_data_hub_market_counts_are_per_user(client, two_users_two_tickers, monkeypatch):
    monkeypatch.setenv("STOCK_EXCHANGES", "US")
    for user_id, expected in ((USER_A, 1), (USER_B, 2)):
        with act_as(user_id):
            resp = client.get("/dashboard/data-hub-summary")
        assert resp.status_code == 200
        assert resp.json()["market_data"]["fresh"] == expected
    # The card is about the caller's own data even for an admin.
    with act_as(USER_A, admin=True):
        resp = client.get("/dashboard/data-hub-summary")
    assert resp.json()["market_data"]["fresh"] == 1


# ─── (3) /platforms/options countries ───────────────────────────────────────


def test_platform_options_countries_only_from_callers_accounts(client, two_users_two_tickers):
    with act_as(USER_A):
        countries_a = client.get("/platforms/options").json()["countries"]
    with act_as(USER_B):
        countries_b = client.get("/platforms/options").json()["countries"]
    assert "ZA" in countries_a and "ZB" not in countries_a
    assert "ZB" in countries_b and "ZA" not in countries_b


# ─── (4) parser registration ────────────────────────────────────────────────


@pytest.fixture()
def needs_mapping_job(db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, display_name, is_active, is_admin, created_at, updated_at) "
                "VALUES (:id, 'user2', 'user2', 1, 0, :now, :now)"
            ),
            {"id": USER_A, "now": datetime.now(tz=timezone.utc)},
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES "
                "(1533, 'A Bank', 'DBS', 'BANK', 'SGD', 'SG', :a)"
            ),
            {"a": USER_A},
        )
        conn.execute(
            text(
                "INSERT INTO import_jobs (id, account_id, platform, original_filename, stored_path, file_sha256, "
                "format_signature, status, created_at) VALUES "
                "(1533, 1533, 'DBS', 'x.csv', '/nonexistent/x.csv', 'hash-153', 'sig-153', 'NEEDS_MAPPING', :now)"
            ),
            {"now": datetime.now(tz=timezone.utc)},
        )
    return 1533


def _registered(db_engine) -> str | None:
    db = sessionmaker(bind=db_engine)()
    try:
        row = db.query(ParserRegistry).filter(ParserRegistry.format_signature == "sig-153").one_or_none()
        return row.parser_key if row else None
    finally:
        db.close()


def test_register_requires_admin(client, db_engine, needs_mapping_job):
    with act_as(USER_A):
        resp = client.post(f"/ingest/jobs/{needs_mapping_job}/register", json={"parser_key": "ocbc_account_csv_v1"})
    assert resp.status_code == 403
    assert _registered(db_engine) is None


def test_register_rejects_unknown_parser_key(client, db_engine, needs_mapping_job):
    with act_as(USER_A, admin=True):
        resp = client.post(f"/ingest/jobs/{needs_mapping_job}/register", json={"parser_key": "made_up_parser_v9"})
    assert resp.status_code == 400
    assert "Unknown parser_key" in resp.json()["detail"]
    assert _registered(db_engine) is None


def test_admin_can_register_and_correct_a_mapping(client, db_engine, needs_mapping_job, monkeypatch):
    monkeypatch.setattr("app.routers.ingest.run_ingestion", lambda **kwargs: {"status": "IMPORTED"})
    with act_as(USER_A, admin=True):
        first = client.post(f"/ingest/jobs/{needs_mapping_job}/register", json={"parser_key": "ocbc_account_csv_v1"})
        assert first.status_code == 200
        assert _registered(db_engine) == "ocbc_account_csv_v1"
        # Not first-writer-wins any more: an admin correction replaces the mapping.
        second = client.post(
            f"/ingest/jobs/{needs_mapping_job}/register", json={"parser_key": "dbs_transaction_history_csv_v1"}
        )
    assert second.status_code == 200
    assert _registered(db_engine) == "dbs_transaction_history_csv_v1"
