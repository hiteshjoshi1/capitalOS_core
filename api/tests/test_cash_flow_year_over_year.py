"""Cash Flow against the same month last year, and the twelve-month savings-rate line
(#409, U15, D-113). The open month compares days 1..today with the same days of last
year's month; a past month is whole vs whole. Own-account transfers stay out (D-85).
Synthetic user and data only."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.auth_helpers import ensure_user
from tests.valuation_household import as_user, freeze_clock, set_user_timezone

SINGAPORE = "Asia/Singapore"
USER = 1
TOL = 0.01
# 10:00 on 18 Mar 2026 in Singapore.
MID_MARCH = datetime(2026, 3, 18, 2, 0, tzinfo=timezone.utc)

# (ts, amount, type, category) on one SGD bank account.
ROWS = [
    # March 2025: the year-ago month. Days 1-18 and after.
    ("2025-03-03 09:00:00+00:00", 4000.0, "INCOME", "Salary"),
    ("2025-03-05 09:00:00+00:00", -1500.0, "EXPENSE", "Rent"),
    ("2025-03-10 09:00:00+00:00", -200.0, "EXPENSE", "Groceries"),
    ("2025-03-25 09:00:00+00:00", -800.0, "EXPENSE", "Travel"),  # after day 18
    # An own-account standing instruction out of the year-ago month: not spending (D-85).
    ("2025-03-12 09:00:00+00:00", -3000.0, "TRANSFER", "Transfer"),
    # February 2026.
    ("2026-02-03 09:00:00+00:00", 5000.0, "INCOME", "Salary"),
    ("2026-02-05 09:00:00+00:00", -2000.0, "EXPENSE", "Rent"),
    # March 2026 (the open month, up to day 18).
    ("2026-03-03 09:00:00+00:00", 5000.0, "INCOME", "Salary"),
    ("2026-03-05 09:00:00+00:00", -2000.0, "EXPENSE", "Rent"),
    ("2026-03-11 09:00:00+00:00", -100.0, "EXPENSE", "Groceries"),
    ("2026-03-14 09:00:00+00:00", -400.0, "EXPENSE", "Dining"),
]


def _seed(db_engine) -> None:
    ensure_user(db_engine, USER)
    set_user_timezone(db_engine, USER, SINGAPORE)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) "
                "VALUES (9801, 'Synthetic Bank', 'SYNTH', 'BANK', 'SGD', 'SG', :u)"
            ),
            {"u": USER},
        )
        conn.execute(
            text(
                "INSERT INTO transactions (ts, account_id, amount, type, currency, category, merchant_counterparty) "
                "VALUES (:ts, 9801, :amt, :type, 'SGD', :cat, :m)"
            ),
            [{"ts": ts, "amt": amt, "type": kind, "cat": cat, "m": f"Synthetic {cat}"} for ts, amt, kind, cat in ROWS],
        )


@pytest.fixture()
def seeded(client: TestClient, db_engine, monkeypatch):
    monkeypatch.setenv("TZ", SINGAPORE)
    monkeypatch.setenv("SNAPSHOT_DAY", "1")
    _seed(db_engine)
    as_user(client, USER)
    return client


def _analytics(client: TestClient, month: str) -> dict:
    resp = client.get(f"/spending/cash-flow-detail?month={month}&base_currency=SGD")
    assert resp.status_code == 200, resp.text
    return resp.json()["analytics"]


def _deltas(items: list[dict]) -> dict[str, float]:
    return {item["label"]: item["delta_amount"] for item in items}


def test_open_month_compares_with_the_same_days_last_year(seeded, monkeypatch):
    freeze_clock(monkeypatch, MID_MARCH)
    yoy = _analytics(seeded, "2026-03")["year_over_year"]
    assert yoy["basis"] == "month_to_date"
    assert (yoy["prior_year_month"], yoy["through_day"]) == ("2025-03", 18)
    assert (yoy["prior_start"], yoy["prior_end"]) == ("2025-03-01", "2025-03-18")
    assert yoy["has_prior_year_data"] is True
    # Days 1-18 of March 2025: salary 4000, rent 1500, groceries 200. Travel (25th) is out,
    # and so is the own-account transfer (D-85).
    assert yoy["prior_inflows"] == pytest.approx(4000.0, abs=TOL)
    assert yoy["prior_outflows"] == pytest.approx(1700.0, abs=TOL)
    assert yoy["outflows"] == pytest.approx(2500.0, abs=TOL)
    assert yoy["prior_savings_rate"] == pytest.approx((4000 - 1700) / 4000, abs=1e-6)
    deltas = _deltas(yoy["outflow_category_deltas"])
    assert deltas == pytest.approx({"Rent": 500.0, "Dining": 400.0, "Groceries": -100.0}, abs=TOL)
    # Both directions, biggest increase first.
    assert [item["label"] for item in yoy["outflow_category_deltas"]] == ["Rent", "Dining", "Groceries"]


def test_past_month_is_whole_month_vs_whole_month(seeded, monkeypatch):
    freeze_clock(monkeypatch, datetime(2027, 4, 10, 2, 0, tzinfo=timezone.utc))
    yoy = _analytics(seeded, "2026-03")["year_over_year"]
    assert yoy["basis"] == "full_month"
    assert yoy["prior_end"] == "2025-03-31"
    # The whole of March 2025 now: travel on the 25th is in.
    assert yoy["prior_outflows"] == pytest.approx(2500.0, abs=TOL)
    assert _deltas(yoy["outflow_category_deltas"])["Travel"] == pytest.approx(-800.0, abs=TOL)


def test_no_data_last_year_says_so(seeded, monkeypatch):
    freeze_clock(monkeypatch, MID_MARCH)
    yoy = _analytics(seeded, "2026-02")["year_over_year"]
    assert yoy["prior_year_month"] == "2025-02"
    assert yoy["has_prior_year_data"] is False
    assert yoy["prior_outflows"] == 0
    assert yoy["prior_savings_rate"] is None


def test_savings_rate_trend_covers_twelve_months(seeded, monkeypatch):
    freeze_clock(monkeypatch, MID_MARCH)
    trend = _analytics(seeded, "2026-03")["savings_rate_trend"]
    assert [p["month"] for p in trend][0] == "2025-04"
    assert [p["month"] for p in trend][-1] == "2026-03"
    assert len(trend) == 12
    by_month = {p["month"]: p for p in trend}
    assert by_month["2026-02"]["savings_rate"] == pytest.approx(0.6, abs=1e-6)
    assert by_month["2026-03"]["savings_rate"] == pytest.approx((5000 - 2500) / 5000, abs=1e-6)
    # A month without income has no rate, not 0 %.
    assert by_month["2025-06"]["savings_rate"] is None
