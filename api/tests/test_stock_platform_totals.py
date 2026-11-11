"""#396 (U7): cost basis and unrealised P&L per platform on the Stocks page."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.valuation.pages import _stock_platform_totals


def _row(platform, value, quantity, avg_cost, price):
    return {"platform": platform, "value": value, "quantity": quantity, "avg_cost": avg_cost, "latest_price": price}


def test_platform_totals_add_up_the_rows_pnl_at_each_rows_rate():
    rows = [
        # SGD stock: 10 x (12 - 10) = +20; cost 100.
        _row("IBKR", Decimal("120"), Decimal("10"), Decimal("10"), Decimal("12")),
        # USD stock valued at 1.35 SGD/USD: 5 x (20 - 16) = +20 USD = +27 SGD; value 135, cost 108.
        _row("IBKR", Decimal("135"), Decimal("5"), Decimal("16"), Decimal("20")),
        _row("DBS_VICKERS", Decimal("50"), Decimal("1"), Decimal("60"), Decimal("50")),
    ]
    totals = _stock_platform_totals(rows)

    assert [t["platform"] for t in totals] == ["IBKR", "DBS_VICKERS"]
    ibkr = totals[0]
    assert ibkr["value"] == Decimal("255")
    assert ibkr["unrealised_pnl"] == Decimal("47")
    assert ibkr["cost_basis"] == Decimal("208")
    assert ibkr["unrealised_pnl_pct"] == Decimal("47") / Decimal("208") * 100
    assert ibkr["positions"] == 2 and ibkr["positions_without_cost"] == 0
    dbs = totals[1]
    assert dbs["unrealised_pnl"] == Decimal("-10")
    assert dbs["cost_basis"] == Decimal("60")


def test_a_row_without_a_purchase_price_is_counted_apart_not_as_zero_cost():
    totals = _stock_platform_totals([
        _row("IBKR", Decimal("100"), Decimal("10"), None, Decimal("10")),
        _row("IBKR", Decimal("40"), Decimal("4"), Decimal("5"), Decimal("10")),
    ])
    (ibkr,) = totals
    assert ibkr["value"] == Decimal("140")
    assert ibkr["unrealised_pnl"] == Decimal("20")
    assert ibkr["cost_basis"] == Decimal("20")
    assert ibkr["positions"] == 2
    assert ibkr["positions_without_cost"] == 1
    assert ibkr["value_without_cost"] == Decimal("100")


def test_no_cost_basis_means_no_percentage():
    (only,) = _stock_platform_totals([_row("IBKR", Decimal("100"), None, None, None)])
    assert only["unrealised_pnl_pct"] is None
    assert only["cost_basis"] == 0


def test_stock_holdings_response_carries_platform_totals_matching_its_rows(client: TestClient, seed_dashboard_data):
    data = client.get("/dashboard/stock-holdings?month=2026-02&base_currency=SGD").json()
    assert "platform_totals" in data
    rows = data["top_holdings"]
    for total in data["platform_totals"]:
        mine = [r for r in rows if (r.get("platform") or "UNKNOWN") == total["platform"]]
        assert total["positions"] == len(mine)
        assert total["value"] == pytest.approx(sum(r["value"] for r in mine), abs=1e-6)
        assert total["cost_basis"] + total["unrealised_pnl"] + total["value_without_cost"] == pytest.approx(total["value"], abs=1e-6)
