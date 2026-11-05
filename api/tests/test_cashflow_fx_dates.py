"""Cash flow converts each transaction at its own date (#170, D-30).

Spending pages, credit-card pages and the dashboard cash flow used to convert a
whole month at the rate for the 1st. Here two transactions in one month on
different dates must convert at their own (synthetic, non-1) rates; a currency
with no rate is left out (never 1.0) and the response is flagged; and the same
month's totals agree on Overview (/spending/summary), the History trend
(/spending/cash-flow-detail analytics.trend), Cash Flow detail and the
dashboard summary. Providers are down: only the stored rates below exist."""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text

from tests.test_fx import _store, providers_down  # noqa: F401 - fixture re-export

BANK_SGD, BANK_USD, CARD_USD = 7501, 7502, 7503

# 1 USD in SGD on each stored date. The 1st is deliberately different from
# both transaction dates, so a month-start conversion would fail every assert.
RATE_APR_01, RATE_APR_03, RATE_APR_20 = 1.2, 1.3, 1.4

INCOME = 1000 * RATE_APR_03 + 1000 * RATE_APR_20  # 2700
BANK_SPEND = 200 * RATE_APR_03 + 300 * RATE_APR_20  # 680
CARD_SPEND = 50 * RATE_APR_03 + 70 * RATE_APR_20  # 163
EXPENSES = BANK_SPEND + CARD_SPEND  # 843


def _seed(db_engine, *, with_unknown_currency: bool = False) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES "
                f"({BANK_SGD}, 'Home Bank', 'HBANK', 'BANK', 'SGD', 'SG', 1), "
                f"({BANK_USD}, 'Dollar Bank', 'DBANK', 'BANK', 'USD', 'US', 1), "
                f"({CARD_USD}, 'Dollar Card', 'DBANK', 'CREDIT_CARD', 'USD', 'US', 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO credit_card_accounts (account_id, card_name, issuer, credit_limit, statement_day, due_day) "
                f"VALUES ({CARD_USD}, 'Test Card', 'DBANK', 5000, 20, 25)"
            )
        )
        rows = [
            (7601, "2026-04-03 10:00:00+00:00", BANK_USD, 1000, "INCOME", "USD", "Salary", "Employer A"),
            (7602, "2026-04-20 10:00:00+00:00", BANK_USD, 1000, "INCOME", "USD", "Salary", "Employer A"),
            (7603, "2026-04-03 11:00:00+00:00", BANK_USD, -200, "EXPENSE", "USD", "Groceries", "Grocer"),
            (7604, "2026-04-20 11:00:00+00:00", BANK_USD, -300, "EXPENSE", "USD", "Groceries", "Grocer"),
            (7605, "2026-04-03 12:00:00+00:00", CARD_USD, -50, "EXPENSE", "USD", "Dining", "Cafe"),
            (7606, "2026-04-20 12:00:00+00:00", CARD_USD, -70, "EXPENSE", "USD", "Dining", "Cafe"),
        ]
        if with_unknown_currency:
            rows.append((7607, "2026-04-10 12:00:00+00:00", BANK_SGD, -999, "EXPENSE", "XYZ", "Travel", "Exotic Shop"))
        for row in rows:
            conn.execute(
                text(
                    "INSERT INTO transactions (id, ts, account_id, amount, type, currency, category, merchant_counterparty) "
                    "VALUES (:id, :ts, :account_id, :amount, :type, :currency, :category, :merchant)"
                ),
                dict(zip(("id", "ts", "account_id", "amount", "type", "currency", "category", "merchant"), row)),
            )
    _store(db_engine, date(2026, 4, 1), {"USD": 1.0, "SGD": RATE_APR_01})
    _store(db_engine, date(2026, 4, 3), {"USD": 1.0, "SGD": RATE_APR_03})
    _store(db_engine, date(2026, 4, 20), {"USD": 1.0, "SGD": RATE_APR_20})


def _flags(body: dict) -> tuple:
    return body["fx_incomplete"], body["fx_missing_currencies"]


def test_each_transaction_converts_at_its_own_date_and_pages_agree(client, db_engine, providers_down):  # noqa: F811
    _seed(db_engine)

    summary = client.get("/spending/summary?month=2026-04&base_currency=SGD").json()
    assert summary["income_total"] == pytest.approx(INCOME)
    assert summary["expense_total"] == pytest.approx(EXPENSES)
    assert _flags(summary) == (False, [])

    detail = client.get("/spending/cash-flow-detail?month=2026-04&base_currency=SGD").json()
    assert detail["income_total"] == pytest.approx(INCOME)
    assert detail["expense_total"] == pytest.approx(EXPENSES)
    assert sorted(t["base_amount"] for t in detail["income"]["transactions"]) == [
        pytest.approx(1000 * RATE_APR_03),
        pytest.approx(1000 * RATE_APR_20),
    ]
    assert detail["analytics"]["trend"][-1]["month"] == "2026-04"
    assert detail["analytics"]["trend"][-1]["inflows"] == pytest.approx(INCOME)
    assert detail["analytics"]["trend"][-1]["outflows"] == pytest.approx(EXPENSES)
    assert _flags(detail) == (False, [])

    # History's "Income vs spending" chart reads a later month's trend.
    later = client.get("/spending/cash-flow-detail?month=2026-05&base_currency=SGD").json()
    april = next(p for p in later["analytics"]["trend"] if p["month"] == "2026-04")
    assert april["inflows"] == pytest.approx(INCOME)
    assert april["outflows"] == pytest.approx(EXPENSES)
    assert later["analytics"]["prior_month_net"] == pytest.approx(INCOME - EXPENSES)

    dash = client.get("/dashboard/summary?month=2026-04&base_currency=SGD&skip_networth=true").json()
    assert dash["cash_flow"]["income"] == pytest.approx(INCOME)
    assert dash["cash_flow"]["expenses"] == pytest.approx(EXPENSES)

    analytics = client.get("/spending/credit-card-analytics?month=2026-04&base_currency=SGD").json()
    assert analytics["total_spend"] == pytest.approx(CARD_SPEND)
    assert sorted(t["amount"] for t in analytics["transactions"]) == [
        pytest.approx(-70 * RATE_APR_20),
        pytest.approx(-50 * RATE_APR_03),
    ]
    assert analytics["trend"][-1]["spend"] == pytest.approx(CARD_SPEND)
    assert _flags(analytics) == (False, [])

    card_tx = client.get("/spending/credit-card-transactions?month=2026-04&base_currency=SGD").json()
    assert sorted(t["amount"] for t in card_tx["transactions"]) == [
        pytest.approx(-70 * RATE_APR_20),
        pytest.approx(-50 * RATE_APR_03),
    ]
    assert card_tx["total_spend"] == pytest.approx(CARD_SPEND)
    assert _flags(card_tx) == (False, [])

    cards = client.get("/spending/credit-cards?month=2026-04&base_currency=SGD").json()
    assert cards["total_spend"] == pytest.approx(CARD_SPEND)
    # The card limit is a balance, not a flow: still valued at the month's start.
    assert cards["cards"][0]["credit_limit"] == pytest.approx(5000 * RATE_APR_01)
    assert _flags(cards) == (False, [])


def test_missing_rate_is_left_out_and_flagged_never_one(client, db_engine, providers_down):  # noqa: F811
    _seed(db_engine, with_unknown_currency=True)

    summary = client.get("/spending/summary?month=2026-04&base_currency=SGD").json()
    assert summary["expense_total"] == pytest.approx(EXPENSES)  # XYZ 999 is not counted 1:1
    assert _flags(summary) == (True, ["XYZ"])

    detail = client.get("/spending/cash-flow-detail?month=2026-04&base_currency=SGD").json()
    assert detail["expense_total"] == pytest.approx(EXPENSES)
    xyz = next(t for t in detail["expenses"]["transactions"] if t["currency"] == "XYZ")
    assert xyz["amount"] == -999
    assert xyz["base_amount"] == 0
    assert _flags(detail) == (True, ["XYZ"])

    dash = client.get("/dashboard/summary?month=2026-04&base_currency=SGD&skip_networth=true").json()
    assert dash["cash_flow"]["expenses"] == pytest.approx(EXPENSES)
    assert dash["fx_incomplete"] is True
    assert "XYZ" in dash["fx_missing_currencies"]
