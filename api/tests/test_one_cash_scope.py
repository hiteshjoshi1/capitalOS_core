"""#144: one cash scope, breakdowns that add up, and D-21's price rule for every
holding and for dividend yields. Synthetic household (tests/valuation_household.py)
unless a test builds its own rows; every number here is made up."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import valuation_cache
from app.portfolio.position_pricing import (
    PRICE_FALLBACK_IMPLAUSIBLE,
    PRICE_FALLBACK_NO_QUOTE,
    PRICE_FALLBACK_OLDER_QUOTE,
    latest_quotes,
    price_position,
)
from tests.valuation_household import (
    FLEX_REPORTS,
    INFY,
    RELIANCE,
    SCENARIOS,
    USER_A,
    build_household,
    fx,
    household_env,
    upload_balance,
)

MID = SCENARIOS["mid"]
TOL = 0.01


@pytest.fixture()
def household(client: TestClient, db_engine, monkeypatch):
    household_env(monkeypatch, MID)
    build_household(db_engine, now=MID)
    return client


def _get(client: TestClient, path: str) -> dict:
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.text)
    return resp.json()


def _live_cash(client: TestClient) -> float:
    return _get(client, "/dashboard/summary?month=2026-03&base_currency=SGD")["current_net_worth"]["cash"]


def _holding(client: TestClient, symbol: str, month: str = "2026-03") -> dict:
    holdings = _get(client, f"/dashboard/stock-holdings?month={month}&base_currency=SGD")["top_holdings"]
    return next(h for h in holdings if h["symbol"] == symbol)


# ─── Cash ────────────────────────────────────────────────────────────────────


def test_foreign_currency_upload_is_converted_from_its_own_currency(household, db_engine):
    """A USD statement uploaded to an SGD account counts at the USD rate, not 1:1
    as if its amount were already in SGD (#130 2.8)."""
    before = _live_cash(household)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country, platform_id) "
                "VALUES (191, 'DBS Multi', 'DBS', :a, 'BANK', 'SGD', 'SG', 1)"
            ),
            {"a": USER_A},
        )
    upload_balance(db_engine, 191, "2026-03-05", "USD", 1000.0)
    valuation_cache.clear_shared_cache()
    assert _live_cash(household) - before == pytest.approx(1000.0 * fx(MID.date(), "USD"), abs=TOL)


def test_nav_cash_rows_that_dont_add_up_keep_the_nav_total(household, db_engine):
    """IBKR cash is the NAV's cash. When the per-currency cash rows of the NAV's
    report date don't cover it (here the USD row is missing), the rest is shown
    in the NAV's base currency: the Cash page still equals net-worth cash."""
    report = next(r for r in FLEX_REPORTS if r.report_date == date(2026, 3, 16))
    nav_cash = report.cash_sgd + report.cash_usd * fx(report.report_date, "USD")
    with db_engine.begin() as conn:
        deleted = conn.execute(
            text(
                "DELETE FROM portfolio_cash_balance_snapshots WHERE currency = 'USD' AND report_date = '2026-03-16'"
            )
        ).rowcount
    assert deleted == 1
    valuation_cache.clear_shared_cache()

    page = _get(household, "/dashboard/cash-deposits?month=2026-03&base_currency=SGD")
    items = {i["source"]: i["value"] for i in page["items"]}
    assert items["IBKR"] == pytest.approx(nav_cash, abs=TOL)
    stable = page["total"] - _live_cash(household)
    assert stable > 0  # stablecoins, the only difference
    balances = {b["currency"]: b["value"] for b in _get(household, "/dashboard/summary?month=2026-03&base_currency=SGD")["cash_balances"]}
    assert sum(balances.values()) == pytest.approx(_live_cash(household), abs=TOL)


def test_every_cash_reader_uses_one_scope(household):
    """Net-worth cash, the summary's cash by currency, the Cash page (minus
    stablecoins) and the cash in geography all describe the same money."""
    summary = _get(household, "/dashboard/summary?month=2026-03&base_currency=SGD")
    nw_cash = summary["current_net_worth"]["cash"]
    assert sum(b["value"] for b in summary["cash_balances"]) == pytest.approx(nw_cash, abs=TOL)
    past = _get(household, "/dashboard/summary?month=2026-02&base_currency=SGD")["net_worth"]
    geo = _get(household, "/dashboard/geography-exposure?month=2026-02&base_currency=SGD")
    # geography shows stablecoins as US cash; net worth counts them as crypto
    assert sum(i["cash"] + i["crypto"] for i in geo["items"]) == pytest.approx(past["cash"] + past["crypto"], abs=TOL)


# ─── D-21 for every holding ──────────────────────────────────────────────────


def test_uploaded_holding_ignores_a_quote_older_than_its_statement(household, db_engine):
    """Sharekhan's 15 March holdings: with RELIANCE's 17 March quote gone, its
    newest quote (27 Feb) predates the statement, so the statement price stands."""
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM prices WHERE asset_id = :a AND trade_date >= '2026-03-01'"), {"a": RELIANCE})
    valuation_cache.clear_shared_cache()
    reliance = _holding(household, "RELIANCE")
    assert reliance["price_fallback_reason"] == PRICE_FALLBACK_OLDER_QUOTE
    assert reliance["value"] == pytest.approx(12 * 2880.0 * fx(MID.date(), "INR"), abs=TOL)
    infy = _holding(household, "INFY")
    assert infy["price_fallback_reason"] is None  # its 17 March quote is used
    assert infy["value"] == pytest.approx(20 * 1650.0 * fx(MID.date(), "INR"), abs=TOL)


def test_uploaded_holding_ignores_an_implausible_quote(household, db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE prices SET price = 29000 WHERE asset_id = :a AND trade_date = '2026-03-17'"), {"a": RELIANCE}
        )
    valuation_cache.clear_shared_cache()
    reliance = _holding(household, "RELIANCE")
    assert reliance["price_fallback_reason"] == PRICE_FALLBACK_IMPLAUSIBLE
    assert reliance["value"] == pytest.approx(12 * 2880.0 * fx(MID.date(), "INR"), abs=TOL)
    # Net worth uses the same value (one rule, one figure).
    nw = _get(household, "/dashboard/summary?month=2026-03&base_currency=SGD")["current_net_worth"]["stocks_funds"]
    exposure = _get(household, "/dashboard/stock-exposure?month=2026-03&base_currency=SGD")["total"]
    assert exposure == pytest.approx(nw, abs=TOL)


def test_snapshot_views_report_no_fallback_reason(household):
    """A past month is valued at its statements: no live-price reasons."""
    for h in _get(household, "/dashboard/stock-holdings?month=2026-02&base_currency=SGD")["top_holdings"]:
        assert h["price_fallback_reason"] is None
        assert h["valued_at_cost"] is False


def test_dividend_yield_denominator_follows_the_same_rule(household, db_engine):
    from app.routers.dividends import _latest_asset_market_values
    from app.valuation.clock import _current_anchor_ts

    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM prices WHERE asset_id = :a AND trade_date >= '2026-03-01'"), {"a": RELIANCE})
    valuation_cache.clear_shared_cache()
    db = Session(bind=db_engine)
    try:
        values = _latest_asset_market_values(db, _current_anchor_ts(), "SGD", USER_A)
    finally:
        db.close()
    rate = fx(MID.date(), "INR")
    assert values[RELIANCE] == pytest.approx(12 * 2880.0 * rate, abs=TOL)  # statement, not the 27 Feb quote
    assert values[INFY] == pytest.approx(20 * 1650.0 * rate, abs=TOL)  # its 17 March quote


def _row(**overrides) -> dict:
    row = {
        "asset_id": 7,
        "quantity": 10.0,
        "report_date": "2026-03-10",
        "account_currency": "USD",
        "quote_currency": "USD",
        "snapshot_market_value_base": 1000.0,
        "snapshot_cost_basis_base": 800.0,
        "cost_basis_base": 800.0,
    }
    row.update(overrides)
    return row


def test_price_position_rules():
    rates = {"USD": 1.0}
    quote = {"price": 110.0, "currency": "USD", "trade_date": "2026-03-12"}
    # Not a live view: the statement value.
    assert price_position(_row(), None, rates, "USD") == (None, None, 1000.0, 1000.0, False)
    # Live, a recent quote: used.
    assert price_position(_row(), {7: quote}, rates, "USD").value == pytest.approx(1100.0)
    # Live, no quote / an older quote / an implausible one: the statement, with the reason.
    assert price_position(_row(), {}, rates, "USD").fallback_reason == PRICE_FALLBACK_NO_QUOTE
    older = {**quote, "trade_date": "2026-03-09"}
    assert price_position(_row(), {7: older}, rates, "USD")[1:3] == (PRICE_FALLBACK_OLDER_QUOTE, 1000.0)
    wild = {**quote, "price": 250.0}
    assert price_position(_row(), {7: wild}, rates, "USD")[1:3] == (PRICE_FALLBACK_IMPLAUSIBLE, 1000.0)
    # No market value: valued at cost and flagged, never 0 (#130 2.7) ...
    at_cost = price_position(_row(snapshot_market_value_base=None), None, rates, "USD")
    assert (at_cost.value, at_cost.valued_at_cost) == (800.0, True)
    # ... and the 2x check doesn't compare a quote with a cost basis.
    assert price_position(_row(snapshot_market_value_base=None), {7: wild}, rates, "USD").value == pytest.approx(2500.0)
    # A missing FX rate leaves the value out (D-30), not 1:1.
    assert price_position(_row(), None, {}, "USD").value == 0.0


def test_quote_selection_is_deterministic_between_sources(db_engine):
    """Two sources quoting the same day: the most recently written row wins,
    whatever order the database returns them in (#130 2.6)."""
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency) "
                "VALUES (901, 'SYNQ', 'Synthetic Quote Co', 'STOCK', 'USD')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO prices (asset_id, ts, trade_date, price, currency, source) VALUES "
                "(901, '2026-03-12 22:00:00+00:00', '2026-03-12', 51.0, 'USD', 'b_market'), "
                "(901, '2026-03-12 21:00:00+00:00', '2026-03-12', 50.0, 'USD', 'a_market'), "
                "(901, '2026-03-11 22:00:00+00:00', '2026-03-11', 49.0, 'USD', 'a_market'), "
                "(901, '2026-03-20 22:00:00+00:00', '2026-03-20', 60.0, 'USD', 'a_market')"
            )
        )
    db = Session(bind=db_engine)
    try:
        quote = latest_quotes(db, date(2026, 3, 15), frozenset({901}))[901]
    finally:
        db.close()
    assert (quote["price"], quote["source"], str(quote["trade_date"])[:10]) == (51.0, "b_market", "2026-03-12")

