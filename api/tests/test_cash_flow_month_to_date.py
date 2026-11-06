"""Cash Flow month to date (#243, D-63): the open month is compared with the
previous month up to the same day, clamped to that month's length; a past
month stays whole month vs whole month. "Today" and every transaction's date
follow the user's home timezone (D-49). Synthetic users and data only."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.routers.spending import _comparison_window, _parse_month
from tests.auth_helpers import ensure_user
from tests.valuation_household import NEW_YORK, as_user, freeze_clock, set_user_timezone

SINGAPORE = "Asia/Singapore"
NY_USER = 1  # the `client` fixture's user
SG_USER = 2
TOL = 0.01

# 10:00 on 18 Mar in Singapore = 02:00Z = 22:00 on 17 Mar in New York (EDT).
MID_MARCH = datetime(2026, 3, 18, 2, 0, tzinfo=timezone.utc)

# SGD rows on a bank account (base SGD: no FX). (ts, amount, type, category)
ROWS = [
    ("2026-02-02 09:00:00+00:00", -2000.0, "EXPENSE", "Rent"),
    ("2026-02-03 09:00:00+00:00", 5000.0, "INCOME", "Salary"),
    ("2026-02-10 09:00:00+00:00", -300.0, "EXPENSE", "Groceries"),
    # 14:00 on 18 Feb in Singapore (day 18: in), 01:00 on 18 Feb in New York (day 18: out).
    ("2026-02-18 06:00:00+00:00", -40.0, "EXPENSE", "Groceries"),
    # Date-only statement row: 18 Feb everywhere.
    ("2026-02-18 00:00:00+00:00", -25.0, "EXPENSE", "Groceries"),
    # 04:00 on 19 Feb in Singapore, 15:00 on 18 Feb in New York: out for both.
    ("2026-02-18 20:00:00+00:00", -60.0, "EXPENSE", "Groceries"),
    ("2026-02-25 09:00:00+00:00", -500.0, "EXPENSE", "Groceries"),
    ("2026-02-25 10:00:00+00:00", 1000.0, "INCOME", "Salary"),
    ("2026-03-02 09:00:00+00:00", -2000.0, "EXPENSE", "Rent"),
    ("2026-03-03 09:00:00+00:00", 5000.0, "INCOME", "Salary"),
    ("2026-03-12 09:00:00+00:00", -900.0, "EXPENSE", "Groceries"),
]
FEB_INFLOWS = 6000.0
FEB_OUTFLOWS = 2000 + 300 + 40 + 25 + 60 + 500
MAR_INFLOWS, MAR_OUTFLOWS = 5000.0, 2900.0


def _seed(db_engine, user_id: int, timezone_name: str) -> None:
    ensure_user(db_engine, user_id)
    set_user_timezone(db_engine, user_id, timezone_name)
    account_id = 9400 + user_id
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
                "VALUES (:ts, :a, :amt, :type, 'SGD', :cat, :m)"
            ),
            [
                {"ts": ts, "a": account_id, "amt": amt, "type": kind, "cat": cat, "m": f"Synthetic {cat}"}
                for ts, amt, kind, cat in ROWS
            ],
        )


@pytest.fixture()
def households(client: TestClient, db_engine, monkeypatch):
    monkeypatch.setenv("TZ", SINGAPORE)
    monkeypatch.setenv("SNAPSHOT_DAY", "1")
    _seed(db_engine, NY_USER, NEW_YORK)
    _seed(db_engine, SG_USER, SINGAPORE)
    return client


def _analytics(client: TestClient, user_id: int, month: str) -> dict:
    as_user(client, user_id)
    resp = client.get(f"/spending/cash-flow-detail?month={month}&base_currency=SGD")
    assert resp.status_code == 200, resp.text
    return resp.json()["analytics"]


def _deltas(items: list[dict]) -> dict[str, float]:
    return {item["label"]: item["delta_amount"] for item in items}


# ─── The window: month-length edges ────────────────────────────────────────


@pytest.mark.parametrize(
    ("month", "today", "through", "month_days", "prior_through", "prior_days"),
    [
        ("2026-03", date(2026, 3, 18), 18, 31, 18, 28),  # an ordinary day
        ("2026-03", date(2026, 3, 1), 1, 31, 1, 28),  # the 1st: one day vs one day
        ("2026-03", date(2026, 3, 31), 31, 31, 28, 28),  # 31 Mar vs February: all of February
        ("2026-03", date(2026, 3, 30), 30, 31, 28, 28),  # 30 Mar vs February: all of February
        ("2028-03", date(2028, 3, 30), 30, 31, 29, 29),  # leap year: all of 29-day February
        ("2028-03", date(2028, 3, 29), 29, 31, 29, 29),
        ("2026-12", date(2026, 12, 31), 31, 31, 30, 30),  # day 31 vs a 30-day month: all of it
        ("2026-05", date(2026, 5, 31), 31, 31, 30, 30),
        ("2026-11", date(2026, 11, 30), 30, 30, 30, 31),  # 30 Nov vs October: 1-30 Oct, not all of it
        ("2027-01", date(2027, 1, 15), 15, 31, 15, 31),  # across the year boundary
        ("2026-02", date(2026, 2, 28), 28, 28, 28, 31),  # last day of February vs 1-28 Jan
    ],
)
def test_open_month_window_is_the_same_day_clamped(month, today, through, month_days, prior_through, prior_days):
    window = _comparison_window(_parse_month(month), today)
    assert window.basis == "month_to_date"
    assert (window.through_day, window.month_days) == (through, month_days)
    assert (window.prior_through_day, window.prior_month_days) == (prior_through, prior_days)
    # The exclusive end is the day after the last counted day of the prior month.
    assert window.prior_end.date() - window.prior_month_start.date() == timedelta(days=prior_through)


@pytest.mark.parametrize(
    ("month", "today", "month_days", "prior_days"),
    [
        ("2026-02", date(2026, 3, 18), 28, 31),  # a past month: whole vs whole
        ("2025-12", date(2026, 3, 18), 31, 30),
        ("2026-04", date(2026, 3, 18), 30, 31),  # a future month has no "today" in it
    ],
)
def test_other_months_compare_whole_months(month, today, month_days, prior_days):
    window = _comparison_window(_parse_month(month), today)
    assert window.basis == "full_month"
    assert (window.through_day, window.month_days) == (month_days, month_days)
    assert (window.prior_through_day, window.prior_month_days) == (prior_days, prior_days)


# ─── The endpoint ──────────────────────────────────────────────────────────


def test_open_month_compares_with_the_same_day_last_month(households, monkeypatch):
    freeze_clock(monkeypatch, MID_MARCH)
    analytics = _analytics(households, SG_USER, "2026-03")
    comparison = analytics["comparison"]

    assert comparison["basis"] == "month_to_date"
    assert (comparison["through_day"], comparison["month_days"]) == (18, 31)
    assert comparison["prior_month"] == "2026-02"
    assert (comparison["prior_start"], comparison["prior_end"]) == ("2026-02-01", "2026-02-18")
    assert comparison["prior_through_day"] == 18

    prior_outflows = 2000 + 300 + 40 + 25
    assert comparison["inflows"] == pytest.approx(MAR_INFLOWS, abs=TOL)
    assert comparison["outflows"] == pytest.approx(MAR_OUTFLOWS, abs=TOL)
    assert comparison["prior_inflows"] == pytest.approx(5000.0, abs=TOL)
    assert comparison["prior_outflows"] == pytest.approx(prior_outflows, abs=TOL)
    assert comparison["prior_net"] == pytest.approx(5000.0 - prior_outflows, abs=TOL)
    assert comparison["net_change"] == pytest.approx((MAR_INFLOWS - MAR_OUTFLOWS) - (5000.0 - prior_outflows), abs=TOL)
    assert comparison["outflows_change"] == pytest.approx(MAR_OUTFLOWS - prior_outflows, abs=TOL)
    assert comparison["prior_savings_rate"] == pytest.approx((5000.0 - prior_outflows) / 5000.0, abs=1e-6)

    # Categories compare like for like too: groceries 900 vs 365 by day 18 ...
    assert _deltas(comparison["outflow_category_deltas"]) == pytest.approx({"Groceries": 900.0 - 365.0}, abs=TOL)
    # ... and salary is level by day 18, so it is no deterioration driver.
    assert _deltas(comparison["deterioration_drivers"]) == pytest.approx({"Groceries": -(900.0 - 365.0)}, abs=TOL)

    # The existing fields keep their meaning (whole previous month; D-24: no silent change).
    assert analytics["prior_month_net"] == pytest.approx(FEB_INFLOWS - FEB_OUTFLOWS, abs=TOL)
    assert analytics["free_cash_flow_change_vs_prior_month"] == pytest.approx(
        (MAR_INFLOWS - MAR_OUTFLOWS) - (FEB_INFLOWS - FEB_OUTFLOWS), abs=TOL
    )
    # Against the whole of February groceries were down (900 vs 925): the old list hid the rise.
    assert analytics["outflow_category_deltas"] == []


def test_same_instant_is_a_different_day_in_new_york(households, monkeypatch):
    """At 02:00Z on 18 Mar it is still the 17th in New York: day 17 of March
    against 1-17 Feb by New York's calendar."""
    freeze_clock(monkeypatch, MID_MARCH)
    comparison = _analytics(households, NY_USER, "2026-03")["comparison"]
    assert comparison["basis"] == "month_to_date"
    assert comparison["through_day"] == 17
    assert (comparison["prior_start"], comparison["prior_end"]) == ("2026-02-01", "2026-02-17")
    # Neither 18 Feb row is in New York's 1-17 Feb.
    assert comparison["prior_outflows"] == pytest.approx(2000 + 300, abs=TOL)
    assert _deltas(comparison["outflow_category_deltas"]) == pytest.approx({"Groceries": 900.0 - 300.0}, abs=TOL)


def test_the_open_month_follows_the_users_today(households, monkeypatch):
    """At 04:00Z on 1 Mar, Singapore is in March (day 1) and February is past;
    New York is still on 28 Feb, so February is its open month (day 28 of 28,
    against 1-28 Jan)."""
    freeze_clock(monkeypatch, datetime(2026, 3, 1, 4, 0, tzinfo=timezone.utc))

    sg_feb = _analytics(households, SG_USER, "2026-02")["comparison"]
    assert sg_feb["basis"] == "full_month"
    sg_mar = _analytics(households, SG_USER, "2026-03")["comparison"]
    assert sg_mar["basis"] == "month_to_date"
    assert (sg_mar["through_day"], sg_mar["prior_end"]) == (1, "2026-02-01")

    ny_feb = _analytics(households, NY_USER, "2026-02")["comparison"]
    assert ny_feb["basis"] == "month_to_date"
    assert (ny_feb["through_day"], ny_feb["month_days"]) == (28, 28)
    assert (ny_feb["prior_start"], ny_feb["prior_end"]) == ("2026-01-01", "2026-01-28")


def test_past_month_is_whole_month_vs_whole_month(households, monkeypatch):
    """A past month's comparison is exactly the existing full-month fields."""
    freeze_clock(monkeypatch, MID_MARCH)
    analytics = _analytics(households, SG_USER, "2026-02")
    comparison = analytics["comparison"]
    assert comparison["basis"] == "full_month"
    assert (comparison["through_day"], comparison["month_days"]) == (28, 28)
    assert (comparison["prior_start"], comparison["prior_end"]) == ("2026-01-01", "2026-01-31")
    assert comparison["inflows"] == pytest.approx(FEB_INFLOWS, abs=TOL)
    assert comparison["outflows"] == pytest.approx(FEB_OUTFLOWS, abs=TOL)
    assert comparison["prior_net"] == pytest.approx(analytics["prior_month_net"], abs=TOL)
    assert comparison["net_change"] == pytest.approx(analytics["free_cash_flow_change_vs_prior_month"], abs=TOL)
    assert comparison["outflow_category_deltas"] == analytics["outflow_category_deltas"]
    assert comparison["deterioration_drivers"] == analytics["deterioration_drivers"]


def test_burn_rate_stays_in_the_response(households, monkeypatch):
    """The page no longer shows it, but fields are only ever added (#243)."""
    freeze_clock(monkeypatch, MID_MARCH)
    analytics = _analytics(households, SG_USER, "2026-03")
    assert analytics["burn_rate"] == pytest.approx(MAR_OUTFLOWS / MAR_INFLOWS, abs=1e-6)
    assert all("burn_rate" in point for point in analytics["trend"])
