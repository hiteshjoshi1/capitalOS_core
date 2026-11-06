"""#249 (D-65): "since last update" is market movement since the compare date
for every holding.

The compare date is the newest statement date at or before yesterday (the
label, ``compare_as_of``). The compare side is valued at that date: each holding
at its last quote on or before it (D-21's rule, as the live headline), so a
broker whose newest statement is weeks older than another's is compared at the
quote on the compare date, not at its old statement price nor at a quote from
after the date the label names. A holding with no usable quote by then is at its
statement price, flagged and counted.

Synthetic household (tests/valuation_household.py); every number is made up.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.valuation.clock import _compare_date_anchor_ts
from tests.canonical_test_helpers import seed_canonical_position_snapshot_for_test
from tests.valuation_household import (
    AAPL,
    INFY,
    RELIANCE,
    SGT,
    SHAREKHAN,
    TENCENT,
    build_household,
    fx,
    household_env,
)

# 2 April, 10:00 SGT. IBKR's newest statement is 31 March (the compare date);
# Sharekhan's is 15 March, more than two weeks older.
NOW = datetime(2026, 4, 2, 10, 0, tzinfo=SGT)
COMPARE_DATE = date(2026, 3, 31)
TCS = 5  # a Sharekhan holding the price job has no quote for until today
WIPRO = 6  # a Sharekhan holding the price job never quotes

# Quotes after the compare date: 1 April (yesterday) and 2 April (today).
LATER_QUOTES = (
    ("2026-04-01", AAPL, 210.0, "USD", "US"),
    ("2026-04-01", TENCENT, 310.0, "HKD", "HKEX"),
    ("2026-04-01", RELIANCE, 3000.0, "INR", "NSE"),
    ("2026-04-01", INFY, 1700.0, "INR", "NSE"),
    ("2026-04-02", AAPL, 212.0, "USD", "US"),
    ("2026-04-02", TENCENT, 312.0, "HKD", "HKEX"),
    ("2026-04-02", RELIANCE, 3100.0, "INR", "NSE"),
    ("2026-04-02", INFY, 1720.0, "INR", "NSE"),
    ("2026-04-02", TCS, 4200.0, "INR", "NSE"),
)


@pytest.fixture()
def household(client: TestClient, db_engine, monkeypatch):
    household_env(monkeypatch, NOW)
    build_household(db_engine, now=NOW)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) "
                "VALUES (:tcs, 'TCS', 'Tata Consultancy', 'STOCK', 'INR', 'IN'), "
                "(:wipro, 'WIPRO', 'Wipro', 'STOCK', 'INR', 'IN')"
            ),
            {"tcs": TCS, "wipro": WIPRO},
        )
        conn.execute(
            text(
                "INSERT INTO prices (asset_id, ts, trade_date, price, currency, source, exchange_code) "
                "VALUES (:asset, :ts, :d, :p, :c, 'synthetic', :x)"
            ),
            [
                {"asset": asset, "ts": f"{d} 10:00:00+00:00", "d": d, "p": price, "c": cur, "x": exchange}
                for d, asset, price, cur, exchange in LATER_QUOTES
            ],
        )
    # TCS and WIPRO join Sharekhan's 15 March holdings statement.
    for asset_id, quantity, price in ((TCS, 5, 4000.0), (WIPRO, 30, 500.0)):
        seed_canonical_position_snapshot_for_test(
            db_engine,
            account_id=SHAREKHAN,
            asset_id=asset_id,
            as_of="2026-03-15",
            quantity=quantity,
            market_value_base=quantity * price,
            market_price=price,
            cost_basis_base=quantity * price * 0.9,
            currency="INR",
            platform_code="SHAREKHAN",
        )
    return client


def _since_update(client: TestClient) -> dict:
    resp = client.get("/dashboard/net-worth-since-update?base_currency=SGD")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _movers(payload: dict) -> dict[str, dict]:
    movers = payload["top_movers"]
    return {row["symbol"]: row for row in [*movers["gainers"], *movers["detractors"]]}


def test_an_older_statement_is_compared_at_the_quote_on_the_compare_date(household):
    payload = _since_update(household)
    assert payload["compare_as_of"].startswith(COMPARE_DATE.isoformat())
    assert payload["basis"] == "quoted_at_compare_date"
    movers = _movers(payload)
    today, compare = date(2026, 4, 2), COMPARE_DATE

    # Sharekhan's statement is from 15 March (12 RELIANCE at 2880, 20 INFY at
    # 1620). Its holdings are compared at their 31 March quotes (2950, 1640),
    # not at 2880/1620 (the old statement) nor at 1 April's (after the label).
    reliance = movers["RELIANCE"]
    assert reliance["previous_value"] == pytest.approx(12 * 2950.0 * fx(compare, "INR"), abs=0.01)
    assert reliance["current_value"] == pytest.approx(12 * 3100.0 * fx(today, "INR"), abs=0.01)
    assert reliance["compare_price_basis"] == "quote"
    assert reliance["compare_price_as_of"] == "2026-03-31"
    assert reliance["compare_price_fallback"] is False
    infy = movers["INFY"]
    assert infy["previous_value"] == pytest.approx(20 * 1640.0 * fx(compare, "INR"), abs=0.01)
    assert infy["compare_price_as_of"] == "2026-03-31"

    # IBKR's holdings (statement of 31 March) likewise, at the 31 March quote.
    aapl = movers["AAPL"]
    assert aapl["previous_value"] == pytest.approx(25 * 206.0 * fx(compare, "USD"), abs=0.01)
    assert aapl["current_value"] == pytest.approx(25 * 212.0 * fx(today, "USD"), abs=0.01)
    assert aapl["compare_price_basis"] == "quote"


def test_a_holding_without_a_quote_by_the_compare_date_falls_back_and_is_counted(household):
    payload = _since_update(household)
    tcs = _movers(payload)["TCS"]
    # No quote on or before 31 March: its statement price (15 March), flagged.
    assert tcs["previous_value"] == pytest.approx(5 * 4000.0 * fx(COMPARE_DATE, "INR"), abs=0.01)
    assert tcs["current_value"] == pytest.approx(5 * 4200.0 * fx(date(2026, 4, 2), "INR"), abs=0.01)
    assert tcs["compare_price_basis"] == "statement"
    assert tcs["compare_price_as_of"] == "2026-03-15"
    assert tcs["compare_price_fallback"] is True
    # WIPRO has no quote at all: its statement price on both sides, so it moves
    # only with the INR rate, and isn't flagged.
    wipro = _movers(payload)["WIPRO"]
    assert wipro["previous_value"] == pytest.approx(30 * 500.0 * fx(COMPARE_DATE, "INR"), abs=0.01)
    assert wipro["compare_price_basis"] == "statement"
    assert wipro["compare_price_fallback"] is False
    assert payload["compare_basis"] == {
        "price_date": "2026-03-31",
        "holdings": 6,
        "quoted": 4,
        "statement_priced": 2,
        "older_statement_priced": 1,
    }


def test_the_stocks_change_is_the_sum_of_the_holdings_moves(household):
    payload = _since_update(household)
    stocks = payload["component_change"]["stocks_funds"]
    stock_moves = [row for row in _movers(payload).values() if row["asset_class"] == "STOCK"]
    # Every holding is listed: five gainers, and WIPRO (FX only: the rupee fell) the one detractor.
    assert len(stock_moves) == 6
    assert [row["symbol"] for row in payload["top_movers"]["detractors"] if row["asset_class"] == "STOCK"] == ["WIPRO"]
    assert stocks["abs"] == pytest.approx(sum(row["delta_abs"] for row in stock_moves), abs=0.05)
    # The wallets' newest snapshot is from 31 March on both sides: crypto moves
    # only with the USD rate (April's vs March's).
    crypto = payload["component_change"]["crypto"]
    ratio = (crypto["compare_value"] + crypto["abs"]) / crypto["compare_value"]
    assert ratio == pytest.approx(fx(date(2026, 4, 2), "USD") / fx(COMPARE_DATE, "USD"))


def test_compare_date_anchor():
    anchor = datetime(2026, 4, 1, 10, 0, tzinfo=SGT)
    assert _compare_date_anchor_ts(anchor, None) == anchor
    same_day = datetime(2026, 4, 1, tzinfo=timezone.utc)
    assert _compare_date_anchor_ts(anchor, same_day) == anchor
    earlier = datetime(2026, 3, 15, tzinfo=timezone.utc)
    shifted = _compare_date_anchor_ts(anchor, earlier)
    assert shifted == anchor - timedelta(days=17)
    assert shifted.date() == date(2026, 3, 15)
