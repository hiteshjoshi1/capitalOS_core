"""Cash Flow's cash bridge uses the nearest cash snapshots (#265, D-72).

It used to need exact snapshots on the month's anchors (the 1st with SNAPSHOT_DAY=1), so it
never drew mid-month or for month-end statements. Now it runs from the nearest cash snapshot
at or before the month's start anchor to the nearest at or before its end anchor, and says so.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.canonical_test_helpers import seed_canonical_account_balance_for_test


def _bank_account(db_engine, account_id: int = 950) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES "
                f"({account_id}, 'Synthetic Bank', 'DBS', 'BANK', 'SGD', 'SG', 1)"
            )
        )


def _balance(db_engine, as_of: str, amount: float, account_id: int = 950) -> None:
    seed_canonical_account_balance_for_test(
        db_engine, account_id=account_id, as_of=as_of, currency="SGD", balance_base=amount, balance_type="bank_cash"
    )


def _tx(db_engine, tx_id: int, ts: str, amount: float, type_: str, category: str, account_id: int = 950) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO transactions (id, ts, account_id, amount, type, currency, category, merchant_counterparty, notes) "
                "VALUES (:id, :ts, :acc, :amount, :type, 'SGD', :category, 'Synthetic', NULL)"
            ),
            {"id": tx_id, "ts": ts, "acc": account_id, "amount": amount, "type": type_, "category": category},
        )


def _waterfall(client: TestClient, month: str) -> dict:
    resp = client.get(f"/spending/cash-flow-detail?month={month}&base_currency=SGD")
    assert resp.status_code == 200
    return resp.json()["analytics"]["waterfall"]


def test_mid_month_snapshots_draw_the_bridge_with_their_dates(client: TestClient, db_engine):
    """Statements on 6 May and 4 Jun: June's bridge runs from the nearest at or before 1 Jun
    (6 May) to the nearest at or before 1 Jul (4 Jun), and balances."""
    _bank_account(db_engine)
    _balance(db_engine, "2026-05-06", 10_000)
    _balance(db_engine, "2026-06-04", 12_000)
    _tx(db_engine, 9501, "2026-05-20 12:00:00+00:00", 5_000, "INCOME", "Salary")
    _tx(db_engine, 9502, "2026-05-25 12:00:00+00:00", -2_500, "EXPENSE", "Rent")
    _tx(db_engine, 9503, "2026-06-10 12:00:00+00:00", 999, "INCOME", "Salary")  # after the end snapshot

    wf = _waterfall(client, "2026-06")

    assert wf["bridge_available"] is True
    assert wf["span_start"] == "2026-05-06"
    assert wf["span_end"] == "2026-06-04"
    assert wf["span_basis"] == "nearest"
    assert wf["availability_message"] is None
    assert wf["boundary_exact"] is False  # unchanged meaning: not on the anchors
    assert wf["starting_cash"] == pytest.approx(10_000)
    assert wf["ending_cash"] == pytest.approx(12_000)
    assert wf["inflows"] == pytest.approx(5_000)
    assert wf["outflows"] == pytest.approx(2_500)
    # The lines add up: start + in - out + transfers + other = end.
    assert wf["starting_cash"] + wf["inflows"] - wf["outflows"] + wf["transfers_and_funding"] + wf[
        "other_cash_movements"
    ] == pytest.approx(wf["ending_cash"])


def test_snapshots_on_the_first_are_exact(client: TestClient, db_engine):
    _bank_account(db_engine)
    _balance(db_engine, "2026-06-01", 10_000)
    _balance(db_engine, "2026-07-01", 11_000)

    wf = _waterfall(client, "2026-06")

    assert wf["bridge_available"] is True
    assert (wf["span_start"], wf["span_end"]) == ("2026-06-01", "2026-07-01")
    assert wf["span_basis"] == "exact"
    assert wf["boundary_exact"] is True
    assert wf["availability_message"] is None


def test_no_snapshot_before_the_month_says_why(client: TestClient, db_engine):
    _bank_account(db_engine)
    _balance(db_engine, "2026-06-15", 10_000)

    wf = _waterfall(client, "2026-06")

    assert wf["bridge_available"] is False
    assert wf["span_start"] is None
    assert wf["span_basis"] is None
    assert "on or before 2026-06-01" in wf["availability_message"]


def test_no_newer_snapshot_than_the_start_is_not_a_bridge(client: TestClient, db_engine):
    _bank_account(db_engine)
    _balance(db_engine, "2026-05-28", 10_000)

    wf = _waterfall(client, "2026-06")

    assert wf["bridge_available"] is False
    assert wf["span_start"] == wf["span_end"] == "2026-05-28"
    assert "No cash snapshot newer than 2026-05-28" in wf["availability_message"]


def test_a_start_older_than_the_loaded_transactions_is_refused(client: TestClient, db_engine):
    _bank_account(db_engine)
    _balance(db_engine, "2025-12-15", 10_000)
    _balance(db_engine, "2026-07-01", 11_000)

    wf = _waterfall(client, "2026-06")

    assert wf["bridge_available"] is False
    assert "more than 5 months earlier" in wf["availability_message"]


def test_card_statements_dont_count_as_cash_snapshots(client: TestClient, db_engine):
    """A card statement mid-month is a liability, not a cash date (#207): the end stays the bank's."""
    _bank_account(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES "
                "(951, 'Synthetic Card', 'DBS', 'CREDIT_CARD', 'SGD', 'SG', 1)"
            )
        )
    _balance(db_engine, "2026-05-31", 10_000)
    _balance(db_engine, "2026-06-30", 11_000)
    seed_canonical_account_balance_for_test(
        db_engine, account_id=951, as_of="2026-07-01", currency="SGD", balance_base=-500, balance_type="credit_balance"
    )

    wf = _waterfall(client, "2026-06")

    assert (wf["span_start"], wf["span_end"]) == ("2026-05-31", "2026-06-30")


def test_the_open_month_runs_to_the_newest_snapshot(client: TestClient, db_engine):
    """Mid-month (the issue's case): from the last snapshot before the 1st to the newest so far."""
    from datetime import date, timedelta

    today = date.today()
    month = today.strftime("%Y-%m")
    first = today.replace(day=1)
    before = first - timedelta(days=25)
    _bank_account(db_engine)
    _balance(db_engine, before.isoformat(), 10_000)
    _balance(db_engine, today.isoformat(), 10_500)

    wf = _waterfall(client, month)

    if today == first:
        pytest.skip("on the 1st the newest snapshot is the start anchor itself")
    assert wf["bridge_available"] is True
    assert (wf["span_start"], wf["span_end"]) == (before.isoformat(), today.isoformat())
    assert wf["span_basis"] == "nearest"
