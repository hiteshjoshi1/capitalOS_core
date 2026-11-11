"""Money in valuation is Decimal (#360, D-106): exact sums inside, floats at the edge.

- ``app.valuation.money``: D() keeps a float's shortest repr (0.1 stays 0.1), floats()
  turns nested Decimals into floats for the API.
- The canonical readers return Decimal money (NUMERIC, never DOUBLE PRECISION).
- On the synthetic household (tests/valuation_household.py), every scenario: net worth
  is exactly the sum of its parts, and the month bridge (before its float edge) adds up
  to the change exactly: start + lines + unexplained = end, each line = its parts.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.portfolio.canonical_reads import canonical_account_balance_rows, canonical_position_rows_by_legacy_account
from app.valuation import bridge as valuation_bridge
from app.valuation.clock import _anchor_ts, _parse_month
from app.valuation.context import valuation_context
from app.valuation.facts import _networth_components
from app.valuation.money import D, dsum, floats
from tests.valuation_household import SCENARIOS, USER_A, build_scenario, household_env

MONTHS = {"mid": ("2026-03", "2026-02"), "first": ("2026-04", "2026-03"), "first_us": ("2026-03", "2026-02")}


def test_d_keeps_a_floats_shortest_repr():
    assert D(0.1) == Decimal("0.1")
    assert D(0.1) + D(0.2) == Decimal("0.3")  # floats: 0.30000000000000004
    assert D(None) == 0 and D("") == 0 and D(float("nan")) == 0
    assert D("12.50") == Decimal("12.50") and D(3) == 3 and D(Decimal("1.5")) == Decimal("1.5")
    assert dsum([0.1, 0.2, Decimal("0.3"), None]) == Decimal("0.6")


def test_floats_converts_nested_decimals_only():
    out = floats({"a": Decimal("1.5"), "b": [Decimal("2"), {"c": (Decimal("0.25"), "x")}], "d": None, "e": 3})
    assert out == {"a": 1.5, "b": [2.0, {"c": (0.25, "x")}], "d": None, "e": 3}
    assert isinstance(out["a"], float) and isinstance(out["b"][0], float) and isinstance(out["e"], int)


@pytest.mark.parametrize("scenario", sorted(MONTHS))
def test_canonical_readers_return_decimal_money(scenario: str, db_engine, monkeypatch):
    household_env(monkeypatch, SCENARIOS[scenario])
    build_scenario(db_engine, scenario)
    anchor = _anchor_ts(_parse_month(MONTHS[scenario][1])).date()
    db = Session(bind=db_engine)
    try:
        positions = canonical_position_rows_by_legacy_account(
            db, current_user_id=USER_A, anchor_date=anchor, include_nav_accounts=True
        )
        balances = canonical_account_balance_rows(db, current_user_id=USER_A, anchor_date=anchor)
    finally:
        db.close()
    assert positions and balances
    for row in positions:
        for key in ("quantity", "snapshot_market_value_base", "avg_cost"):
            assert row[key] is None or isinstance(row[key], Decimal), (key, row[key])
    for row in balances:
        assert isinstance(row["balance_local"], Decimal) and isinstance(row["balance_base"], Decimal)


def _lines_and_parts(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [*result["lines"], result["unexplained"]]


@pytest.mark.parametrize("base", ("SGD", "USD"))
@pytest.mark.parametrize("scenario", sorted(MONTHS))
def test_net_worth_and_the_bridge_add_up_exactly(scenario: str, base: str, client: TestClient, db_engine, monkeypatch):
    household_env(monkeypatch, SCENARIOS[scenario])
    build_scenario(db_engine, scenario)
    db = Session(bind=db_engine)
    try:
        for month in MONTHS[scenario]:
            where = f"{scenario} {base} {month}"
            month_start = _parse_month(month)
            nw = _networth_components(db, _anchor_ts(month_start), base, USER_A)
            for key in ("total", "cash", "stocks_funds", "crypto", "liabilities"):
                assert isinstance(nw[key], Decimal), (where, key)
            assert nw["total"] == nw["cash"] + nw["stocks_funds"] + nw["crypto"] - nw["liabilities"], where

            # Before the float edge (float_edge keeps the undecorated function as __wrapped__), in the
            # user's timezone and one frozen "now", as the API runs it (#395).
            with valuation_context(db, USER_A):
                exact = valuation_bridge.month_bridge.__wrapped__(db, USER_A, month, month_start, base, movers_limit=20)
            amounts = [D(line["amount"]) for line in _lines_and_parts(exact)]
            assert all(isinstance(line["amount"], Decimal) for line in _lines_and_parts(exact)), where
            assert D(exact["start"]["value"]) + dsum(amounts) == D(exact["end"]["value"]), where
            for line in _lines_and_parts(exact):
                if line["parts"]:
                    assert dsum(p["amount"] for p in line["parts"]) == D(line["amount"]), (where, line["key"])
            # ... and the API's floats are those numbers, the live month included (#395).
            api = client.get(f"/dashboard/month-bridge?month={month}&base_currency={base}&limit=20").json()
            assert api["end"]["value"] == float(exact["end"]["value"]), where
            assert [line["amount"] for line in api["lines"]] == [float(line["amount"]) for line in exact["lines"]], where
    finally:
        db.close()


def test_scenarios_cover_the_months():
    assert set(MONTHS) <= set(SCENARIOS)
    assert all(date.fromisoformat(m + "-01") for months in MONTHS.values() for m in months)


def test_a_direct_call_needs_the_users_timezone_for_the_live_month(client: TestClient, db_engine, monkeypatch):
    """#395: 1 Apr 10:00 in Singapore is still 31 Mar in New York. For the first_us household
    (home timezone New York) March is the open, live month in the API; a direct call in the
    app's timezone saw it as closed. ``valuation_context`` makes the direct call match."""
    from tests.valuation_household import SGT

    household_env(monkeypatch, datetime(2026, 4, 1, 10, 0, tzinfo=SGT))
    build_scenario(db_engine, "first_us")
    month_start = _parse_month("2026-03")
    db = Session(bind=db_engine)
    try:
        bare = valuation_bridge.month_bridge.__wrapped__(db, USER_A, "2026-03", month_start, "SGD")
        with valuation_context(db, USER_A):
            scoped = valuation_bridge.month_bridge.__wrapped__(db, USER_A, "2026-03", month_start, "SGD")
    finally:
        db.close()
    api = client.get("/dashboard/month-bridge?month=2026-03&base_currency=SGD").json()
    assert bare["is_live"] is False  # Singapore: March is over
    assert api["is_live"] is True and scoped["is_live"] is True  # New York: still March
    assert float(scoped["end"]["value"]) == api["end"]["value"]
    assert scoped["end"]["as_of"] == api["end"]["as_of"] and scoped["start"]["as_of"] == api["start"]["as_of"]
