"""#299: the UOB card export repeats a statement period, and an undated "Previous Balance"
line used to overwrite the amount of the transaction above it. Synthetic rows only."""
from datetime import datetime

import pandas as pd

from app.ingestion.parsers.uob_credit_card_xls_v1 import _collapse_rows, _normalize_columns
from app.ingestion.uob_card_repair import plan_job

COLUMNS = [
    "Transaction Date",
    "Posting Date",
    "Description",
    "Foreign Currency Type",
    "Transaction Amount(Foreign)",
    "Local Currency Type",
    "Transaction Amount(Local)",
]


def _frame(rows):
    return pd.DataFrame(rows, columns=COLUMNS)


def _tx(day, desc, amount, posting=None):
    return [day, posting or day, desc, None, None, "SGD", amount]


def _pb(amount):
    return [None, None, "Previous Balance", None, None, "SGD", amount]


def _parse(rows):
    df = _frame(rows)
    return [r for r in _collapse_rows(df, _normalize_columns(COLUMNS)) if not r.is_balance_marker]


PERIOD_1 = [
    _tx("06 Nov 2026", "SHOP A", 33),
    _tx("02 Nov 2026", "GIRO PAYMENT", -524.21),
    _tx("01 Nov 2026", "SHOP B", 190),
    _tx("14 Oct 2026", "PHONE BILL", 36.9),
    _pb(271.06),
]
PERIOD_2 = [
    _tx("02 Oct 2026", "GIRO PAYMENT", -271.06),
    _tx("13 Sep 2026", "SHOP C", 28),
    _pb(214.28),
]


def test_previous_balance_no_longer_replaces_the_amount_above_it():
    rows = _parse(PERIOD_1 + PERIOD_2)
    amounts = {r.description: r.local_amount for r in rows}
    assert amounts["PHONE BILL"] == 36.9
    assert amounts["SHOP C"] == 28
    assert all("Previous Balance" not in r.description for r in rows)
    assert len(rows) == 6


def test_a_period_printed_twice_is_kept_once():
    rows = _parse(PERIOD_1 + PERIOD_1 + PERIOD_2)
    assert len(rows) == 6
    assert [r.description for r in rows].count("GIRO PAYMENT") == 2  # one per period


def test_the_repeat_the_real_export_has_head_and_tail_of_a_period_twice():
    # The real file: period 1, the first rows of period 2, then all of that again, then older periods.
    block = PERIOD_1 + PERIOD_2[:2]
    rows = _parse(block + block + [_pb(214.28), _tx("31 Jul 2026", "GIRO PAYMENT", -512.21)])
    assert len(rows) == 7


def test_two_identical_same_day_purchases_stay():
    rows = _parse([_tx("09 Oct 2026", "COFFEE", 6.8), _tx("09 Oct 2026", "COFFEE", 6.8), _pb(0)])
    assert len(rows) == 2


def test_two_identical_pairs_in_a_row_stay():
    pair = [_tx("09 Oct 2026", "COFFEE", 6.8), _tx("09 Oct 2026", "TOAST", 2.5)]
    assert len(_parse(pair + pair)) == 4  # under _MIN_REPEATED_RUN: could be real


def _stored(id_, day, merchant, amount):
    return {"id": id_, "ts": datetime.fromisoformat(day), "amount": amount, "currency": "SGD", "merchant_counterparty": merchant}


def _parsed(day, merchant, amount):
    return {"ts": datetime.fromisoformat(day), "amount": amount, "currency": "SGD", "merchant_counterparty": merchant,
            "type": "EXPENSE" if amount < 0 else "TRANSFER", "category": None, "notes": None}


def test_repair_plan_keeps_corrects_and_deletes_duplicates():
    stored = [
        _stored(1, "2026-11-02", "GIRO PAYMENT", 524.21),
        _stored(2, "2026-10-14", "PHONE BILL", -271.06),   # amount replaced by the previous balance
        _stored(3, "2026-09-13", "SHOP C", -28.0),
        _stored(4, "2026-11-02", "GIRO PAYMENT", 524.21),  # the repeated period
        _stored(5, "2026-10-14", "PHONE BILL", -271.06),
        _stored(6, "2026-09-13", "SHOP C", -214.28),       # second copy, wrong amount
    ]
    parsed = [
        _parsed("2026-11-02", "GIRO PAYMENT", 524.21),
        _parsed("2026-10-14", "PHONE BILL", -36.9),
        _parsed("2026-09-13", "SHOP C", -28.0),
    ]
    plan = plan_job(stored, parsed)
    assert sorted(plan.keep) == [1, 3]
    assert [(sid, tx["amount"]) for sid, tx in plan.fix] == [(2, -36.9)]
    assert sorted(plan.delete) == [(4, 1), (5, None), (6, None)]
    assert plan.unmatched_parsed == []


def test_repair_plan_on_clean_rows_changes_nothing():
    stored = [_stored(1, "2026-11-02", "GIRO PAYMENT", 524.21), _stored(2, "2026-10-09", "COFFEE", -6.8),
              _stored(3, "2026-10-09", "COFFEE", -6.8)]
    parsed = [_parsed("2026-11-02", "GIRO PAYMENT", 524.21), _parsed("2026-10-09", "COFFEE", -6.8),
              _parsed("2026-10-09", "COFFEE", -6.8)]
    plan = plan_job(stored, parsed)
    assert sorted(plan.keep) == [1, 2, 3] and not plan.fix and not plan.delete
