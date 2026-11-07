"""Card running balances and the statement check (#300, D-76).

- ``build_ledger``: a dated balance carried by the card's transactions; each
  statement checked against the transactions since the one before.
- The valuation (``_credit_card_liability_details``): the same running balance,
  re-based by each newer dated balance, a credit when overpaid.
- The month bridge: with a running balance, the card part of "unexplained" is 0.
- The UOB parser: every "Previous Balance" becomes a dated balance, and no longer
  overwrites the transaction above it.
- ``GET/POST /spending/credit-card-balances``.
All amounts and names are synthetic.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ingestion.card_balances import card_statement_balances
from app.ingestion.parsers.uob_credit_card_xls_v1 import parse_uob_credit_card_xls
from app.valuation.card_ledger import FLAG_THRESHOLD, build_ledger
from app.valuation.clock import _anchor_ts
from app.valuation.facts import _credit_card_liability_details
from tests.auth_helpers import signed_in_client
from tests.canonical_test_helpers import seed_canonical_account_balance_for_test
from tests.valuation_household import DBS_CARD, SCENARIOS, build_scenario, household_env

D = date
TODAY = D(2026, 11, 7)
CARD = 9301


def _ledger(balances, transactions, today=TODAY):
    return build_ledger(CARD, "SGD", balances, transactions, today=today)


# ─── The ledger ──────────────────────────────────────────────────────────────


def test_a_balance_is_carried_by_the_transactions_after_it():
    ledger = _ledger(
        [(D(2026, 10, 13), 500.0, "statement_balance")],
        [
            (D(2026, 10, 13), "EXPENSE", -999.0),  # on the statement's date: already in it
            (D(2026, 10, 20), "EXPENSE", -120.0),
            (D(2026, 10, 25), "FEE", -10.0),
            (D(2026, 10, 26), "INTEREST", -2.5),
        ],
    )
    assert ledger.method == "running"
    assert ledger.owed_now == pytest.approx(632.5)
    assert ledger.charges_since == pytest.approx(132.5)
    assert ledger.paid_since == 0.0
    assert ledger.paid_in_full is False
    assert ledger.fees_interest_ytd == pytest.approx(12.5)


def test_paying_last_months_bill_in_full():
    ledger = _ledger(
        [(D(2026, 10, 13), 524.21, "statement_balance")],
        [(D(2026, 11, 2), "TRANSFER", 524.21), (D(2026, 11, 3), "EXPENSE", -40.0)],
    )
    assert ledger.paid_in_full is True
    assert ledger.paid_since == pytest.approx(524.21)
    assert ledger.owed_now == pytest.approx(40.0)


def test_an_overpayment_is_a_credit_not_zero():
    ledger = _ledger(
        [(D(2026, 10, 13), 100.0, "statement_balance")],
        [(D(2026, 11, 2), "TRANSFER", 250.0)],
    )
    assert ledger.owed_now == pytest.approx(-150.0)
    assert ledger.paid_in_full is True


def test_every_statement_is_checked_against_the_transactions_between():
    """Three statements: one adds up, one says more is owed than the transactions
    (an overcharge, or a missing upload), one reads less (a charge counted twice)."""
    ledger = _ledger(
        [
            (D(2026, 7, 9), 512.21, "previous_balance"),
            (D(2026, 8, 13), 214.28, "previous_balance"),
            (D(2026, 9, 12), 300.00, "previous_balance"),  # 28.94 more than the transactions
            (D(2026, 10, 13), 500.00, "statement_balance"),  # 24.21 less
        ],
        [
            (D(2026, 7, 14), "EXPENSE", -214.28), (D(2026, 7, 31), "TRANSFER", 512.21),
            (D(2026, 8, 20), "EXPENSE", -271.06), (D(2026, 9, 2), "TRANSFER", 214.28),
            (D(2026, 9, 20), "EXPENSE", -524.21), (D(2026, 10, 2), "TRANSFER", 300.00),
        ],
    )
    first, second, third, newest = ledger.periods
    assert (first.expected, first.printed, first.difference, first.flagged) == (214.28, 214.28, 0.0, False)
    assert first.paid_in_full is True
    assert second.difference == pytest.approx(300.00 - 271.06) and second.flagged
    assert third.difference == pytest.approx(500.00 - 524.21) and third.flagged
    assert newest.to_date is None and newest.printed is None and not newest.flagged
    assert ledger.flagged_count == 2


def test_a_period_with_no_transactions_is_flagged_as_missing_data():
    ledger = _ledger(
        [(D(2026, 5, 12), 683.09, "statement_balance"), (D(2026, 7, 9), 512.21, "previous_balance")],
        [],
    )
    period = ledger.periods[0]
    assert period.transaction_count == 0
    assert period.flagged and period.difference == pytest.approx(512.21 - 683.09)


def test_a_difference_under_the_threshold_is_rounding():
    assert FLAG_THRESHOLD == 1.0
    ledger = _ledger(
        [(D(2026, 9, 12), 100.0, "x"), (D(2026, 10, 13), 150.6, "x")],
        [(D(2026, 9, 20), "EXPENSE", -150.0), (D(2026, 10, 2), "TRANSFER", 100.0)],
    )
    assert ledger.periods[0].difference == pytest.approx(0.6) and not ledger.periods[0].flagged


def test_a_newer_balance_rebases_the_running_balance():
    ledger = _ledger(
        [(D(2026, 9, 12), 100.0, "x"), (D(2026, 10, 13), 400.0, "x")],
        [(D(2026, 9, 20), "EXPENSE", -150.0), (D(2026, 10, 20), "EXPENSE", -60.0)],
    )
    assert ledger.last_balance == 400.0
    assert ledger.owed_now == pytest.approx(460.0)  # the newest balance, not 100 + all spend


def test_a_card_with_no_dated_balance_estimates_from_this_months_transactions():
    ledger = _ledger([], [(D(2026, 10, 20), "EXPENSE", -80.0), (D(2026, 11, 3), "EXPENSE", -25.0)])
    assert ledger.method == "transactions"
    assert ledger.owed_now == pytest.approx(25.0)
    assert ledger.periods == []


# ─── The valuation ───────────────────────────────────────────────────────────


@pytest.fixture()
def sgd_only(monkeypatch):
    monkeypatch.setattr("app.valuation.fx.get_rates", lambda *_a, **_k: {"SGD": 1.0})


def _card(db_engine) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES "
                "(:id, 'Synthetic Card', 'UOB', 'CREDIT_CARD', 'SGD', 'SG', 1)"
            ),
            {"id": CARD},
        )


def _tx(db_engine, ts: str, kind: str, amount: float) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO transactions (ts, account_id, type, amount, currency) VALUES (:ts, :a, :k, :amt, 'SGD')"),
            {"ts": ts, "a": CARD, "k": kind, "amt": amount},
        )


def _owed(db_engine, month: datetime) -> dict:
    db = Session(bind=db_engine)
    try:
        return _credit_card_liability_details(db, _anchor_ts(month), "SGD", 1)[0]
    finally:
        db.close()


def test_the_valuation_is_the_running_balance_rebased_by_each_statement(db_engine, sgd_only):
    _card(db_engine)
    seed_canonical_account_balance_for_test(
        db_engine, account_id=CARD, as_of="2026-09-12", currency="SGD", balance_base=-271.06, balance_type="credit_balance"
    )
    _tx(db_engine, "2026-09-20 00:00:00+00:00", "EXPENSE", -524.21)
    _tx(db_engine, "2026-10-02 00:00:00+00:00", "TRANSFER", 271.06)
    # 30 Sep month-end (anchor 1 Oct): 271.06 + 524.21
    sep = _owed(db_engine, datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert sep["method"] == "running" and sep["value"] == pytest.approx(795.27)

    seed_canonical_account_balance_for_test(
        db_engine, account_id=CARD, as_of="2026-10-13", currency="SGD", balance_base=-524.21, balance_type="credit_balance"
    )
    _tx(db_engine, "2026-10-20 00:00:00+00:00", "EXPENSE", -60.0)
    # 31 Oct month-end (anchor 1 Nov): re-based on the 13 Oct statement, plus 60.
    octo = _owed(db_engine, datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert octo["as_of_date"] == D(2026, 10, 13)
    assert octo["value"] == pytest.approx(584.21)
    # September is unchanged by October's statement.
    assert _owed(db_engine, datetime(2026, 9, 1, tzinfo=timezone.utc))["value"] == pytest.approx(795.27)


# ─── The month bridge ────────────────────────────────────────────────────────


def test_with_a_running_balance_the_bridge_explains_the_card(client: TestClient, db_engine, monkeypatch):
    """The household's card spends 1,210.40 + 95 and pays 1,000 in February, then
    970.55 in March. With a dated balance before them, the card's change is its
    transactions: nothing about it is unexplained (before #300 it was 305.40)."""
    household_env(monkeypatch, SCENARIOS["mid"])
    build_scenario(db_engine, "mid")
    seed_canonical_account_balance_for_test(
        db_engine, account_id=DBS_CARD, as_of="2026-01-31", currency="SGD", balance_base=-960.0, balance_type="credit_balance"
    )
    bridge = client.get("/dashboard/month-bridge?month=2026-03&base_currency=SGD&limit=20").json()
    parts = {part["key"]: part["amount"] for part in bridge["unexplained"]["parts"]}
    assert parts.get("card_balances", 0.0) == pytest.approx(0.0, abs=0.01)
    assert bridge["liabilities_change"] == pytest.approx(660.0 + 310.55, abs=0.01)


# ─── The UOB parser ──────────────────────────────────────────────────────────

HEADER = ["Transaction Date", "Posting Date", "Description", "Foreign Currency Type",
          "Transaction Amount(Foreign)", "Local Currency Type", "Transaction Amount(Local)"]


def _uob_xlsx(path: Path, statement_date: str, statement_balance: float, rows: list[list]) -> Path:
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "history"
    for line in (
        ["United Overseas Bank Limited."], ["Account Statement Details"], [],
        ["Account Number:", "4000000000000002"], ["Account Type:", "SYNTHETIC CARD"],
        ["Statement Date:", statement_date], ["Statement Balance:", statement_balance, "SGD"], [],
        HEADER, *rows,
    ):
        ws.append(line)
    wb.save(path)
    return path


def _row(day: str, description: str, amount: float) -> list:
    return [day, day, description, None, None, "SGD", amount]


def _previous(amount: float) -> list:
    return [None, None, "Previous Balance", None, None, "SGD", amount]


def test_a_uob_history_export_states_every_period_and_no_amount_is_overwritten(tmp_path):
    """Newest first: the unbilled period, then each statement period with its
    Previous Balance on top of it (older rows). The header's balance opens the
    unbilled period."""
    path = _uob_xlsx(tmp_path / "history.xlsx", "10 Jul 2026 To 06 Nov 2026", 524.21, [
        _row("06 Nov 2026", "SYNTHETIC GROCER", 33),
        _row("02 Nov 2026", "GIRO PAYMENT", -524.21),
        _row("14 Oct 2026", "SYNTHETIC TELCO", 36.9),
        _previous(271.06),
        _row("09 Oct 2026", "SYNTHETIC CAFE", 6.8),
        _row("02 Oct 2026", "GIRO PAYMENT", -271.06),
        _row("13 Sep 2026", "SYNTHETIC TONIC", 28),
        _previous(214.28),
        _row("14 Aug 2026", "SYNTHETIC HOUSEHOLD", 3),
    ])
    result = parse_uob_credit_card_xls(str(path))
    amounts = {tx["merchant_counterparty"]: tx["amount"] for tx in result.transactions}
    # Before #300 each Previous Balance overwrote the row above it (36.90 read as 271.06).
    assert amounts["SYNTHETIC TELCO"] == -36.9
    assert amounts["SYNTHETIC TONIC"] == -28.0
    assert len(result.transactions) == 7
    assert result.parser_meta["statement_balances"] == [
        {"as_of_date": "2026-08-13", "owed": 214.28, "source": "previous_balance"},
        {"as_of_date": "2026-09-12", "owed": 271.06, "source": "previous_balance"},
        {"as_of_date": "2026-10-13", "owed": 524.21, "source": "statement_balance"},
    ]
    statements = card_statement_balances("uob_credit_card_xls_v1", result.parser_meta)
    assert [(s.as_of_date, s.balance) for s in statements] == [
        (D(2026, 8, 13), -214.28), (D(2026, 9, 12), -271.06), (D(2026, 10, 13), -524.21),
    ]


def test_a_uob_statement_dates_its_balance_on_the_statement_date(tmp_path):
    path = _uob_xlsx(tmp_path / "statement.xlsx", "12 May 2026", 683.09, [
        _previous(280.37),
        _row("09 May 2026", "SYNTHETIC CAFE", 403.09),
        _row("30 Apr 2026", "GIRO PAYMENT", -280.37),
        _row("13 Apr 2026", "SYNTHETIC GROCER", 280),
    ])
    meta = parse_uob_credit_card_xls(str(path)).parser_meta
    assert meta["statement_balances"] == [
        {"as_of_date": "2026-04-12", "owed": 280.37, "source": "previous_balance"},
        {"as_of_date": "2026-05-12", "owed": 683.09, "source": "statement_balance"},
    ]


# ─── The API ─────────────────────────────────────────────────────────────────


def test_balances_endpoint_and_a_typed_in_statement(client: TestClient, db_engine, monkeypatch, sgd_only):
    monkeypatch.setattr("app.routers.spending.get_rates", lambda *_a, **_k: {"SGD": 1.0})
    _card(db_engine)
    _tx(db_engine, "2026-10-20 00:00:00+00:00", "EXPENSE", -60.0)
    body = client.get("/spending/credit-card-balances?base_currency=SGD").json()
    card = next(c for c in body["cards"] if c["account_id"] == CARD)
    assert card["method"] == "transactions" and card["periods"] == []

    resp = client.post(f"/spending/credit-card-balances/{CARD}", json={"as_of_date": "2026-10-13", "owed": 500.0})
    assert resp.status_code == 200, resp.text
    card = next(c for c in resp.json()["cards"] if c["account_id"] == CARD)
    assert card["method"] == "running"
    assert card["last_balance"] == 500.0 and card["last_balance_source"] == "manual"
    assert card["owed_now"] == pytest.approx(560.0)

    future = client.post(f"/spending/credit-card-balances/{CARD}", json={"as_of_date": "2099-01-01", "owed": 1.0})
    assert future.status_code == 422


def test_another_users_card_is_not_found(client: TestClient, db_engine):
    _card(db_engine)
    other = signed_in_client(db_engine, 9302)
    resp = other.post(f"/spending/credit-card-balances/{CARD}", json={"as_of_date": "2026-10-13", "owed": 1.0})
    assert resp.status_code == 404
    assert all(c["account_id"] != CARD for c in other.get("/spending/credit-card-balances").json()["cards"])
