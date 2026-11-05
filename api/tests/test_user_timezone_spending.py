"""Per-user timezone, part 2 (#211): spending/cash-flow month windows and
crypto wallet snapshot dates follow the user's home timezone (D-49).

A month runs from midnight to midnight in the user's timezone. A timestamp at
exactly 00:00:00 UTC is a date-only statement row and counts on its calendar
date; any other timestamp is an instant. Synthetic users and data only.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import clock as core_clock
from app.crypto.ingest import SnapshotResult, upsert_snapshot, wallet_as_of_date
from app.valuation.clock import (
    _card_transaction_in_window,
    _parse_month,
    _transaction_date,
    _transaction_in_month_window,
    _transaction_month_key,
)
from app.valuation.facts import _cashflow
from tests.auth_helpers import ensure_user
from tests.valuation_household import NEW_YORK, as_user, freeze_clock, set_user_timezone

SINGAPORE = "Asia/Singapore"
NY_USER = 1  # the `client` fixture's user
SG_USER = 2
TOL = 0.01

# Every row is an SGD expense on a bank account (base SGD: no FX involved).
ROWS = [
    # 23:00 on 28 Feb in New York = 04:00Z on 1 Mar = 12:00 on 1 Mar in Singapore.
    ("2026-03-01 04:00:00+00:00", -50.0, "Late Feb NY"),
    # Date-only statement row: 1 Feb in every timezone.
    ("2026-02-01 00:00:00+00:00", -20.0, "Feb 1st statement row"),
    # 22:00 on 31 Jan in New York = 03:00Z on 1 Feb = 11:00 on 1 Feb in Singapore.
    ("2026-02-01 03:00:00+00:00", -7.0, "Early Feb SG"),
    # Date-only: 1 Mar everywhere.
    ("2026-03-01 00:00:00+00:00", -3000.0, "Mar 1st statement row"),
    # Mid-month, in every timezone.
    ("2026-02-14 12:00:00+00:00", -100.0, "Mid Feb"),
]
# February by each user's calendar.
NY_FEB = 50.0 + 20.0 + 100.0
SG_FEB = 20.0 + 7.0 + 100.0  # = the old 00:00 UTC window's total


def _seed_bank(db_engine, user_id: int, timezone_name: str) -> int:
    ensure_user(db_engine, user_id)
    set_user_timezone(db_engine, user_id, timezone_name)
    account_id = 9300 + user_id
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) "
                "VALUES (:id, 'Synthetic Bank', 'SYNTH', 'BANK', 'SGD', 'SG', :u)"
            ),
            {"id": account_id, "u": user_id},
        )
        conn.execute(
            text(
                "INSERT INTO transactions (ts, account_id, amount, type, currency, category, merchant_counterparty) "
                "VALUES (:ts, :a, :amt, 'EXPENSE', 'SGD', 'Groceries', :m)"
            ),
            [{"ts": ts, "a": account_id, "amt": amt, "m": merchant} for ts, amt, merchant in ROWS],
        )
    return account_id


@pytest.fixture()
def two_spenders(client: TestClient, db_engine, monkeypatch):
    monkeypatch.setenv("TZ", SINGAPORE)
    _seed_bank(db_engine, NY_USER, NEW_YORK)
    _seed_bank(db_engine, SG_USER, SINGAPORE)
    return client


def _summary(client: TestClient, user_id: int, month: str) -> dict:
    as_user(client, user_id)
    resp = client.get(f"/spending/summary?month={month}&base_currency=SGD")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_new_york_spending_month_runs_midnight_to_midnight_local(two_spenders):
    """23:00 on the month's last day (a real timestamp) is in New York's
    February; the date-only row on the 1st is in February; 22:00 on 31 Jan
    local is January's."""
    feb = _summary(two_spenders, NY_USER, "2026-02")
    assert feb["expense_total"] == pytest.approx(NY_FEB, abs=TOL)
    jan = _summary(two_spenders, NY_USER, "2026-01")
    assert jan["expense_total"] == pytest.approx(7.0, abs=TOL)
    mar = _summary(two_spenders, NY_USER, "2026-03")
    assert mar["expense_total"] == pytest.approx(3000.0, abs=TOL)


def test_singapore_spending_is_unchanged(two_spenders):
    """For Singapore the local month and the old UTC month hold the same rows."""
    assert _summary(two_spenders, SG_USER, "2026-02")["expense_total"] == pytest.approx(SG_FEB, abs=TOL)
    assert _summary(two_spenders, SG_USER, "2026-01")["expense_total"] == pytest.approx(0.0, abs=TOL)
    assert _summary(two_spenders, SG_USER, "2026-03")["expense_total"] == pytest.approx(3050.0, abs=TOL)


def test_cash_flow_detail_lists_and_trends_by_local_month(two_spenders):
    as_user(two_spenders, NY_USER)
    resp = two_spenders.get("/spending/cash-flow-detail?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["expense_total"] == pytest.approx(NY_FEB, abs=TOL)
    merchants = {tx["merchant_counterparty"] for tx in data["expenses"]["transactions"]}
    assert merchants == {"Late Feb NY", "Feb 1st statement row", "Mid Feb"}
    # The six-month trend buckets the same rows the same way.
    trend = {point["month"]: point["outflows"] for point in data["analytics"]["trend"]}
    assert trend["2026-01"] == pytest.approx(7.0, abs=TOL)
    assert trend["2026-02"] == pytest.approx(NY_FEB, abs=TOL)


def test_dashboard_cash_flow_uses_the_users_month(two_spenders, db_engine):
    start, end = _parse_month("2026-02"), _parse_month("2026-03")
    with Session(db_engine) as db:
        with core_clock.use_timezone(NEW_YORK):
            ny = _cashflow(db, start, end, "SGD", NY_USER)
        with core_clock.use_timezone(SINGAPORE):
            sg = _cashflow(db, start, end, "SGD", SG_USER)
    assert ny["expenses"] == pytest.approx(NY_FEB, abs=TOL)
    assert sg["expenses"] == pytest.approx(SG_FEB, abs=TOL)


def test_dashboard_summary_cash_flow_for_a_new_york_user(two_spenders):
    as_user(two_spenders, NY_USER)
    resp = two_spenders.get("/dashboard/summary?month=2026-02&base_currency=SGD&compare=prev_month")
    assert resp.status_code == 200, resp.text
    assert resp.json()["cash_flow"]["expenses"] == pytest.approx(NY_FEB, abs=TOL)


def test_credit_card_spend_uses_the_users_month(client: TestClient, db_engine, monkeypatch):
    """The card pages' month spend follows the same window (no available limit,
    so current_due is the month's transactions)."""
    monkeypatch.setenv("TZ", SINGAPORE)
    set_user_timezone(db_engine, NY_USER, NEW_YORK)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) "
                "VALUES (9401, 'Synthetic Card', 'SYNTH', 'CREDIT_CARD', 'SGD', 'SG', :u)"
            ),
            {"u": NY_USER},
        )
        conn.execute(
            text(
                "INSERT INTO credit_card_accounts (account_id, card_name, issuer, credit_limit, statement_day, due_day) "
                "VALUES (9401, 'Synthetic', 'SYNTH', 10000, 20, 25)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO transactions (ts, account_id, amount, type, currency, merchant_counterparty) "
                "VALUES (:ts, 9401, :amt, 'EXPENSE', 'SGD', :m)"
            ),
            [{"ts": ts, "amt": amt, "m": merchant} for ts, amt, merchant in ROWS],
        )
    resp = client.get("/spending/credit-cards?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_spend"] == pytest.approx(NY_FEB, abs=TOL)
    resp = client.get("/spending/credit-card-transactions?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200, resp.text
    assert {tx["merchant_counterparty"] for tx in resp.json()["transactions"]} == {
        "Late Feb NY",
        "Feb 1st statement row",
        "Mid Feb",
    }
    resp = client.get("/spending/credit-card-analytics?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_spend"] == pytest.approx(NY_FEB, abs=TOL)


# ─── The shared rule ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("timezone_name", [SINGAPORE, NEW_YORK, "UTC", "Pacific/Kiritimati", "Pacific/Pago_Pago"])
def test_month_window_is_the_card_month_rule(timezone_name):
    """One rule (#202): a transaction's month key, the month window and the
    card window with a date anchor agree for every row."""
    start, end = _parse_month("2026-02"), _parse_month("2026-03")
    with core_clock.use_timezone(timezone_name):
        for ts_text, _amt, _m in ROWS:
            ts = datetime.fromisoformat(ts_text)
            in_feb = _transaction_month_key(ts) == "2026-02"
            assert _transaction_in_month_window(ts, start, end) is in_feb
            assert _card_transaction_in_window(ts, date(2026, 2, 1), end) is in_feb
            assert _transaction_month_key(ts_text) == _transaction_month_key(ts)


def test_transaction_date_rule():
    with core_clock.use_timezone(NEW_YORK):
        assert _transaction_date(datetime(2026, 3, 1, 4, 0, tzinfo=timezone.utc)) == date(2026, 2, 28)
        assert _transaction_date(datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)) == date(2026, 3, 1)
        assert _transaction_date("2026-03-01 00:00:00+00:00") == date(2026, 3, 1)
        assert _transaction_date(date(2026, 3, 1)) == date(2026, 3, 1)
    with core_clock.use_timezone(SINGAPORE):
        assert _transaction_date(datetime(2026, 2, 28, 20, 0, tzinfo=timezone.utc)) == date(2026, 3, 1)


# ─── Crypto wallet snapshot dates ────────────────────────────────────────────

# 02:00Z on 1 April: 10:00 on 1 April in Singapore, 22:00 on 31 March in New York.
SNAPSHOT_INSTANT = datetime(2026, 4, 1, 2, 0, tzinfo=timezone.utc)


def _seed_wallet(db_engine, wallet_id: str, user_id: int, timezone_name: str) -> None:
    ensure_user(db_engine, user_id)
    set_user_timezone(db_engine, user_id, timezone_name)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO crypto_wallets (id, user_id, chain_type, chain, address, status, created_at) VALUES "
                "(:id, :u, 'evm', 'ethereum', :addr, 'active', :t)"
            ),
            {"id": wallet_id, "u": user_id, "addr": f"0xsyn{user_id}", "t": datetime(2026, 1, 1, tzinfo=timezone.utc)},
        )


def _snapshot_dates(db_engine, wallet_id: str) -> list[str]:
    with db_engine.begin() as conn:
        rows = conn.execute(
            text("SELECT as_of_date FROM crypto_wallet_snapshots WHERE wallet_id = :w ORDER BY as_of_date"),
            {"w": wallet_id},
        ).fetchall()
    return [str(row[0])[:10] for row in rows]


@pytest.mark.parametrize("bound_timezone", [None, SINGAPORE, NEW_YORK])
def test_crypto_snapshot_is_dated_in_the_wallet_owners_timezone(db_engine, monkeypatch, bound_timezone):
    """A snapshot is filed under today in the owner's timezone, whoever runs
    the refresh: the scheduler (no user), or a request bound to another
    user's timezone."""
    monkeypatch.setenv("TZ", SINGAPORE)
    freeze_clock(monkeypatch, SNAPSHOT_INSTANT)
    _seed_wallet(db_engine, "wallet-ny", NY_USER, NEW_YORK)
    _seed_wallet(db_engine, "wallet-sg", SG_USER, SINGAPORE)
    with Session(db_engine) as db:
        if bound_timezone is None:
            upsert_snapshot(db, "wallet-ny", SnapshotResult(total_usd=10.0, items=[], source_versions={}))
            upsert_snapshot(db, "wallet-sg", SnapshotResult(total_usd=10.0, items=[], source_versions={}))
        else:
            with core_clock.use_timezone(bound_timezone):
                upsert_snapshot(db, "wallet-ny", SnapshotResult(total_usd=10.0, items=[], source_versions={}))
                upsert_snapshot(db, "wallet-sg", SnapshotResult(total_usd=10.0, items=[], source_versions={}))
        db.commit()
        assert wallet_as_of_date(db, "wallet-ny") == date(2026, 3, 31)
        assert wallet_as_of_date(db, "wallet-sg") == date(2026, 4, 1)
    assert _snapshot_dates(db_engine, "wallet-ny") == ["2026-03-31"]
    assert _snapshot_dates(db_engine, "wallet-sg") == ["2026-04-01"]


def test_crypto_snapshot_for_a_user_without_a_timezone_uses_the_app_timezone(db_engine, monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    freeze_clock(monkeypatch, datetime(2026, 4, 1, 23, 30, tzinfo=timezone.utc))
    ensure_user(db_engine, 5)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO crypto_wallets (id, user_id, chain_type, chain, address, status, created_at) VALUES "
                "('wallet-app', 5, 'evm', 'ethereum', '0xsynapp', 'active', :t)"
            ),
            {"t": datetime(2026, 1, 1, tzinfo=timezone.utc)},
        )
    with Session(db_engine) as db, core_clock.use_timezone(SINGAPORE):
        # Bound to Singapore (2 April there), but the owner has no timezone: the app's (UTC, 1 April).
        assert wallet_as_of_date(db, "wallet-app") == date(2026, 4, 1)
