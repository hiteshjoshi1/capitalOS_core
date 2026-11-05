"""Valuation goldens (#142): fixed inputs -> the exact numbers of the main
endpoints, so moving the valuation code (#143) can't change a figure unnoticed.

Inputs: the synthetic household in tests/valuation_household.py, at two frozen
instants ("mid": a normal day in an open month, with past months to browse;
"first": 06:00 SGT on the 1st, still the 31st in UTC). Outputs: one golden JSON
per scenario under tests/golden/valuation/. Regenerate only deliberately:
``UPDATE_GOLDEN=1 pytest tests/test_valuation_golden.py`` (or ``make golden-update``),
then review the diff. See tests/valuation_golden.py.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.valuation_golden import check_golden
from tests.valuation_household import SCENARIOS, build_scenario, household_env

# Endpoints per scenario, as the web app calls them. The History timeline is
# read after "Generate history" (the backfill), like a user's first visit.
_MID = [
    "/dashboard/bootstrap?month=2026-03&base_currency=SGD",
    "/dashboard/summary?month=2026-03&base_currency=SGD&compare=prev_month,prev_year",
    "/dashboard/summary?month=2026-02&base_currency=SGD&compare=prev_month,prev_year",
    "/dashboard/summary?month=2026-01&base_currency=SGD&compare=prev_month",
    "/dashboard/summary?month=2026-03&base_currency=USD&compare=prev_month",
    "/dashboard/summary?month=2026-03&base_currency=SGD&skip_networth=true",
    "/dashboard/net-worth-change?month=2026-03&base_currency=SGD",
    "/dashboard/net-worth-change?month=2026-02&base_currency=SGD",
    "/dashboard/net-worth-since-update?base_currency=SGD",
    "/dashboard/net-worth-timeline?months=6&base_currency=SGD",
    "/dashboard/net-worth-timeline/2026-02/movers?base_currency=SGD",
    "/dashboard/cash-deposits?month=2026-03&base_currency=SGD",
    "/dashboard/cash-deposits?month=2026-02&base_currency=SGD",
    "/dashboard/stock-holdings?month=2026-03&base_currency=SGD",
    "/dashboard/stock-holdings?month=2026-02&base_currency=SGD",
    "/dashboard/platform-allocation?month=2026-03&base_currency=SGD",
    "/dashboard/stock-exposure?month=2026-03&base_currency=SGD",
    "/dashboard/geography-exposure?month=2026-03&base_currency=SGD",
    "/dashboard/geography-exposure?month=2026-02&base_currency=SGD",
    "/crypto/summary?month=2026-03&base_currency=SGD",
    "/crypto/summary?month=2026-02&base_currency=SGD",
    "/dividends/summary?from_month=2026-01&to_month=2026-03&base_currency=SGD",
    "/dividends/by-company?from_month=2026-01&to_month=2026-03&base_currency=SGD",
    "/dividends/history?symbol=AAPL&from_month=2026-01&to_month=2026-03&base_currency=SGD",
    "/dividends/history?symbol=RELIANCE&from_month=2026-01&to_month=2026-03&base_currency=SGD",
    "/dividends/expected/overview?from_month=2026-03&to_month=2026-05&base_currency=SGD",
    "/spending/summary?month=2026-02&base_currency=SGD",
    "/spending/cash-flow-detail?month=2026-02&base_currency=SGD",
    "/spending/cash-flow-detail?month=2026-03&base_currency=SGD",
]

_FIRST = [
    "/dashboard/bootstrap?month=2026-04&base_currency=SGD",
    "/dashboard/summary?month=2026-04&base_currency=SGD&compare=prev_month,prev_year",
    "/dashboard/summary?month=2026-03&base_currency=SGD&compare=prev_month,prev_year",
    "/dashboard/net-worth-change?month=2026-04&base_currency=SGD",
    "/dashboard/net-worth-since-update?base_currency=SGD",
    "/dashboard/net-worth-timeline?months=6&base_currency=SGD",
    "/dashboard/cash-deposits?month=2026-04&base_currency=SGD",
    "/dashboard/cash-deposits?month=2026-03&base_currency=SGD",
    "/dashboard/stock-holdings?month=2026-04&base_currency=SGD",
    "/dashboard/geography-exposure?month=2026-04&base_currency=SGD",
    "/crypto/summary?month=2026-04&base_currency=SGD",
]

# The "first" instant for a New York household (#202): still 31 March there,
# so March is the open month (live) and February the latest completed month.
_FIRST_US = [
    "/dashboard/bootstrap?month=2026-03&base_currency=SGD",
    "/dashboard/summary?month=2026-03&base_currency=SGD&compare=prev_month,prev_year",
    "/dashboard/summary?month=2026-02&base_currency=SGD&compare=prev_month,prev_year",
    "/dashboard/net-worth-change?month=2026-03&base_currency=SGD",
    "/dashboard/net-worth-since-update?base_currency=SGD",
    "/dashboard/net-worth-timeline?months=6&base_currency=SGD",
    "/dashboard/cash-deposits?month=2026-03&base_currency=SGD",
    "/dashboard/cash-deposits?month=2026-02&base_currency=SGD",
    "/dashboard/stock-holdings?month=2026-03&base_currency=SGD",
    "/dashboard/stock-holdings?month=2026-02&base_currency=SGD",
    "/dashboard/geography-exposure?month=2026-03&base_currency=SGD",
    "/crypto/summary?month=2026-03&base_currency=SGD",
    "/crypto/summary?month=2026-02&base_currency=SGD",
]

ENDPOINTS = {"mid": _MID, "first": _FIRST, "first_us": _FIRST_US}


def collect(client: TestClient, paths: list[str]) -> dict:
    out = {}
    for path in paths:
        if path.startswith("/dashboard/net-worth-timeline?"):
            backfill = client.post("/dashboard/net-worth-timeline/backfill?months=6&base_currency=SGD")
            assert backfill.status_code == 200, backfill.text
        resp = client.get(path)
        assert resp.status_code == 200, (path, resp.text)
        out[path] = resp.json()
    return out


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_valuation_golden(scenario: str, client: TestClient, db_engine, monkeypatch):
    now = SCENARIOS[scenario]
    household_env(monkeypatch, now)
    build_scenario(db_engine, scenario)
    check_golden(
        scenario,
        {"scenario": scenario, "now": now.isoformat(), "responses": collect(client, ENDPOINTS[scenario])},
    )
