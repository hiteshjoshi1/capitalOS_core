from fastapi.testclient import TestClient
import pytest


def test_dashboard_invalid_month(client: TestClient):
    resp = client.get("/dashboard/summary?month=2026-13")
    assert resp.status_code == 400
    assert "Invalid month format" in resp.json()["detail"]


def test_dashboard_summary_basic(client: TestClient, seed_dashboard_data):
    resp = client.get("/dashboard/summary?month=2026-02&compare=prev_month")
    assert resp.status_code == 200
    data = resp.json()

    assert data["as_of_month"] == "2026-02"
    assert data["base_currency"] == "SGD"
    assert data["net_worth"]["total"] == 100000.0
    assert data["cash_flow"]["income"] == 5999.0
    assert data["cash_flow"]["expenses"] == 2100.0
    assert data["cash_flow"]["net"] == 3899.0
    assert data["cash_flow"]["savings_rate"] == pytest.approx(3899.0 / 5999.0, rel=1e-4)

    top = data["top_holdings"]
    assert len(top) == 3
    assert top[0]["symbol"] == "AAPL"

    changes = data["net_worth_change"]["vs_prev_month"]
    assert changes["abs"] == 10000.0
    assert changes["pct"] == 10000.0 / 90000.0


def test_platform_allocation(client: TestClient, seed_dashboard_data):
    resp = client.get("/dashboard/platform-allocation?month=2026-02")
    assert resp.status_code == 200
    data = resp.json()

    assert data["total"] == 100000.0
    assert data["as_of"] is not None

    items = data["items"]
    assert len(items) == 2
    assert items[0]["platform"] == "IBKR"
    assert items[0]["value"] == 70000.0
    assert items[1]["platform"] == "DBS"
    assert items[1]["value"] == 30000.0


def test_dashboard_converts_quote_currencies(client: TestClient, db_engine, monkeypatch):
    from sqlalchemy import text
    from datetime import datetime, timezone

    as_of = datetime(2026, 2, 6, tzinfo=timezone.utc)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country) VALUES "
                "(10, 'SHAREKHAN', 'Sharekhan', 'BROKER', 'IN')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, platform_id) VALUES "
                "(10, 'Sharekhan', 'SHAREKHAN', 'BROKER', 'INR', 'IN', 10)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(10, 'INFY', 'Infosys', 'STOCK', 'INR', 'IN'), "
                "(11, 'AAPL', 'Apple', 'STOCK', 'USD', 'US')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO positions (id, account_id, asset_id, as_of, quantity, avg_cost, cost_basis_base) VALUES "
                "(10, 10, 10, :as_of, 100, 1000, 100000), "
                "(11, 10, 11, :as_of, 10, 200, 2000)"
            ),
            {"as_of": as_of},
        )

    def fake_rates(_date, base, symbols):
        assert base == "SGD"
        return {"SGD": 1.0, "INR": 0.01, "USD": 1.5}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/summary?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200
    data = resp.json()
    # 100000 INR * 0.01 = 1000 SGD, 2000 USD * 1.5 = 3000 SGD
    assert data["net_worth"]["stocks_funds"] == 4000.0
    assert data["net_worth"]["total"] == 4000.0
