"""Card payment due dates (#352, D-91). All names and amounts are synthetic.

- ``due_state``: upcoming, due within 5 days, overdue, paid (card or bank-side payment),
  minimum paid; the statement's own balance when no amount was given.
- A parser's ``payment_due`` is stored as a statement due; a typed-in due can't replace it.
- ``POST /spending/credit-card-dues`` and the due fields of ``credit-card-balances``.
- A card with no printed or configured due date has none (``due_date`` null), never day 1.
- The Inbox: a due-soon and an overdue item, cleared by a payment.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser
from app.services import inbox as ib
from app.valuation.card_dues import DueRecord, due_state, load_due_records, write_due, write_statement_due
from app.valuation.card_ledger import BANK_PAYMENT, build_ledger
from tests.auth_helpers import signed_in_client

D = date
CARD = 9351
TODAY = D(2026, 11, 20)


def _record(due=D(2026, 11, 27), amount=500.0, minimum=None, statement=D(2026, 11, 2)):
    return DueRecord(CARD, statement, due, amount, minimum, "manual")


def _ledger(transactions, balances=((D(2026, 11, 2), 500.0, "manual"),)):
    return build_ledger(CARD, "SGD", list(balances), transactions, today=TODAY)


# ─── due_state ───────────────────────────────────────────────────────────────


def test_a_due_more_than_five_days_away_is_upcoming():
    state = due_state(_record(due=D(2026, 11, 27)), _ledger([]), today=TODAY)
    assert (state.status, state.days_until, state.remaining) == ("upcoming", 7, 500.0)


def test_a_due_within_five_days_is_due_soon_and_overdue_after():
    assert due_state(_record(due=D(2026, 11, 25)), _ledger([]), today=TODAY).status == "due_soon"
    assert due_state(_record(due=D(2026, 11, 20)), _ledger([]), today=TODAY).status == "due_soon"
    late = due_state(_record(due=D(2026, 11, 19)), _ledger([]), today=TODAY)
    assert (late.status, late.days_until) == ("overdue", -1)


def test_payments_after_the_statement_clear_it_including_bank_side_ones():
    on_card = due_state(_record(due=D(2026, 11, 19)), _ledger([(D(2026, 11, 10), "TRANSFER", 500.0)]), today=TODAY)
    assert (on_card.status, on_card.paid, on_card.remaining) == ("paid", 500.0, 0.0)
    from_bank = due_state(_record(due=D(2026, 11, 19)), _ledger([(D(2026, 11, 10), BANK_PAYMENT, 500.0)]), today=TODAY)
    assert from_bank.status == "paid"
    # A payment on or before the statement date paid an earlier bill, not this one.
    before = due_state(_record(due=D(2026, 11, 19)), _ledger([(D(2026, 11, 2), "TRANSFER", 500.0)]), today=TODAY)
    assert before.status == "overdue"


def test_only_the_minimum_paid_is_still_overdue_but_says_so():
    state = due_state(
        _record(due=D(2026, 11, 19), minimum=50.0), _ledger([(D(2026, 11, 15), "TRANSFER", 60.0)]), today=TODAY
    )
    assert (state.status, state.minimum_paid, state.remaining) == ("overdue", True, 440.0)


def test_without_an_amount_the_statements_own_balance_is_due():
    state = due_state(_record(amount=None), _ledger([], balances=[(D(2026, 11, 2), 321.5, "statement_balance")]), today=TODAY)
    assert state.amount_due == 321.5


# ─── Storage ─────────────────────────────────────────────────────────────────


def _card(db_engine, user_id: int = 1) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES "
                "(:id, 'Synthetic Card', 'CITI', 'CREDIT_CARD', 'SGD', 'SG', :u)"
            ),
            {"id": CARD, "u": user_id},
        )


def _tx(db_engine, ts: str, kind: str, amount: float) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO transactions (ts, account_id, type, amount, currency) VALUES (:ts, :a, :k, :amt, 'SGD')"),
            {"ts": ts, "a": CARD, "k": kind, "amt": amount},
        )


def test_a_parsers_payment_due_is_stored_and_a_typed_in_one_cant_replace_it(db_engine):
    _card(db_engine)
    db = Session(bind=db_engine)
    try:
        assert write_statement_due(db, account_id=CARD, import_job_id=None, parser_meta={"statement_balance": 1}) is False
        assert write_statement_due(
            db,
            account_id=CARD,
            import_job_id=None,
            parser_meta={"payment_due": {"statement_date": "2026-11-02", "due_date": "2026-11-27",
                                         "amount_due": 500, "minimum_due": 50}},
        )
        db.commit()
        record = load_due_records(db, 1, today=TODAY)[CARD]
        assert (record.due_date, record.amount_due, record.minimum_due, record.source) == (
            D(2026, 11, 27), 500.0, 50.0, "statement"
        )
        with pytest.raises(ValueError):
            write_due(db, account_id=CARD, statement_date=D(2026, 11, 2), due_date=D(2026, 11, 28),
                      amount_due=None, minimum_due=None, source="manual")
        with pytest.raises(ValueError):
            write_due(db, account_id=CARD, statement_date=D(2026, 11, 2), due_date=D(2026, 11, 1),
                      amount_due=None, minimum_due=None, source="statement")
    finally:
        db.rollback()
        db.close()


def test_the_newest_statement_up_to_today_is_the_current_due(db_engine):
    _card(db_engine)
    db = Session(bind=db_engine)
    try:
        for statement, due in ((D(2026, 10, 2), D(2026, 10, 27)), (D(2026, 11, 2), D(2026, 11, 27)),
                               (D(2026, 12, 2), D(2026, 12, 27))):
            write_due(db, account_id=CARD, statement_date=statement, due_date=due, amount_due=10,
                      minimum_due=None, source="manual")
        db.commit()
        assert load_due_records(db, 1, today=TODAY)[CARD].due_date == D(2026, 11, 27)
        assert load_due_records(db, 9352, today=TODAY) == {}  # another user's card
    finally:
        db.close()


# ─── The API ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def today(monkeypatch):
    monkeypatch.setattr("app.routers.spending._app_today", lambda: TODAY)
    monkeypatch.setattr("app.routers.spending.get_rates", lambda *_a, **_k: {"SGD": 1.0})
    monkeypatch.setattr("app.valuation.fx.get_rates", lambda *_a, **_k: {"SGD": 1.0})
    return TODAY


def _card_item(body: dict) -> dict:
    return next(c for c in body["cards"] if c["account_id"] == CARD)


def test_typing_in_a_due_date_and_paying_it(client: TestClient, db_engine, today):
    _card(db_engine)
    card = _card_item(client.get("/spending/credit-card-balances").json())
    assert card["due_date"] is None and card["due_source"] is None

    resp = client.post(f"/spending/credit-card-balances/{CARD}",
                       json={"as_of_date": "2026-11-02", "owed": 500.0, "due_date": "2026-11-23", "minimum_due": 50})
    assert resp.status_code == 200, resp.text
    card = _card_item(resp.json())
    assert (card["due_date"], card["due_source"], card["due_status"]) == ("2026-11-23", "manual", "due_soon")
    assert (card["amount_due"], card["minimum_due"], card["remaining_due"]) == (500.0, 50.0, 500.0)
    assert card["due_statement_date"] == "2026-11-02"

    _tx(db_engine, "2026-11-15 00:00:00+00:00", "TRANSFER", 500.0)
    card = _card_item(client.get("/spending/credit-card-balances").json())
    assert (card["due_status"], card["paid_toward_due"], card["remaining_due"]) == ("paid", 500.0, 0.0)


def test_the_due_endpoint_validates_and_scopes(client: TestClient, db_engine, today):
    _card(db_engine)
    ok = client.post(f"/spending/credit-card-dues/{CARD}",
                     json={"statement_date": "2026-11-02", "due_date": "2026-11-27", "amount_due": 80})
    assert ok.status_code == 200, ok.text
    card = _card_item(ok.json())
    assert (card["due_date"], card["due_status"], card["amount_due"]) == ("2026-11-27", "upcoming", 80.0)

    before = client.post(f"/spending/credit-card-dues/{CARD}", json={"statement_date": "2026-11-02", "due_date": "2026-11-01"})
    assert before.status_code == 422
    future = client.post(f"/spending/credit-card-dues/{CARD}", json={"statement_date": "2099-01-01", "due_date": "2099-01-20"})
    assert future.status_code == 422
    other = signed_in_client(db_engine, 9353)
    assert other.post(f"/spending/credit-card-dues/{CARD}",
                      json={"statement_date": "2026-11-02", "due_date": "2026-11-27"}).status_code == 404


def test_a_card_with_no_known_due_date_has_none_not_day_one(client: TestClient, db_engine, today):
    _card(db_engine)
    analytics = client.get("/spending/credit-card-analytics?month=2026-11&base_currency=SGD").json()
    card = _card_item(analytics)
    assert card["due_date"] is None and card["due_source"] is None
    summary = _card_item(client.get("/spending/credit-cards?month=2026-11&base_currency=SGD").json())
    assert summary["due_date"] is None

    client.post(f"/spending/credit-card-dues/{CARD}", json={"statement_date": "2026-11-02", "due_date": "2026-11-27"})
    card = _card_item(client.get("/spending/credit-card-analytics?month=2026-11&base_currency=SGD").json())
    assert (card["due_date"], card["due_source"]) == ("2026-11-27", "manual")


# ─── The Inbox ───────────────────────────────────────────────────────────────


def test_the_inbox_reminds_before_and_after_the_due_date_until_paid(db_engine, monkeypatch):
    monkeypatch.setattr("app.valuation.fx.get_rates", lambda *_a, **_k: {"SGD": 1.0})
    _card(db_engine)
    db = Session(bind=db_engine)
    user = CurrentUser(id=1, username="hitesh-synthetic")
    try:
        write_due(db, account_id=CARD, statement_date=D(2026, 11, 2), due_date=D(2026, 11, 23),
                  amount_due=500, minimum_due=50, source="manual")
        db.commit()

        assert ib._card_due_items(db, user, D(2026, 11, 10)) == ([], False)  # 13 days away: no reminder yet

        items, all_paid = ib._card_due_items(db, user, TODAY)
        assert not all_paid
        assert [(i.kind, i.severity, i.title) for i in items] == [
            ("card_due_soon", "medium", "Synthetic Card: SGD 500.00 due 23 Nov (3 days)")
        ]
        assert (items[0].action.route, items[0].action.params) == ("/liabilities", {"card": str(CARD)})

        items, _ = ib._card_due_items(db, user, D(2026, 11, 25))
        assert [(i.kind, i.severity, i.title) for i in items] == [
            ("card_overdue", "high", "Synthetic Card: SGD 500.00 overdue since 23 Nov")
        ]

        _tx(db_engine, "2026-11-24 00:00:00+00:00", "TRANSFER", 60.0)  # the minimum, a day late
        items, _ = ib._card_due_items(db, user, D(2026, 11, 25))
        assert items[0].title == "Synthetic Card: SGD 440.00 overdue since 23 Nov"
        assert "minimum paid" in (items[0].detail or "")

        _tx(db_engine, "2026-11-25 00:00:00+00:00", "TRANSFER", 440.0)
        assert ib._card_due_items(db, user, D(2026, 11, 25)) == ([], True)
    finally:
        db.close()
