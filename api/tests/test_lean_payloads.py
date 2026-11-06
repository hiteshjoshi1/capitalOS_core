"""Lean page payloads (#149): each lean endpoint returns exactly what the page used to
read from the full one, on the synthetic household (tests/valuation_household.py),
in every scenario, for the open month, the last completed month and an older one,
in two base currencies.

- /spending/cash-flow-trend   = /spending/cash-flow-detail's analytics.trend (History)
- /crypto/stablecoins         = /crypto/summary's USDC/USDT top_holdings (Cash)
- /dashboard/risk-summary     = /dashboard/summary's net_worth and top_holdings, each row
                                cut to the fields the Risk page reads (Risk)

(/alerts/notifications/count is checked against /alerts/notifications in test_alerts.py.)

The shared valuation cache is cleared before every call, so a lean answer is computed,
not served from what the full endpoint just cached.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.routers.crypto import STABLECOIN_SYMBOLS
from app.schemas.crypto import StablecoinHolding
from app.schemas.dashboard import RiskHolding
from app.valuation_cache import clear_shared_cache
from tests.valuation_household import SCENARIOS, build_scenario, household_env

MONTHS = {
    # scenario: (open month, last completed month, an older month)
    "mid": ("2026-03", "2026-02", "2026-01"),
    "first": ("2026-04", "2026-03", "2026-01"),
    "first_us": ("2026-03", "2026-02", "2026-01"),
}
CURRENCIES = ("SGD", "USD")
FX_FIELDS = ("fx_incomplete", "fx_missing_currencies", "fx_stale_currencies")


@pytest.fixture(params=sorted(SCENARIOS))
def household(request, client: TestClient, db_engine, monkeypatch):
    scenario = request.param
    household_env(monkeypatch, SCENARIOS[scenario])
    build_scenario(db_engine, scenario)
    return scenario, client


def _get(client: TestClient, path: str) -> dict:
    clear_shared_cache()
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.text)
    return resp.json()


def _cases(scenario: str):
    for month in MONTHS[scenario]:
        for currency in CURRENCIES:
            yield month, currency


def test_cash_flow_trend_equals_cash_flow_detail_trend(household):
    scenario, client = household
    non_zero = 0
    for month, ccy in _cases(scenario):
        lean = _get(client, f"/spending/cash-flow-trend?month={month}&base_currency={ccy}")
        full = _get(client, f"/spending/cash-flow-detail?month={month}&base_currency={ccy}")
        assert lean["trend"] == full["analytics"]["trend"], (scenario, month, ccy)
        assert (lean["month"], lean["base_currency"]) == (full["month"], full["base_currency"])
        assert len(lean["trend"]) == 6
        non_zero += sum(1 for point in lean["trend"] if point["inflows"] or point["outflows"])
    assert non_zero, "the household has cash flow, so the comparison isn't vacuous"


def test_stablecoins_equal_crypto_summary_stablecoin_rows(household):
    scenario, client = household
    fields = list(StablecoinHolding.model_fields)
    seen = 0
    for month, ccy in _cases(scenario):
        lean = _get(client, f"/crypto/stablecoins?month={month}&base_currency={ccy}")
        full = _get(client, f"/crypto/summary?month={month}&base_currency={ccy}")
        expected = [
            {field: row.get(field) for field in fields}
            for row in full["top_holdings"]
            if row["symbol"].upper() in STABLECOIN_SYMBOLS
        ]
        assert lean["holdings"] == expected, (scenario, month, ccy)
        # The Cash page's card total: the same sum, in the same order.
        assert lean["total_base"] == sum(row["value_base"] for row in expected)
        for key in ("month", "is_live", "as_of", "base_currency", *FX_FIELDS):
            assert lean[key] == full[key], (scenario, month, ccy, key)
        assert lean["symbols"] == list(STABLECOIN_SYMBOLS)
        seen += len(expected)
    assert seen, "the household holds stablecoins, so the comparison isn't vacuous"


def test_risk_summary_equals_dashboard_summary_fields(household):
    scenario, client = household
    holdings = 0
    for month, ccy in _cases(scenario):
        lean = _get(client, f"/dashboard/risk-summary?month={month}&base_currency={ccy}")
        # The Risk page's own call (it asked for the comparisons too).
        full = _get(client, f"/dashboard/summary?month={month}&base_currency={ccy}&compare=prev_month,prev_year")
        for key in ("as_of_month", "base_currency", "snapshot_day", "is_live", "net_worth", *FX_FIELDS):
            assert lean[key] == full[key], (scenario, month, ccy, key)
        # #241: the net worth the shares divide by is the one at the positions'
        # anchor: /summary's live current_net_worth, or a past month's net_worth.
        expected_view = full["current_net_worth"] if full["is_live"] else full["net_worth"]
        assert lean["view_net_worth"] == pytest.approx(expected_view), (scenario, month, ccy)
        assert lean["basis"] == ("live" if full["is_live"] else "month_end"), (scenario, month, ccy)
        fields = list(RiskHolding.model_fields)
        assert lean["top_holdings"] == [{field: row[field] for field in fields} for row in full["top_holdings"]], (
            scenario,
            month,
            ccy,
        )
        holdings += len(lean["top_holdings"])
    assert holdings, "the household has positions, so the comparison isn't vacuous"


def test_lean_payloads_are_smaller(household):
    """The point of #149: each lean answer is a fraction of the full one."""
    scenario, client = household
    month = MONTHS[scenario][0]
    pairs = (
        ("/spending/cash-flow-trend", "/spending/cash-flow-detail"),
        ("/crypto/stablecoins", "/crypto/summary"),
        ("/dashboard/risk-summary", "/dashboard/summary"),
    )
    for lean_path, full_path in pairs:
        clear_shared_cache()
        lean = client.get(f"{lean_path}?month={month}&base_currency=SGD")
        clear_shared_cache()
        full = client.get(f"{full_path}?month={month}&base_currency=SGD&compare=prev_month,prev_year")
        assert len(lean.content) < len(full.content), (lean_path, len(lean.content), len(full.content))
