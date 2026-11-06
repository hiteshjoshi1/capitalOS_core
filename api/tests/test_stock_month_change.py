"""Stocks: each holding's change vs the compare month-end (#251), split into price,
quantity and FX by Overview's bridge split (D-60), on the synthetic household
(tests/valuation_household.py).

- For every golden instant (and SNAPSHOT_DAY=5), base SGD and USD, the open month
  and past months: the rows' changes (holdings held now, plus those sold since)
  add up to the bridge's stocks parts (markets: stocks, FX: stocks, and the
  stocks' quantity, unsplit and gap parts), and with what the statement totals
  hold beyond the holdings to the Stocks headline's change, which is the change
  of the bridge's stocks_funds component.
- Each row: change = price + quantity + FX + unsplit = its value - its compare value.
- A holding sold during the month is listed at 0 as "sold": its change is all
  quantity (a sale), never a price or FX loss, and the bridge lists the same trade.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.valuation_household import INFY, SCENARIOS, SGT, SHAREKHAN, build_household, build_scenario, fx, household_env

TOL = 0.01
MONTHS: dict[str, tuple[str, tuple[str, ...]]] = {
    "mid": ("2026-03", ("2026-02", "2026-01", "2025-12")),
    "first": ("2026-04", ("2026-03", "2026-02")),
    "first_us": ("2026-03", ("2026-02", "2026-01")),
    "early_snapshot_day": ("2026-03", ("2026-02", "2026-01")),
}
EARLY_SNAPSHOT_DAY_NOW = datetime(2026, 3, 3, 10, 0, tzinfo=SGT)
EFFECTS = ("price_effect", "quantity_effect", "fx_effect", "unsplit")


def _get(client: TestClient, path: str) -> dict[str, Any]:
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.text)
    return resp.json()


def _stocks(client: TestClient, month: str, base: str = "SGD") -> dict[str, Any]:
    return _get(client, f"/dashboard/stock-holdings?month={month}&base_currency={base}")


def _bridge(client: TestClient, month: str, base: str = "SGD") -> dict[str, Any]:
    return _get(client, f"/dashboard/month-bridge?month={month}&base_currency={base}&limit=20")


def _part(bridge: dict[str, Any], line_key: str, part_key: str) -> float:
    line = next(line for line in [*bridge["lines"], bridge["unexplained"]] if line["key"] == line_key)
    return next((part["amount"] for part in line["parts"] if part["key"] == part_key), 0.0)


def _rows(stocks: dict[str, Any]) -> list[dict[str, Any]]:
    return [*stocks["top_holdings"], *stocks["sold_holdings"]]


def _check_month(client: TestClient, month: str, base: str, live: bool, where: str) -> None:
    stocks, bridge = _stocks(client, month, base), _bridge(client, month, base)
    assert stocks["is_live"] is live and bridge["is_live"] is live, where
    assert stocks["compare_month"] == bridge["start"]["month"], where
    assert stocks["compare_boundary_at"] == bridge["start"]["boundary_at"], where
    rows = _rows(stocks)
    for row in rows:
        change = row["month_change"]
        assert change is not None, (where, row["symbol"])
        assert change["abs"] == pytest.approx(sum(change[key] for key in EFFECTS), abs=1e-6), (where, row["symbol"])
        assert change["abs"] == pytest.approx(change["end_value"] - change["compare_value"], abs=1e-6), (where, row["symbol"])
        assert change["end_value"] == pytest.approx(row["value"], abs=TOL), (where, row["symbol"])
        assert change["compare_month"] == stocks["compare_month"], where
        assert change["baseline_missing"] is stocks["stock_snapshot_missing"], where
        assert change["side"] in {"held", "new", "sold"}, where
        if change["side"] == "sold":
            # A sale is a change in quantity, not a loss.
            assert row["value"] == 0.0 and change["quantity_effect"] == pytest.approx(-change["compare_value"]), where
            assert change["price_effect"] == 0.0 and change["fx_effect"] == 0.0, where
        if change["side"] == "new":
            assert change["compare_value"] == 0.0 and change["pct"] is None, where

    # The rows add up to the bridge's stocks parts.
    total = stocks["month_change_total"]
    assert sum(r["month_change"]["price_effect"] for r in rows) == pytest.approx(_part(bridge, "markets", "stocks"), abs=TOL), where
    assert sum(r["month_change"]["fx_effect"] for r in rows) == pytest.approx(_part(bridge, "fx", "stocks"), abs=TOL), where
    for key in EFFECTS:
        assert sum(r["month_change"][key] for r in rows) == pytest.approx(total[key], abs=TOL), (where, key)
    stock_trades = {t["symbol"]: t["amount"] for t in bridge["trades"] if t["asset_class"] in {"STOCK", "FUND"}}
    for row in rows:
        if abs(row["month_change"]["quantity_effect"]) >= 1.0:
            assert stock_trades[row["symbol"]] == pytest.approx(row["month_change"]["quantity_effect"], abs=TOL), where
    rows_change = sum(r["month_change"]["abs"] for r in rows)
    assert rows_change + total["not_in_holdings"] == pytest.approx(total["abs"], abs=TOL), where
    # ... and with the totals beyond the holdings, to the headline's change: the
    # bridge's stocks_funds from start to end (one number, D-58).
    headline_change = stocks["stock_current_total"] - stocks["stock_snapshot_total"]
    assert total["abs"] == pytest.approx(headline_change, abs=TOL), where
    bridge_change = bridge["end"]["net_worth"]["stocks_funds"] - bridge["start"]["net_worth"]["stocks_funds"]
    assert headline_change == pytest.approx(bridge_change, abs=TOL), where
    assert total["compare_value"] == pytest.approx(stocks["stock_snapshot_total"], abs=TOL), where


@pytest.mark.parametrize("base", ("SGD", "USD"))
@pytest.mark.parametrize("scenario", sorted(MONTHS))
def test_rows_add_up_to_the_bridge(scenario: str, base: str, client: TestClient, db_engine, monkeypatch):
    if scenario == "early_snapshot_day":
        household_env(monkeypatch, EARLY_SNAPSHOT_DAY_NOW)
        monkeypatch.setenv("SNAPSHOT_DAY", "5")
        build_household(db_engine, now=EARLY_SNAPSHOT_DAY_NOW)
    else:
        household_env(monkeypatch, SCENARIOS[scenario])
        build_scenario(db_engine, scenario)
    live_month, past_months = MONTHS[scenario]
    for month, live in ((live_month, True), *((m, False) for m in past_months)):
        _check_month(client, month, base, live, f"{scenario} {base} {month}")


@pytest.fixture
def mid(client: TestClient, db_engine, monkeypatch):
    household_env(monkeypatch, SCENARIOS["mid"])
    build_scenario(db_engine, "mid")
    return client


def test_open_month_rows_by_hand(mid: TestClient):
    """March 2026, live on 18 March: AAPL 20 @190 (27 Feb statement) -> 25, quoted 205."""
    stocks = _stocks(mid, "2026-03")
    aapl = next(row for row in stocks["top_holdings"] if row["symbol"] == "AAPL")["month_change"]
    usd, fx_feb = fx(date(2026, 3, 18), "USD"), fx(date(2026, 2, 27), "USD")
    assert aapl["side"] == "held"
    assert aapl["price_effect"] == pytest.approx(20 * (205.0 - 190.0) * usd, abs=TOL)
    assert aapl["fx_effect"] == pytest.approx(20 * 190.0 * (usd - fx_feb), abs=TOL)
    assert aapl["quantity_effect"] == pytest.approx(5 * 205.0 * usd, abs=TOL)
    assert (aapl["start_quantity"], aapl["end_quantity"]) == (20.0, 25.0)
    assert (aapl["start_price"], aapl["end_price"], aapl["price_currency"]) == (190.0, 205.0, "USD")
    assert aapl["start_rate"] == pytest.approx(fx_feb, rel=1e-6) and aapl["end_rate"] == pytest.approx(usd, rel=1e-6)
    assert aapl["compare_value"] == pytest.approx(20 * 190.0 * fx_feb, abs=TOL)
    assert aapl["pct"] == pytest.approx(aapl["abs"] / aapl["compare_value"])
    assert stocks["sold_holdings"] == []


def test_first_month_holdings_are_new(mid: TestClient):
    """January 2026 vs December 2025, before any holding: every row is new."""
    stocks = _stocks(mid, "2026-01")
    assert stocks["top_holdings"]
    for row in stocks["top_holdings"]:
        change = row["month_change"]
        assert change["side"] == "new" and change["pct"] is None
        assert change["quantity_effect"] == pytest.approx(row["value"], abs=TOL)


def test_a_sale_reads_as_a_sale(mid: TestClient, db_engine):
    """INFY sold at Sharekhan before the 15 March statement: listed at 0, "sold",
    its change all quantity; the bridge lists the same sale."""
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM portfolio_position_snapshots WHERE legacy_account_id = :a AND report_date = '2026-03-15' "
                "AND broker_instrument_id IN (SELECT id FROM broker_instruments WHERE asset_id = :asset)"
            ),
            {"a": SHAREKHAN, "asset": INFY},
        )
    for base in ("SGD", "USD"):
        _check_month(mid, "2026-03", base, True, f"sold {base}")
    stocks = _stocks(mid, "2026-03")
    assert "INFY" not in {row["symbol"] for row in stocks["top_holdings"]}
    [infy] = stocks["sold_holdings"]
    change = infy["month_change"]
    assert infy["symbol"] == "INFY" and infy["value"] == 0.0 and infy["platform"] == "SHAREKHAN"
    assert change["side"] == "sold" and change["end_quantity"] is None and change["start_quantity"] == 20.0
    assert change["start_price"] == 1580.0 and change["price_currency"] == "INR"
    assert change["compare_value"] == pytest.approx(20 * 1580.0 * change["start_rate"], abs=TOL)
    assert change["abs"] == pytest.approx(-change["compare_value"])
    assert change["quantity_effect"] == pytest.approx(change["abs"])
    trade = next(t for t in _bridge(mid, "2026-03")["trades"] if t["symbol"] == "INFY")
    assert trade["side"] == "sold" and trade["amount"] == pytest.approx(change["quantity_effect"], abs=TOL)
