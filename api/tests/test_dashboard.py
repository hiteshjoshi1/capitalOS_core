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


def test_dashboard_top_holdings_include_cash_symbol(client: TestClient, seed_dashboard_data):
    resp = client.get("/dashboard/summary?month=2026-02&compare=prev_month")
    assert resp.status_code == 200
    data = resp.json()

    top = data["top_holdings"]
    cash_rows = [row for row in top if row["asset_class"] == "CASH"]
    assert len(cash_rows) == 1
    assert cash_rows[0]["symbol"] == "SGD"
    assert cash_rows[0]["percent_of_networth"] == 30.0


def test_dashboard_summary_exposes_risk_fields_for_top_n_card(client: TestClient, seed_dashboard_data):
    resp = client.get("/dashboard/summary?month=2026-02&compare=prev_month")
    assert resp.status_code == 200
    data = resp.json()

    assert data["net_worth"]["total"] > 0
    assert len(data["top_holdings"]) >= 3
    assert all(
        {"symbol", "asset_class", "value", "quantity", "avg_cost", "latest_price", "quote_currency"}.issubset(row.keys())
        for row in data["top_holdings"][:3]
    )
    values = [row["value"] for row in data["top_holdings"][:3]]
    assert values == sorted(values, reverse=True)


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


def test_dashboard_uses_latest_stock_prices_when_available(client: TestClient, db_engine, monkeypatch):
    from sqlalchemy import text
    from datetime import datetime, timezone

    as_of = datetime(2026, 2, 6, tzinfo=timezone.utc)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country) VALUES "
                "(20, 'IBKR', 'Interactive Brokers', 'BROKER', 'US')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, platform_id) VALUES "
                "(20, 'IBKR Main', 'IBKR', 'BROKER', 'USD', 'US', 20)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(20, 'AAPL', 'Apple', 'STOCK', 'USD', 'US')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO positions (id, account_id, asset_id, as_of, quantity, avg_cost, cost_basis_base) VALUES "
                "(20, 20, 20, :as_of, 10, 100, 1000)"
            ),
            {"as_of": as_of},
        )
        conn.execute(
            text(
                "INSERT INTO prices (id, asset_id, ts, price, currency, source, trade_date, exchange_code, provider_symbol) VALUES "
                "(20, 20, :as_of, 200, 'USD', 'eodhd_bulk', '2026-02-06', 'US', 'AAPL.US')"
            ),
            {"as_of": as_of},
        )

    def fake_rates(_date, base, symbols):
        assert base == "USD"
        return {"USD": 1.0}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/summary?month=2026-02&base_currency=USD")
    assert resp.status_code == 200
    data = resp.json()
    # 10 qty * 200 latest price = 2000, replacing cost_basis_base=1000
    assert data["net_worth"]["stocks_funds"] == 2000.0
    assert data["net_worth"]["total"] == 2000.0


def test_dashboard_top_holdings_infers_geo_and_exposes_detail_fields(client: TestClient, db_engine, monkeypatch):
    from sqlalchemy import text
    from datetime import datetime, timezone

    as_of = datetime(2026, 2, 6, tzinfo=timezone.utc)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country) VALUES "
                "(30, 'IBKR', 'Interactive Brokers', 'BROKER', 'US')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, platform_id) VALUES "
                "(30, 'IBKR One', 'IBKR', 'BROKER', 'HKD', 'HK', 30), "
                "(31, 'IBKR Two', 'IBKR', 'BROKER', 'HKD', 'HK', 30)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(30, '700', 'Tencent', 'STOCK', 'HKD', NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO positions (id, account_id, asset_id, as_of, quantity, avg_cost, cost_basis_base) VALUES "
                "(30, 30, 30, :as_of, 10, 100, 1000), "
                "(31, 31, 30, :as_of, 20, 200, 4000)"
            ),
            {"as_of": as_of},
        )
        conn.execute(
            text(
                "INSERT INTO prices (id, asset_id, ts, price, currency, source, trade_date, exchange_code, provider_symbol) VALUES "
                "(30, 30, :as_of, 150, 'HKD', 'eodhd_bulk', '2026-02-06', 'HKEX', '700.HK')"
            ),
            {"as_of": as_of},
        )
        conn.execute(
            text(
                "INSERT INTO market_symbol_map (id, asset_id, exchange_code, exchange_symbol, quote_currency, is_active) VALUES "
                "(30, 30, 'HKEX', '700', 'HKD', 1)"
            )
        )

    def fake_rates(_date, base, symbols):
        assert base == "HKD"
        return {"HKD": 1.0}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/summary?month=2026-02&base_currency=HKD")
    assert resp.status_code == 200
    data = resp.json()
    row = next(item for item in data["top_holdings"] if item["symbol"] == "700")

    assert row["geo"] == "HK"
    assert row["quantity"] == 30.0
    assert row["avg_cost"] == pytest.approx((100.0 * 10.0 + 200.0 * 20.0) / 30.0)
    assert row["latest_price"] == 150.0
    assert row["quote_currency"] == "HKD"


def test_dashboard_top_holdings_limit_is_15(client: TestClient, db_engine, monkeypatch):
    from sqlalchemy import text
    from datetime import datetime, timezone

    as_of = datetime(2026, 2, 6, tzinfo=timezone.utc)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country) VALUES "
                "(40, 'IBKR', 'Interactive Brokers', 'BROKER', 'US')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, platform_id) VALUES "
                "(40, 'IBKR Main', 'IBKR', 'BROKER', 'USD', 'US', 40)"
            )
        )
        asset_rows = []
        position_rows = []
        for idx in range(18):
            asset_id = 400 + idx
            value = 20000 - (idx * 100)
            asset_rows.append(
                {
                    "id": asset_id,
                    "symbol": f"STK{idx + 1}",
                    "name": f"Stock {idx + 1}",
                }
            )
            position_rows.append(
                {
                    "id": asset_id,
                    "account_id": 40,
                    "asset_id": asset_id,
                    "as_of": as_of,
                    "quantity": 10,
                    "avg_cost": 10,
                    "cost_basis_base": value,
                }
            )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) "
                "VALUES (:id, :symbol, :name, 'STOCK', 'USD', 'US')"
            ),
            asset_rows,
        )
        conn.execute(
            text(
                "INSERT INTO positions (id, account_id, asset_id, as_of, quantity, avg_cost, cost_basis_base) "
                "VALUES (:id, :account_id, :asset_id, :as_of, :quantity, :avg_cost, :cost_basis_base)"
            ),
            position_rows,
        )

    def fake_rates(_date, base, symbols):
        assert base == "USD"
        return {"USD": 1.0}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/summary?month=2026-02&base_currency=USD")
    assert resp.status_code == 200
    data = resp.json()
    non_cash = [row for row in data["top_holdings"] if row["asset_class"] != "CASH"]
    assert len(non_cash) == 15
