"""#224: missing data never reads as a value. A comparison with no data behind
it says so (``baseline_missing`` / ``*_snapshot_missing``) instead of passing a
zero off as a real baseline, and every stock holding says where its price comes
from. Synthetic household (tests/valuation_household.py); every number is made up.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import valuation_cache
from app.valuation.history import baseline_missing
from tests.valuation_household import RELIANCE, SCENARIOS, build_household, household_env

MID = SCENARIOS["mid"]  # 18 March 2026: March is live, February closed; data starts Dec 2025


@pytest.fixture()
def household(client: TestClient, db_engine, monkeypatch):
    household_env(monkeypatch, MID)
    build_household(db_engine, now=MID)
    return client


def _get(client: TestClient, path: str) -> dict:
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.text)
    return resp.json()


def test_baseline_missing_rule():
    assert baseline_missing(None, 0.0) is True
    # A real zero (data exists, the value is zero) is not "missing".
    assert baseline_missing("2026-02-01", 0.0) is False
    # Something to compare against (e.g. crypto without a canonical snapshot date).
    assert baseline_missing(None, 1250.0) is False


def test_net_worth_change_flags_a_year_with_no_data(household):
    summary = _get(household, "/dashboard/summary?month=2026-03&base_currency=SGD&compare=prev_month,prev_year")
    live = summary["current_net_worth_change"]
    # A year back (Feb 2025) predates every statement: no comparison, not +100%.
    year = live["vs_prev_year"]
    assert year["compare_month"] == "2025-02"
    assert year["baseline_missing"] is True
    assert year["compare_value"] == 0
    assert year["pct"] is None
    # Last month has data: a real baseline, and abs = current - compare_value.
    month = live["vs_prev_month"]
    assert month["baseline_missing"] is False
    assert month["compare_value"] > 0
    assert month["abs"] == pytest.approx(summary["current_net_worth"]["total"] - month["compare_value"], abs=0.01)
    assert month["pct"] == pytest.approx(month["abs"] / month["compare_value"])

    snapshot = summary["net_worth_change"]
    assert snapshot["vs_prev_year"]["baseline_missing"] is True
    assert snapshot["vs_prev_month"]["baseline_missing"] is False
    for component in summary["net_worth_component_change"].values():
        assert "baseline_missing" in component
        assert "compare_value" in component


def test_net_worth_change_endpoint_and_since_update_carry_the_flag(household):
    change = _get(household, "/dashboard/net-worth-change?month=2026-01&base_currency=SGD")["net_worth_change"]
    # Dec 2025 has the first bank balances: a real baseline.
    assert change["vs_prev_month"]["compare_month"] == "2025-12"
    assert change["vs_prev_month"]["baseline_missing"] is False
    assert change["vs_prev_year"]["baseline_missing"] is True

    since = _get(household, "/dashboard/net-worth-since-update?base_currency=SGD")
    assert since["net_worth_change"]["baseline_missing"] is False
    assert since["net_worth_change"]["compare_value"] > 0


def test_stock_holdings_flag_a_compare_month_without_stock_data(household):
    # January vs December: December has bank cash but no holdings yet.
    january = _get(household, "/dashboard/stock-holdings?month=2026-01&base_currency=SGD")
    assert january["compare_month"] == "2025-12"
    assert january["stock_snapshot_total"] == 0
    assert january["stock_snapshot_missing"] is True
    march = _get(household, "/dashboard/stock-holdings?month=2026-03&base_currency=SGD")
    assert march["stock_snapshot_missing"] is False
    assert march["stock_snapshot_total"] > 0


def test_cash_deposits_flag_a_compare_month_without_cash_data(household):
    december = _get(household, "/dashboard/cash-deposits?month=2025-12&base_currency=SGD")
    assert december["snapshot_total"] == 0
    assert december["snapshot_missing"] is True
    march = _get(household, "/dashboard/cash-deposits?month=2026-03&base_currency=SGD")
    assert march["snapshot_missing"] is False


def test_crypto_summary_flags_a_compare_month_without_wallet_data(household):
    january = _get(household, "/crypto/summary?month=2026-01&base_currency=SGD")
    assert january["snapshot_missing"] is True
    assert january["snapshot_missing_reason"] == "no_data"
    february = _get(household, "/crypto/summary?month=2026-02&base_currency=SGD")
    assert february["snapshot_missing"] is False
    assert february["snapshot_missing_reason"] is None


def test_price_basis_and_no_live_price_count_on_the_live_month(household, db_engine):
    live = _get(household, "/dashboard/stock-holdings?month=2026-03&base_currency=SGD")
    assert live["quote_stale_days"] == 3
    assert {h["price_basis"] for h in live["top_holdings"]} == {"quote"}
    assert live["quote_freshness_summary"]["no_live_price"] == 0

    # RELIANCE loses its March quotes: its only usable price is the uploaded
    # statement (the #222 case), so it counts as "no live price".
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM prices WHERE asset_id = :a AND trade_date >= '2026-03-01'"), {"a": RELIANCE})
    valuation_cache.clear_shared_cache()
    live = _get(household, "/dashboard/stock-holdings?month=2026-03&base_currency=SGD")
    reliance = next(h for h in live["top_holdings"] if h["symbol"] == "RELIANCE")
    assert reliance["price_basis"] == "statement"
    assert reliance["latest_trade_date"].startswith("2026-03-15")
    assert live["quote_freshness_summary"]["no_live_price"] == 1


def test_past_month_has_no_live_price_count(household):
    past = _get(household, "/dashboard/stock-holdings?month=2026-02&base_currency=SGD")
    assert past["is_live"] is False
    assert past["quote_freshness_summary"]["no_live_price"] is None
    assert {h["price_basis"] for h in past["top_holdings"]} == {"statement"}
