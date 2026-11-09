"""#339, D-85: money between the user's own accounts is neither income nor spending.
Synthetic names, accounts and amounts only."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from datetime import datetime, timezone

from app.routers.spending import _cash_flow_bucket, _cash_flow_rows, _is_transfer_like_before_own
from app.valuation.own_transfers import mark_own_transfers, names_owner, owner_name_words
from tests.valuation_household import DBS_SAVINGS, SCENARIOS, USER_A, build_scenario, household_env

OWNER = owner_name_words("Alex Tan")


def _row(tid, account, day, kind, amount, merchant, category=None):
    return {
        "transaction_id": tid, "account_id": account, "ts": f"{day} 00:00:00+00:00", "type": kind,
        "amount": amount, "currency": "SGD", "merchant_counterparty": merchant, "notes": None,
        "raw_category": category, "resolved_category": category or "Uncategorized",
        "resolved_category_code": "", "resolved_parent_category_code": "",
    }


def _mark(rows):
    return {r["transaction_id"]: r for r in mark_own_transfers(rows, OWNER, _is_transfer_like_before_own)}


# ─── The holder's name ─────────────────────────────────────────────────────


def test_the_name_rule_needs_every_word_in_any_order_and_two_words():
    assert owner_name_words("Alex Tan") == {"alex", "tan"}
    assert owner_name_words("Alex") == frozenset()  # one word: too weak, off
    assert names_owner({"merchant_counterparty": "SI TO :ALEX TAN REF:SALARY"}, OWNER)
    assert names_owner({"merchant_counterparty": "GIRO SI SALARY OTHR TAN ALEX"}, OWNER)
    assert not names_owner({"merchant_counterparty": "ALEX MOTORS PTE LTD"}, OWNER)
    assert not names_owner({"merchant_counterparty": "SI TO :ALEX TAN"}, frozenset())


def test_a_one_sided_transfer_naming_the_holder_is_a_transfer():
    rows = _mark([_row(1, 10, "2026-11-02", "EXPENSE", -4600.0, "SI TO :ALEX TAN REF:SALARY", "Bank::GR")])
    assert rows[1]["own_transfer"] == "name"
    assert _cash_flow_bucket(rows[1]) is None


# ─── Pairs across the user's accounts ──────────────────────────────────────


def test_a_credit_typed_income_pairs_with_the_standing_instruction_out():
    rows = _mark([
        _row(1, 10, "2026-11-02", "EXPENSE", -4600.0, "SI TO :ALEX TAN REF:SALARY", "Bank::GR"),
        _row(2, 20, "2026-11-02", "INCOME", 4600.0, "Inward CR - GIRO", "Bank::Deposit"),
    ])
    assert rows[2]["own_transfer"] == "pair" and rows[2]["own_transfer_partner_id"] == 1
    assert rows[1]["own_transfer"] == "pair" and rows[1]["own_transfer_partner_id"] == 2
    assert _cash_flow_bucket(rows[2]) is None  # no longer income


def test_a_same_amount_pair_a_few_days_apart_on_two_accounts():
    rows = _mark([
        _row(1, 10, "2026-11-03", "TRANSFER", -1500.0, "FAST TRANSFER OUT"),
        _row(2, 30, "2026-11-05", "INCOME", 1500.0, "Inward credit"),
    ])
    assert rows[2]["own_transfer"] == "pair"
    assert _mark([
        _row(1, 10, "2026-11-03", "TRANSFER", -1500.0, "FAST TRANSFER OUT"),
        _row(2, 30, "2026-11-09", "INCOME", 1500.0, "Inward credit"),  # 6 days: too far
    ])[2]["own_transfer"] is None


def test_two_equally_near_candidates_are_ambiguous_and_nothing_pairs():
    rows = _mark([
        _row(1, 10, "2026-11-03", "TRANSFER", -1500.0, "FAST TRANSFER OUT"),
        _row(2, 20, "2026-11-03", "INCOME", 1500.0, "Inward credit"),
        _row(3, 30, "2026-11-03", "INCOME", 1500.0, "Inward credit"),
    ])
    assert rows[2]["own_transfer"] is None and rows[3]["own_transfer"] is None
    assert _cash_flow_bucket(rows[2]) == "income"


def test_an_employer_salary_is_never_the_other_side():
    rows = _mark([
        _row(1, 10, "2026-11-24", "TRANSFER", -6000.0, "FAST TRANSFER OUT"),
        _row(2, 20, "2026-11-24", "INCOME", 6000.0, "PAY ACME PTE LTD", "Salary"),
    ])
    assert rows[2]["own_transfer"] is None
    assert _cash_flow_bucket(rows[2]) == "income"


def test_the_same_account_never_pairs_with_itself():
    rows = _mark([
        _row(1, 10, "2026-11-03", "TRANSFER", -50.0, "FAST TRANSFER OUT"),
        _row(2, 10, "2026-11-03", "INCOME", 50.0, "Refund"),
    ])
    assert rows[2]["own_transfer"] is None


# ─── Read from the database, across the window's edge ──────────────────────


def _setup(db_engine):
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE users SET display_name = 'Alex Tan' WHERE id = 1"))
        conn.execute(text(
            "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES "
            "(9501, 'Synthetic Bank A', 'DBS', 'BANK', 'SGD', 'SG', 1), "
            "(9502, 'Synthetic Bank B', 'UOB', 'BANK', 'SGD', 'SG', 1)"
        ))
        for ts, acc, kind, amt, merchant, cat in (
            ("2026-10-31 00:00:00+00:00", 9501, "EXPENSE", -4600.0, "SI TO :ALEX TAN REF:SALARY", "Bank::GR"),
            ("2026-11-02 00:00:00+00:00", 9502, "INCOME", 4600.0, "Inward CR - GIRO SI SALARY OTHR TAN ALEX", "Bank::Deposit"),
            ("2026-11-24 00:00:00+00:00", 9501, "INCOME", 9000.0, "PAY ACME PTE LTD", "Salary"),
        ):
            conn.execute(
                text("INSERT INTO transactions (ts, account_id, type, amount, currency, merchant_counterparty, category) "
                     "VALUES (:ts, :a, :k, :amt, 'SGD', :m, :c)"),
                {"ts": ts, "a": acc, "k": kind, "amt": amt, "m": merchant, "c": cat},
            )


def test_cash_flow_rows_pair_across_the_month_edge_and_keep_the_salary(db_engine):
    _setup(db_engine)
    db = Session(bind=db_engine)
    try:
        rows = _cash_flow_rows(db, datetime(2026, 11, 1, tzinfo=timezone.utc), datetime(2026, 12, 1, tzinfo=timezone.utc), 1)
    finally:
        db.close()
    by_merchant = {r["merchant_counterparty"]: r for r in rows}
    assert "SI TO :ALEX TAN REF:SALARY" not in by_merchant  # October: outside the window
    credit = by_merchant["Inward CR - GIRO SI SALARY OTHR TAN ALEX"]
    assert credit["own_transfer"] == "pair" and str(credit["own_transfer_partner_day"]) == "2026-10-31"
    assert _cash_flow_bucket(credit) is None
    assert _cash_flow_bucket(by_merchant["PAY ACME PTE LTD"]) == "income"


# ─── The bridge ────────────────────────────────────────────────────────────


@pytest.fixture
def mid(client: TestClient, db_engine, monkeypatch):
    household_env(monkeypatch, SCENARIOS["mid"])
    build_scenario(db_engine, "mid")
    return client


def _bridge(client):
    resp = client.get("/dashboard/month-bridge?month=2026-03&base_currency=SGD")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_an_own_transfer_pair_changes_neither_income_nor_unexplained_and_still_adds_up(mid: TestClient, db_engine):
    before = _bridge(mid)
    with db_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) "
            "VALUES (9601, 'Second Bank', 'UOB', 'BANK', 'SGD', 'SG', :u)"
        ), {"u": USER_A})
        conn.execute(text(
            "INSERT INTO transactions (ts, account_id, type, amount, currency, merchant_counterparty, category) VALUES "
            "('2026-03-03 00:00:00+00:00', :dbs, 'EXPENSE', -2000, 'SGD', :out_text, 'Bank::GR'), "
            "('2026-03-03 00:00:00+00:00', 9601, 'INCOME', 2000, 'SGD', 'Inward CR - GIRO', 'Bank::Deposit')"
        ), {"dbs": DBS_SAVINGS, "out_text": "SI TO :SELF REF:SALARY"})
    after = _bridge(mid)

    def line(bridge, key):
        return next(l for l in bridge["lines"] if l["key"] == key)

    assert line(after, "cash_kept")["amount"] == pytest.approx(line(before, "cash_kept")["amount"], abs=0.01)
    assert after["unexplained"]["amount"] == pytest.approx(before["unexplained"]["amount"], abs=0.01)
    other = next(p for p in after["unexplained"]["parts"] if p["key"] == "other")
    assert not any("Second Bank" in (i["label"] or "") for i in other["items"])
    total = sum(l["amount"] for l in after["lines"]) + after["unexplained"]["amount"]
    assert total == pytest.approx(after["change"], abs=0.01)
