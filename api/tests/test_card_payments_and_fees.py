"""#308, D-77: card payments seen from the bank side, same-day ordering in the statement
check, and currency conversion fees as fees. Synthetic card numbers (Luhn-valid test
numbers) and amounts only."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ingestion.card_fee_repair import repair_card_fees, stored_form
from app.ingestion.card_fees import is_conversion_fee
from app.ingestion.parsers.citi_credit_card_csv_v1 import _classify as citi_classify
from app.ingestion.parsers.dbs_credit_card_csv_v1 import _classify as dbs_classify
from app.ingestion.parsers.uob_credit_card_xls_v1 import _classify as uob_classify
from app.ingestion.runner import _source_fingerprint
from app.routers.spending import _cash_flow_bucket
from app.valuation.card_ledger import BANK_PAYMENT, build_ledger
from app.valuation.card_payments import (
    BankCardPayment,
    card_last4s,
    card_numbers_in,
    missing_bank_payments,
    paid_card,
    payments_missing_from_card,
)

D = date
CARD_NO = "4000000000000002"  # a Luhn-valid test number
CARD = 9401
BANK = 9402


# ─── Recognising a card number on a bank line ──────────────────────────────


def test_a_full_card_number_on_a_bank_line_is_found():
    assert card_numbers_in(f"BILL CARDX-{CARD_NO} : I-BANK REF: 12345678901234567890") == ["0002"]
    assert card_numbers_in("GIRO 4000 0000 0000 0002 COLL") == ["0002"]


def test_a_masked_card_number_is_matched_on_its_last_4():
    assert card_numbers_in("Inward DR - GIRO **** ********0002 COLL") == ["0002"]
    assert card_numbers_in("payment XXXX-XXXX-XXXX-0002") == ["0002"]


def test_references_and_invalid_numbers_are_not_cards():
    assert card_numbers_in("FAST REF 12345678901234567890") == []  # 20 digits: a reference
    assert card_numbers_in("PIB4000000000000003") == []  # 16 digits that fail Luhn
    assert card_numbers_in("TRANSIT 1234") == []


def test_paid_card_needs_a_bank_outflow_and_one_card():
    last4s = {"0002": CARD}
    outflow = {"account_type": "BANK", "amount": -100.0, "merchant_counterparty": f"BILL X-{CARD_NO}", "notes": None}
    assert paid_card(outflow, last4s) == CARD
    assert paid_card({**outflow, "amount": 100.0}, last4s) is None  # money in
    assert paid_card({**outflow, "account_type": "CREDIT_CARD"}, last4s) is None
    assert paid_card(outflow, {}) is None


def test_a_payment_to_your_own_card_is_not_spending():
    row = {"type": "EXPENSE", "amount": -500.0, "merchant_counterparty": f"BILL X-{CARD_NO}", "notes": "",
           "raw_category": "Bank::ADV", "own_card_payment": CARD}
    assert _cash_flow_bucket(row) is None
    assert _cash_flow_bucket({**row, "own_card_payment": None}) == "expense"


# ─── Which bank payments the card file is missing ──────────────────────────


def _pay(tx_id, day, amount, card=CARD):
    return BankCardPayment(bank_transaction_id=tx_id, card_account_id=card, day=day, amount=amount, currency="SGD")


def test_a_bank_payment_the_card_file_lists_is_not_added_again():
    bank = [_pay(1, D(2026, 9, 21), 592.41)]
    assert payments_missing_from_card(bank, [(CARD, D(2026, 9, 21), 592.41)]) == []
    assert payments_missing_from_card(bank, [(CARD, D(2026, 9, 24), 592.41)]) == []  # a few days apart
    assert payments_missing_from_card(bank, [(CARD, D(2026, 10, 5), 592.41)]) == bank  # too far apart
    assert payments_missing_from_card(bank, [(CARD, D(2026, 9, 21), 592.40)]) == bank  # another amount
    assert payments_missing_from_card(bank, [(CARD + 1, D(2026, 9, 21), 592.41)]) == bank  # another card


def test_two_same_amount_bank_payments_need_two_card_payments():
    bank = [_pay(1, D(2026, 9, 1), 100.0), _pay(2, D(2026, 9, 3), 100.0)]
    missing = payments_missing_from_card(bank, [(CARD, D(2026, 9, 3), 100.0)])
    assert [p.bank_transaction_id for p in missing] == [1]


# ─── The statement check ───────────────────────────────────────────────────


def test_a_payment_found_only_at_the_bank_closes_the_statement():
    ledger = build_ledger(
        CARD, "SGD",
        [(D(2026, 8, 30), 782.34, "available_limit"), (D(2026, 10, 2), 0.0, "available_limit")],
        [(D(2026, 9, 1), "EXPENSE", -190.0), (D(2026, 9, 21), BANK_PAYMENT, 972.34)],
        today=D(2026, 11, 8),
    )
    period = ledger.periods[0]
    assert period.difference == pytest.approx(0.0) and not period.flagged
    assert period.bank_payments == pytest.approx(972.34)
    assert period.transaction_count == 1  # the card's own transactions only


def test_a_payment_dated_on_the_balance_day_moves_to_the_next_period_when_that_adds_up():
    # The balance read on 30 Aug didn't include that day's 514.63 payment yet.
    ledger = build_ledger(
        CARD, "SGD",
        [(D(2026, 8, 9), 514.63, "available_limit"), (D(2026, 8, 30), 782.34, "available_limit"),
         (D(2026, 10, 2), 0.0, "available_limit")],
        [(D(2026, 8, 15), "EXPENSE", -267.71), (D(2026, 8, 30), "TRANSFER", 514.63),
         (D(2026, 9, 21), BANK_PAYMENT, 267.71)],
        today=D(2026, 11, 8),
    )
    first, second = ledger.periods[0], ledger.periods[1]
    assert first.difference == pytest.approx(0.0)
    assert first.note and "next period" in first.note
    assert second.payments == pytest.approx(514.63 + 267.71)
    assert second.difference == pytest.approx(0.0)


def test_same_day_transactions_stay_when_moving_them_doesnt_help():
    ledger = build_ledger(
        CARD, "SGD",
        [(D(2026, 8, 9), 100.0, "statement_balance"), (D(2026, 8, 30), 150.0, "statement_balance")],
        [(D(2026, 8, 30), "EXPENSE", -50.0)],
        today=D(2026, 11, 8),
    )
    assert ledger.periods[0].difference == pytest.approx(0.0) and ledger.periods[0].note is None


def test_charges_after_the_last_card_transaction_are_named_as_not_uploaded():
    ledger = build_ledger(
        CARD, "SGD",
        [(D(2026, 8, 30), 0.0, "available_limit"), (D(2026, 10, 2), 242.44, "available_limit")],
        [(D(2026, 9, 13), "EXPENSE", -10.0)],
        today=D(2026, 11, 8),
    )
    period = ledger.periods[0]
    assert period.flagged and period.difference == pytest.approx(232.44)
    assert period.note and "after 2026-09-13" in period.note


def test_a_period_with_no_card_transactions_says_its_charges_are_missing():
    ledger = build_ledger(
        CARD, "SGD",
        [(D(2026, 5, 12), 683.09, "statement_balance"), (D(2026, 7, 9), 512.21, "statement_balance")],
        [(D(2026, 5, 29), BANK_PAYMENT, 683.09)],
        today=D(2026, 11, 8),
    )
    period = ledger.periods[0]
    assert period.flagged and period.transaction_count == 0
    assert period.note and "No card transactions uploaded between" in period.note


# ─── From the database ─────────────────────────────────────────────────────


def _accounts(db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES "
                "(:card, 'Synthetic Card', 'DBS', 'CREDIT_CARD', 'SGD', 'SG', 1), "
                "(:bank, 'Synthetic Bank', 'DBS', 'BANK', 'SGD', 'SG', 1)"
            ),
            {"card": CARD, "bank": BANK},
        )


def _tx(db_engine, account, ts, kind, amount, merchant, notes=None, fp=None):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO transactions (ts, account_id, type, amount, currency, merchant_counterparty, notes, source_fingerprint) "
                "VALUES (:ts, :a, :k, :amt, 'SGD', :m, :n, :fp)"
            ),
            {"ts": ts, "a": account, "k": kind, "amt": amount, "m": merchant, "n": notes, "fp": fp},
        )


def test_bank_payments_to_your_card_are_found_and_deduplicated(db_engine):
    _accounts(db_engine)
    _tx(db_engine, CARD, "2026-09-01 00:00:00+00:00", "EXPENSE", -50.0, "SHOP", "card_last4=0002")
    _tx(db_engine, CARD, "2026-08-30 00:00:00+00:00", "TRANSFER", 514.63, "BILL PAYMENT", "card_last4=0002")
    _tx(db_engine, BANK, "2026-08-30 00:00:00+00:00", "EXPENSE", -514.63, f"BILL X-{CARD_NO} : REF 1")
    _tx(db_engine, BANK, "2026-09-21 00:00:00+00:00", "EXPENSE", -592.41, f"BILL X-{CARD_NO} : REF 2")
    _tx(db_engine, BANK, "2026-09-22 00:00:00+00:00", "EXPENSE", -30.0, "FAIRPRICE")
    db = Session(bind=db_engine)
    try:
        assert card_last4s(db, 1) == {"0002": CARD}
        missing = missing_bank_payments(db, 1)
    finally:
        db.close()
    assert [(p.card_account_id, p.day, p.amount) for p in missing] == [(CARD, D(2026, 9, 21), 592.41)]


# ─── Conversion fees ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "line",
    ["CCY CONVERSION FEE    SGD          30.00", "FOREIGN TRANSACTION FEE", "FX FEE", "CROSS BORDER FEE", "OVERSEAS CHARGE"],
)
def test_conversion_fee_lines(line):
    assert is_conversion_fee(line)


@pytest.mark.parametrize("line", ["FAIRPRICE XTRA", "LATE CHARGE FEE", "ANNUAL FEE", "FOREIGN BOOKS SHOP", None])
def test_lines_that_are_not_conversion_fees(line):
    assert not is_conversion_fee(line)


def test_every_card_parser_types_a_conversion_fee_as_a_fee():
    assert citi_classify("CCY CONVERSION FEE    SGD          30.00", -0.30)[0] == "FEE"
    assert uob_classify("FOREIGN TRANSACTION FEE", -1.20)[0] == "FEE"
    assert dbs_classify("CCY CONVERSION FEE", "PURCHASE", -0.50)[0] == "FEE"
    assert citi_classify("FAIRPRICE XTRA", -20.0)[0] == "EXPENSE"


def test_the_fee_repair_retypes_stored_rows_and_keeps_them_deduplicating(db_engine):
    _accounts(db_engine)
    ts = datetime(2026, 8, 7, tzinfo=timezone.utc)
    key = {"ts": ts, "type": "EXPENSE", "amount": -0.30, "currency": "SGD", "merchant_counterparty": "CCY CONVERSION FEE"}
    fp = _source_fingerprint(CARD, key, 1)
    _tx(db_engine, CARD, "2026-08-07 00:00:00+00:00", "EXPENSE", -0.30, "CCY CONVERSION FEE", f"card_number=****0002 | fp:{fp}", fp)
    _tx(db_engine, CARD, "2026-08-08 00:00:00+00:00", "EXPENSE", -20.0, "FAIRPRICE", None, None)

    db = Session(bind=db_engine)
    try:
        dry = repair_card_fees(db, apply=False)
        assert dry.candidates == 1 and dry.retyped == 1 and not dry.unreproducible
        assert db.execute(text("SELECT type FROM transactions WHERE merchant_counterparty = 'CCY CONVERSION FEE'")).scalar() == "EXPENSE"

        repair_card_fees(db, apply=True)
        row = dict(db.execute(text(
            "SELECT id, account_id, ts, type, amount, currency, merchant_counterparty, notes, source_fingerprint, category "
            "FROM transactions WHERE merchant_counterparty = 'CCY CONVERSION FEE'"
        )).mappings().one())
        assert row["type"] == "FEE" and row["category"] == "CreditCard::Fee"
        new_fp = _source_fingerprint(CARD, {**key, "type": "FEE"}, 1)
        assert row["source_fingerprint"] == new_fp and row["notes"].endswith(f"fp:{new_fp}")
        assert stored_form(row) is not None  # a fresh upload would compute the same fingerprint
        assert db.execute(text("SELECT type FROM transactions WHERE merchant_counterparty = 'FAIRPRICE'")).scalar() == "EXPENSE"
        assert repair_card_fees(db, apply=False).candidates == 0  # idempotent
    finally:
        db.close()
