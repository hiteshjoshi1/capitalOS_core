from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.routers.dashboard import _display_source, _infer_country, _anchor_ts, _networth_components, _parse_month
from tests.canonical_test_helpers import (
    seed_canonical_account_balance_for_test,
    seed_canonical_position_snapshot_for_test,
)


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
    assert data["current_net_worth_as_of"] is not None
    assert data["current_net_worth"]["total"] >= data["net_worth"]["total"]
    assert "current_net_worth_freshness" in data
    assert data["net_worth_as_of"] == "2026-03-01T00:00:00+00:00"
    assert data["net_worth_snapshot_as_of"] == "2026-02-06T00:00:00+00:00"
    assert data["net_worth_boundary_at"] == "2026-03-01T00:00:00+00:00"
    assert data["net_worth_boundary_exact"] is False
    assert data["net_worth_freshness_status"] == "synthetic"
    assert data["net_worth"]["total"] == 100000.0
    assert data["cash_flow"]["income"] == 5999.0
    assert data["cash_flow"]["expenses"] == 2100.0
    assert data["cash_flow"]["net"] == 3899.0
    assert data["cash_flow"]["savings_rate"] == pytest.approx(3899.0 / 5999.0, rel=1e-4)
    assert data["cash_percent"] == 30.0

    top = data["top_holdings"]
    assert len(top) == 2
    assert top[0]["symbol"] == "AAPL"

    changes = data["net_worth_change"]["vs_prev_month"]
    assert changes["abs"] == 10000.0
    assert changes["pct"] == 10000.0 / 90000.0
    component_changes = data["net_worth_component_change"]
    assert component_changes["cash"]["abs"] == 0.0
    assert component_changes["stocks_funds"]["abs"] == 5000.0
    assert component_changes["crypto"]["abs"] == 5000.0
    assert data["top_movers"]["compare_month"] == "2026-01"
    assert "gainers" in data["top_movers"]
    assert "detractors" in data["top_movers"]


def test_dashboard_net_worth_change_lightweight(client: TestClient, seed_dashboard_data):
    resp = client.get("/dashboard/net-worth-change?month=2026-02&compare=prev_month")
    assert resp.status_code == 200
    data = resp.json()

    assert data["as_of_month"] == "2026-02"
    assert data["base_currency"] == "SGD"
    assert "net_worth_as_of" in data
    assert data["net_worth_as_of"] == "2026-03-01T00:00:00+00:00"
    assert data["net_worth_snapshot_as_of"] == "2026-02-06T00:00:00+00:00"
    assert data["net_worth_boundary_at"] == "2026-03-01T00:00:00+00:00"
    assert data["net_worth_boundary_exact"] is False
    assert data["net_worth_freshness_status"] == "synthetic"
    assert "net_worth_change" in data
    assert "vs_prev_month" in data["net_worth_change"]
    assert "vs_prev_year" not in data["net_worth_change"]

    changes = data["net_worth_change"]["vs_prev_month"]
    assert changes["abs"] == 10000.0
    assert changes["pct"] == 10000.0 / 90000.0


def test_canonical_net_worth_ignores_legacy_position_roll_forward(db_engine, monkeypatch):
    from datetime import datetime, timezone

    from sqlalchemy import text
    from sqlalchemy.orm import Session

    as_of = datetime(2026, 3, 26, tzinfo=timezone.utc)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country) VALUES "
                "(910, 'DBS', 'DBS Bank', 'BANK', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country, platform_id) VALUES "
                "(910, 'DBS Multiplier', 'DBS', 2, 'BANK', 'SGD', 'SG', 910)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(910, 'SGD', 'SGD Cash', 'CASH', 'SGD', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO account_balance_snapshots "
                "(id, account_id, as_of_date, currency, balance_type, balance_local, balance_base, "
                "fx_rate_to_base, authority_status, source_kind, metadata_json) VALUES "
                "(910, 910, '2026-03-26', 'SGD', 'bank_cash', 400000, 400000, 1, "
                "'authoritative', 'test_fixture', '{}')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO transactions "
                "(id, ts, account_id, amount, type, currency, category, merchant_counterparty, notes) VALUES "
                "(9101, '2026-04-24T00:00:00+00:00', 910, 20000, 'INCOME', 'SGD', 'Bank::ADV', "
                "'ICT self 20260424UOVBSGSGBRT7617851 OTHR', 'Payments')"
            )
        )

    monkeypatch.setattr("app.routers.dashboard.get_rates", lambda *_args, **_kwargs: {"SGD": 1.0, "USD": 1.0})

    db = Session(bind=db_engine)
    try:
        components = _networth_components(db, _anchor_ts(_parse_month("2026-04")), "SGD", 2)
    finally:
        db.close()

    assert components["cash"] == 400000.0
    assert components["total"] == 400000.0


def test_stock_holdings_summary_is_stocks_only_payload(client: TestClient, seed_dashboard_data):
    resp = client.get("/dashboard/stock-holdings?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200
    data = resp.json()

    assert data["as_of_month"] == "2026-02"
    assert data["base_currency"] == "SGD"
    assert "top_holdings" in data
    assert len(data["top_holdings"]) > 0

    # stocks-only endpoint should not include heavy dashboard sections
    assert "geography" not in data
    assert "cash_flow" not in data
    assert "cash_balances" not in data
    assert "net_worth" not in data
    assert "net_worth_change" not in data
    assert "geography_breakdown" in data
    assert "platform_breakdown" in data
    assert "stock_current_total" in data
    assert "stock_snapshot_total" in data
    assert "quote_freshness_summary" in data
    assert "trend" in data


def test_stock_holdings_summary_geography_breakdown_uses_current_vs_snapshot(client: TestClient, db_engine, monkeypatch):
    monkeypatch.setenv("QUOTE_STALE_DAYS", "10")
    as_of_snapshot = datetime(2026, 5, 1, tzinfo=timezone.utc)
    as_of_current = datetime(2026, 5, 20, tzinfo=timezone.utc)
    quote_trade_date = datetime(2026, 5, 1, tzinfo=timezone.utc).date()
    monkeypatch.setattr("app.routers.dashboard._quote_age_days", lambda _trade_date: 1)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country) VALUES "
                "(210, 'IBKR', 'Interactive Brokers', 'BROKER', 'US')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, platform_id) VALUES "
                "(210, 'IBKR US', 'IBKR', 'BROKER', 'USD', 'US', 210), "
                "(211, 'IBKR HK', 'IBKR', 'BROKER', 'HKD', 'HK', 210)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(210, 'AAPL', 'Apple', 'STOCK', 'USD', 'US'), "
                "(211, '700', 'Tencent', 'STOCK', 'HKD', 'HK')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO market_symbol_map (asset_id, exchange_code, exchange_symbol, quote_currency, is_active) VALUES "
                "(210, 'US', 'AAPL', 'USD', TRUE), "
                "(211, 'HKEX', '700', 'HKD', TRUE)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO prices (asset_id, ts, price, currency, source, trade_date, exchange_code, provider_symbol) VALUES "
                "(210, :snapshot, 110, 'USD', 'finnhub_market', :quote_trade_date, 'US', 'AAPL'), "
                "(211, :snapshot, 60, 'HKD', 'yfinance_market', :quote_trade_date, 'HKEX', '0700.HK')"
            ),
            {"snapshot": as_of_snapshot, "current": as_of_current, "quote_trade_date": quote_trade_date},
        )

    seed_canonical_position_snapshot_for_test(
        db_engine,
        account_id=210,
        asset_id=210,
        as_of=as_of_snapshot,
        quantity=10,
        market_value_base=1100,
        market_price=110,
        cost_basis_base=900,
        currency="USD",
        platform_code="IBKR",
    )
    seed_canonical_position_snapshot_for_test(
        db_engine,
        account_id=211,
        asset_id=211,
        as_of=as_of_snapshot,
        quantity=10,
        market_value_base=600,
        market_price=60,
        cost_basis_base=450,
        currency="HKD",
        platform_code="IBKR",
    )
    seed_canonical_position_snapshot_for_test(
        db_engine,
        account_id=210,
        asset_id=210,
        as_of=as_of_current,
        quantity=20,
        market_value_base=2200,
        market_price=110,
        cost_basis_base=1900,
        currency="USD",
        platform_code="IBKR",
    )
    seed_canonical_position_snapshot_for_test(
        db_engine,
        account_id=211,
        asset_id=211,
        as_of=as_of_current,
        quantity=5,
        market_value_base=300,
        market_price=60,
        cost_basis_base=250,
        currency="HKD",
        platform_code="IBKR",
    )

    monkeypatch.setattr("app.routers.dashboard.get_rates", lambda *_args, **_kwargs: {"USD": 1.0, "HKD": 1.0})

    resp = client.get("/dashboard/stock-holdings?month=2026-04&base_currency=USD")
    assert resp.status_code == 200
    data = resp.json()

    geography = {item["geography"]: item for item in data["geography_breakdown"]}
    platform = {item["key"]: item for item in data["platform_breakdown"]}
    assert data["current_holdings_as_of"] == "2026-05-20T00:00:00+00:00"
    assert data["stock_current_total"] == 2500.0
    assert data["stock_snapshot_total"] == 1700.0
    assert geography["US"]["current_value"] == 2200.0
    assert geography["US"]["snapshot_value"] == 1100.0
    assert geography["US"]["delta_abs"] == 1100.0
    assert geography["HK"]["current_value"] == 300.0
    assert geography["HK"]["snapshot_value"] == 600.0
    assert geography["HK"]["delta_abs"] == -300.0
    assert platform["IBKR"]["current_value"] == 2500.0
    assert platform["IBKR"]["snapshot_value"] == 1700.0
    assert platform["IBKR"]["delta_abs"] == 800.0
    assert platform["IBKR"]["percent"] == 100.0
    assert data["quote_freshness_summary"]["fresh"] == 2
    assert data["trend"][-1]["month"] == "2026-04"


def test_dashboard_summary_uses_wallet_snapshots_for_crypto(client: TestClient, db_engine, monkeypatch):
    from datetime import datetime, timezone

    from sqlalchemy import text

    as_of = datetime(2026, 2, 6, tzinfo=timezone.utc)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country) VALUES "
                "(70, 'DBS', 'DBS Bank', 'BANK', 'SG'), "
                "(71, 'COINBASE', 'Coinbase', 'EXCHANGE', 'US')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, platform_id) VALUES "
                "(70, 'DBS Savings', 'DBS', 'BANK', 'SGD', 'SG', 70), "
                "(71, 'Coinbase', 'COINBASE', 'EXCHANGE', 'USD', 'US', 71)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(70, 'SGD', 'SGD Cash', 'CASH', 'SGD', 'SG'), "
                "(71, 'BTC', 'Bitcoin', 'CRYPTO', 'USD', 'GLOBAL')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallets (id, chain_type, chain, address, label, status, created_at) VALUES "
                "('wallet-70', 'evm', 'ethereum', '0x70', 'Main wallet', 'active', :as_of)"
            ),
            {"as_of": as_of},
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshots (id, wallet_id, as_of_date, fetched_at, total_usd) VALUES "
                "(70, 'wallet-70', '2026-02-06', :as_of, 123.45)"
            ),
            {"as_of": as_of},
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshot_items "
                "(id, snapshot_id, chain_type, chain, asset_kind, symbol, normalized_amount, value_usd) VALUES "
                "(70, 70, 'evm', 'ethereum', 'native', 'ETH', 1, 123.45)"
            )
        )

    seed_canonical_account_balance_for_test(
        db_engine,
        account_id=70,
        as_of=as_of,
        currency="SGD",
        balance_base=1000,
        balance_type="bank_cash",
    )

    def fake_rates(_date, _base, symbols):
        return {symbol: 1.0 for symbol in symbols}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)
    monkeypatch.setattr("app.routers.crypto.get_rates", fake_rates)

    dashboard_resp = client.get("/dashboard/summary?month=2026-02&base_currency=USD")
    assert dashboard_resp.status_code == 200
    dashboard_body = dashboard_resp.json()

    crypto_resp = client.get("/crypto/summary?base_currency=USD")
    assert crypto_resp.status_code == 200
    crypto_body = crypto_resp.json()

    allocation_resp = client.get("/dashboard/platform-allocation?month=2026-02&base_currency=SGD")
    assert allocation_resp.status_code == 200
    allocation_body = allocation_resp.json()

    assert dashboard_body["net_worth"]["cash"] == 1000.0
    assert dashboard_body["net_worth"]["crypto"] == 123.45
    assert dashboard_body["net_worth"]["total"] == 1123.45
    assert crypto_body["total_crypto_base"] == 123.45
    assert dashboard_body["net_worth"]["crypto"] == crypto_body["total_crypto_base"]
    # After changes: CASH is excluded, CRYPTO (ETH) is included in top_holdings
    assert [row["symbol"] for row in dashboard_body["top_holdings"]] == ["ETH"]
    assert any(row["asset_class"] == "CRYPTO" for row in dashboard_body["top_holdings"])
    assert all(row["asset_class"] != "CASH" for row in dashboard_body["top_holdings"])
    assert dashboard_body["geography"] == [{"country": "SG", "value": 1000.0, "percent": 89.01}]
    assert allocation_body["total"] == 1123.45
    assert allocation_body["items"] == [
        {"platform": "DBS", "platform_type": "BANK", "country": "SG", "value": 1000.0, "percent": 89.01},
        {"platform": "CRYPTO", "platform_type": "WALLET_PROVIDER", "country": None, "value": 123.45, "percent": 10.99},
    ]


def test_dashboard_eth_derivative_grouping(client: TestClient, db_engine, monkeypatch):
    """Verify ETH+wETH+stETH+wstETH collapse into single position."""
    from datetime import datetime, timezone
    from sqlalchemy import text

    as_of = datetime(2026, 2, 6, tzinfo=timezone.utc)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO crypto_wallets (id, chain_type, chain, address, label, status, created_at) VALUES "
                "('wallet-eth-test', 'evm', 'ethereum', '0xabc123', 'ETH Test Wallet', 'active', :as_of)"
            ),
            {"as_of": as_of},
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshots (id, wallet_id, as_of_date, fetched_at, total_usd) VALUES "
                "(80, 'wallet-eth-test', '2026-02-06', :as_of, 10000)"
            ),
            {"as_of": as_of},
        )
        # Create crypto_assets entries with base_asset = 'ETH'
        conn.execute(
            text(
                "INSERT INTO crypto_assets (id, chain_type, chain, asset_kind, symbol, base_asset) VALUES "
                "(80, 'evm', 'ethereum', 'native', 'ETH', 'ETH'), "
                "(81, 'evm', 'ethereum', 'token', 'wETH', 'ETH'), "
                "(82, 'evm', 'ethereum', 'token', 'stETH', 'ETH'), "
                "(83, 'evm', 'ethereum', 'token', 'wstETH', 'ETH')"
            )
        )
        # Create 4 separate ETH derivative items
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshot_items "
                "(id, snapshot_id, asset_id, chain_type, chain, asset_kind, symbol, normalized_amount, value_usd) VALUES "
                "(80, 80, 80, 'evm', 'ethereum', 'native', 'ETH', 1.0, 3000), "
                "(81, 80, 81, 'evm', 'ethereum', 'token', 'wETH', 0.5, 1500), "
                "(82, 80, 82, 'evm', 'ethereum', 'token', 'stETH', 1.2, 3600), "
                "(83, 80, 83, 'evm', 'ethereum', 'token', 'wstETH', 0.6, 1900)"
            )
        )

    def fake_rates(_date, _base, symbols):
        return {symbol: 1.0 for symbol in symbols}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/summary?month=2026-02&base_currency=USD")
    assert resp.status_code == 200
    data = resp.json()

    # Verify ETH derivatives are collapsed into single position
    eth_holdings = [h for h in data["top_holdings"] if h["symbol"] == "ETH"]
    assert len(eth_holdings) == 1, "ETH derivatives should be collapsed into one position"
    
    # Verify total value = sum of all ETH derivatives
    expected_total = 3000 + 1500 + 3600 + 1900  # 10000
    assert eth_holdings[0]["value"] == expected_total
    assert eth_holdings[0]["asset_class"] == "CRYPTO"


def test_dashboard_crypto_fallback_join_does_not_double_count_duplicate_assets(
    client: TestClient, db_engine, monkeypatch
):
    from datetime import datetime, timezone
    from sqlalchemy import text

    as_of = datetime(2026, 2, 6, tzinfo=timezone.utc)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO crypto_wallets (id, chain_type, chain, address, label, status, created_at) VALUES "
                "('wallet-fallback-test', 'evm', 'ethereum', '0xfallback', 'Fallback Wallet', 'active', :as_of)"
            ),
            {"as_of": as_of},
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshots (id, wallet_id, as_of_date, fetched_at, total_usd) VALUES "
                "(90, 'wallet-fallback-test', '2026-02-06', :as_of, 500)"
            ),
            {"as_of": as_of},
        )
        conn.execute(
            text(
                "INSERT INTO crypto_assets (id, chain_type, chain, asset_kind, symbol, base_asset) VALUES "
                "(90, 'evm', 'ethereum', 'token', 'stETH', 'ETH'), "
                "(91, 'evm', 'ethereum', 'token', 'stETH', 'ETH')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshot_items "
                "(id, snapshot_id, asset_id, chain_type, chain, asset_kind, symbol, normalized_amount, value_usd) VALUES "
                "(90, 90, NULL, 'evm', 'ethereum', 'token', 'stETH', 0.1, 500)"
            )
        )

    def fake_rates(_date, _base, symbols):
        return {symbol: 1.0 for symbol in symbols}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/summary?month=2026-02&base_currency=USD")
    assert resp.status_code == 200
    data = resp.json()

    eth_holdings = [row for row in data["top_holdings"] if row["symbol"] == "ETH"]
    assert len(eth_holdings) == 1
    assert eth_holdings[0]["value"] == 500


def test_dashboard_top_holdings_include_cash_symbol(client: TestClient, seed_dashboard_data):
    resp = client.get("/dashboard/summary?month=2026-02&compare=prev_month")
    assert resp.status_code == 200
    data = resp.json()

    top = data["top_holdings"]
    # After changes: CASH is excluded from top_holdings
    cash_rows = [row for row in top if row["asset_class"] == "CASH"]
    assert len(cash_rows) == 0
    # Verify cash_percent is exposed and correctly computed
    assert "cash_percent" in data
    assert data["cash_percent"] == 30.0


def test_dashboard_summary_exposes_risk_fields_for_top_n_card(client: TestClient, seed_dashboard_data):
    resp = client.get("/dashboard/summary?month=2026-02&compare=prev_month")
    assert resp.status_code == 200
    data = resp.json()

    assert data["net_worth"]["total"] > 0
    assert len(data["top_holdings"]) >= 2
    assert all(
        {"symbol", "asset_class", "value", "quantity", "avg_cost", "latest_price", "quote_currency"}.issubset(row.keys())
        for row in data["top_holdings"][:2]
    )
    values = [row["value"] for row in data["top_holdings"]]
    assert values == sorted(values, reverse=True)


def test_platform_allocation(client: TestClient, seed_dashboard_data):
    resp = client.get("/dashboard/platform-allocation?month=2026-02")
    assert resp.status_code == 200
    data = resp.json()

    summary_resp = client.get("/dashboard/summary?month=2026-02")
    assert summary_resp.status_code == 200
    summary = summary_resp.json()

    assert data["total"] == pytest.approx(summary["net_worth"]["total"])
    assert data["as_of"] is not None

    items = data["items"]
    by_platform = {item["platform"]: item for item in items}
    assert set(by_platform) == {"IBKR", "DBS", "CRYPTO"}
    assert by_platform["IBKR"]["value"] == pytest.approx(50000.0)
    assert by_platform["DBS"]["value"] == pytest.approx(30000.0)
    assert by_platform["CRYPTO"]["value"] == pytest.approx(20000.0)


def test_platform_allocation_prefers_account_platform_over_platform_id(client: TestClient, db_engine):
    as_of = datetime(2026, 2, 6, tzinfo=timezone.utc)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country) VALUES "
                "(701, 'DBS', 'DBS Bank', 'BANK', 'SG'), "
                "(702, 'DBS_VICKERS', 'DBS Vickers', 'BROKER', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country, platform_id) VALUES "
                "(701, 'DBS Savings', 'DBS', 1, 'BANK', 'SGD', 'SG', 701), "
                "(702, 'DBS Vickers', 'DBS_VICKERS', 1, 'BROKER', 'SGD', 'SG', 701)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(701, 'CASH', 'Cash', 'CASH', 'SGD', 'SG'), "
                "(702, 'D05', 'DBS Group', 'STOCK', 'SGD', 'SG')"
            )
        )
    seed_canonical_account_balance_for_test(
        db_engine,
        account_id=701,
        as_of=as_of,
        currency="SGD",
        balance_base=1000,
        balance_type="bank_cash",
    )
    seed_canonical_position_snapshot_for_test(
        db_engine,
        account_id=702,
        asset_id=702,
        as_of=as_of,
        quantity=100,
        market_value_base=2000,
        market_price=20,
        cost_basis_base=2000,
        currency="SGD",
        platform_code="DBS_VICKERS",
    )

    resp = client.get("/dashboard/platform-allocation?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200
    by_platform = {item["platform"]: item for item in resp.json()["items"]}

    assert set(by_platform) == {"DBS_VICKERS", "DBS"}
    assert by_platform["DBS"]["platform_type"] == "BANK"
    assert by_platform["DBS"]["value"] == pytest.approx(1000.0)
    assert by_platform["DBS_VICKERS"]["platform_type"] == "BROKER"
    assert by_platform["DBS_VICKERS"]["value"] == pytest.approx(2000.0)


def test_platform_allocation_uses_current_holdings_with_latest_price(client: TestClient, db_engine, monkeypatch):
    def fake_rates(_date, _base, symbols):
        return {s: 1.0 for s in symbols}

    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country) VALUES "
                "(620, 'TESTBROKER', 'Test Broker', 'BROKER', 'US')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country, platform_id) VALUES "
                "(620, 'Test Broker Account', 'TESTBROKER', 1, 'BROKER', 'USD', 'US', 620)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(620, 'TEST', 'Test Inc.', 'STOCK', 'USD', 'US')"
            )
        )
        completed_anchor = datetime(2026, 6, 1, tzinfo=timezone.utc)
        later_snapshot = datetime(2026, 6, 10, tzinfo=timezone.utc)
        conn.execute(
            text(
                "INSERT INTO prices (asset_id, ts, price, currency, source, trade_date, exchange_code, provider_symbol) VALUES "
                "(620, :completed_anchor, 100, 'USD', 'test', '2026-06-01', 'US', 'TEST'), "
                "(620, :later_snapshot, 200, 'USD', 'test', '2026-06-10', 'US', 'TEST')"
            ),
            {"completed_anchor": completed_anchor, "later_snapshot": later_snapshot},
        )
    seed_canonical_position_snapshot_for_test(
        db_engine,
        account_id=620,
        asset_id=620,
        as_of=completed_anchor,
        quantity=10,
        market_value_base=1000,
        market_price=100,
        cost_basis_base=1000,
        currency="USD",
        platform_code="TESTBROKER",
    )
    seed_canonical_position_snapshot_for_test(
        db_engine,
        account_id=620,
        asset_id=620,
        as_of=later_snapshot,
        quantity=20,
        market_value_base=2000,
        market_price=100,
        cost_basis_base=2000,
        currency="USD",
        platform_code="TESTBROKER",
    )

    monkeypatch.setenv("SNAPSHOT_DAY", "1")
    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)
    monkeypatch.setattr(
        "app.routers.dashboard._current_anchor_ts",
        lambda: datetime(2026, 6, 15, tzinfo=timezone.utc),
    )

    resp = client.get("/dashboard/platform-allocation?month=2026-06&base_currency=USD")
    assert resp.status_code == 200
    data = resp.json()

    assert data["as_of"] == "2026-06-10T00:00:00+00:00"
    assert data["total"] == pytest.approx(4000.0)
    assert data["items"][0]["platform"] == "TESTBROKER"
    assert data["items"][0]["value"] == pytest.approx(4000.0)


def test_dashboard_geography_exposure_breakdown_maps_crypto_to_us(client: TestClient, seed_dashboard_data, monkeypatch):
    def fake_rates(_date, _base, symbols):
        return {symbol: 1.0 for symbol in symbols}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/geography-exposure?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200
    data = resp.json()

    assert data["base_currency"] == "SGD"
    assert data["total"] == 100000.0

    by_country = {row["country"]: row for row in data["items"]}
    assert set(by_country.keys()) == {"US", "SG"}
    assert by_country["US"]["stocks_funds"] == 50000.0
    assert by_country["US"]["cash"] == 0.0
    assert by_country["US"]["crypto"] == 20000.0
    assert by_country["US"]["total"] == 70000.0
    assert by_country["SG"]["stocks_funds"] == 0.0
    assert by_country["SG"]["cash"] == 30000.0
    assert by_country["SG"]["crypto"] == 0.0
    assert by_country["SG"]["total"] == 30000.0


def test_dashboard_geography_exposure_counts_stablecoins_as_cash_in_us(client: TestClient, db_engine, monkeypatch):
    from datetime import datetime, timezone
    from sqlalchemy import text

    as_of = datetime(2026, 2, 6, tzinfo=timezone.utc)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country) VALUES "
                "(801, 'DBS', 'DBS Bank', 'BANK', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, platform_id) VALUES "
                "(801, 'DBS Savings', 'DBS', 'BANK', 'SGD', 'SG', 801)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(801, 'SGD', 'SGD Cash', 'CASH', 'SGD', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallets (id, chain_type, chain, address, label, status, created_at) VALUES "
                "('wallet-geo', 'evm', 'ethereum', '0xgeo', 'Geo wallet', 'active', :as_of)"
            ),
            {"as_of": as_of},
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshots (id, wallet_id, as_of_date, fetched_at, total_usd) VALUES "
                "(801, 'wallet-geo', '2026-02-06', :as_of, 100)"
            ),
            {"as_of": as_of},
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshot_items "
                "(id, snapshot_id, chain_type, chain, asset_kind, symbol, normalized_amount, value_usd) VALUES "
                "(801, 801, 'evm', 'ethereum', 'token', 'USDC', 40, 40), "
                "(802, 801, 'evm', 'ethereum', 'native', 'BTC', 0.001, 60)"
            )
        )
    seed_canonical_account_balance_for_test(
        db_engine,
        account_id=801,
        as_of=as_of,
        currency="SGD",
        balance_base=1000,
        balance_type="bank_cash",
    )

    def fake_rates(_date, _base, symbols):
        return {symbol: 1.0 for symbol in symbols}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/geography-exposure?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200
    data = resp.json()

    by_country = {row["country"]: row for row in data["items"]}
    assert by_country["US"]["cash"] == 40.0
    assert by_country["US"]["crypto"] == 60.0
    assert by_country["US"]["stocks_funds"] == 0.0


def test_dashboard_cash_deposits_matches_cash_total(client: TestClient, seed_dashboard_data):
    resp = client.get("/dashboard/cash-deposits?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200
    data = resp.json()

    assert data["total"] == 30000.0
    assert data["current_total"] == 30000.0
    assert data["snapshot_total"] == 30000.0
    assert data["items"] == [
        {
            "source": "DBS",
            "value": 30000.0,
            "percent": 100.0,
        }
    ]


def test_dashboard_cash_deposits_exposes_snapshot_delta_and_trend(client: TestClient, db_engine, monkeypatch):
    snapshot_as_of = datetime(2026, 5, 1, tzinfo=timezone.utc)
    current_as_of = datetime(2026, 5, 20, tzinfo=timezone.utc)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country) VALUES "
                "(310, 'DBS', 'DBS Bank', 'BANK', 'SG'), "
                "(311, 'IBKR', 'Interactive Brokers', 'BROKER', 'US')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, platform_id) VALUES "
                "(310, 'DBS Savings', 'DBS', 'BANK', 'SGD', 'SG', 310), "
                "(311, 'IBKR Cash', 'IBKR', 'BROKER', 'USD', 'US', 311)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(310, 'SGD', 'SGD Cash', 'CASH', 'SGD', 'SG'), "
                "(311, 'USD', 'USD Cash', 'CASH', 'USD', 'US')"
            )
        )
    seed_canonical_account_balance_for_test(
        db_engine,
        account_id=310,
        as_of=snapshot_as_of,
        currency="SGD",
        balance_base=1000,
        balance_type="bank_cash",
    )
    seed_canonical_account_balance_for_test(
        db_engine,
        account_id=311,
        as_of=snapshot_as_of,
        currency="USD",
        balance_base=200,
        balance_type="broker_cash",
    )
    seed_canonical_account_balance_for_test(
        db_engine,
        account_id=310,
        as_of=current_as_of,
        currency="SGD",
        balance_base=1200,
        balance_type="bank_cash",
    )
    seed_canonical_account_balance_for_test(
        db_engine,
        account_id=311,
        as_of=current_as_of,
        currency="USD",
        balance_base=300,
        balance_type="broker_cash",
    )

    monkeypatch.setattr("app.routers.dashboard.get_rates", lambda _date, _base, symbols: {"SGD": 1.0, "USD": 1.5})

    resp = client.get("/dashboard/cash-deposits?month=2026-04&base_currency=SGD")
    assert resp.status_code == 200
    data = resp.json()

    assert data["current_total"] == 1650.0
    assert data["snapshot_total"] == 1300.0
    assert data["delta_abs"] == 350.0
    assert data["trend"][-1] == {"month": "2026-04", "value": 1300.0}
    currency_breakdown = {item["currency"]: item for item in data["currency_breakdown"]}
    assert currency_breakdown["SGD"]["current_value"] == 1200.0
    assert currency_breakdown["SGD"]["snapshot_value"] == 1000.0
    assert currency_breakdown["USD"]["current_value"] == 450.0
    assert currency_breakdown["USD"]["snapshot_value"] == 300.0


def test_dashboard_cash_deposits_includes_stablecoins_by_chain(client: TestClient, db_engine, monkeypatch):
    from sqlalchemy import text
    from datetime import datetime, timezone

    as_of = datetime(2026, 2, 6, tzinfo=timezone.utc)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country) VALUES "
                "(50, 'OCBC', 'OCBC Bank', 'BANK', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, platform_id) VALUES "
                "(50, 'OCBC 360', 'OCBC', 'BANK', 'SGD', 'SG', 50)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(50, 'SGD', 'SGD Cash', 'CASH', 'SGD', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallets (id, chain_type, chain, address, label, status, created_at) VALUES "
                "('wallet-eth', 'evm', 'ethereum', '0xabc', 'Main wallet', 'active', :as_of), "
                "('wallet-sol', 'svm', 'solana', 'So111', 'Sol wallet', 'active', :as_of)"
            ),
            {"as_of": as_of},
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshots (id, wallet_id, as_of_date, fetched_at, total_usd) VALUES "
                "(50, 'wallet-eth', '2026-02-05', :as_of, 30), "
                "(51, 'wallet-sol', '2026-02-05', :as_of, 20)"
            ),
            {"as_of": as_of},
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshot_items "
                "(id, snapshot_id, chain_type, chain, asset_kind, symbol, normalized_amount, value_usd) VALUES "
                "(50, 50, 'evm', 'ETHEREUM', 'token', 'USDC', 30, 30), "
                "(51, 51, 'svm', 'solana', 'token', 'USDT', 20, 20)"
            )
        )
    seed_canonical_account_balance_for_test(
        db_engine,
        account_id=50,
        as_of=as_of,
        currency="SGD",
        balance_base=1000,
        balance_type="bank_cash",
    )

    def fake_rates(_date, base, symbols):
        assert base == "SGD"
        rates = {"SGD": 1.0}
        if "USD" in symbols:
            rates["USD"] = 1.5
        return rates

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/cash-deposits?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200
    data = resp.json()

    assert data["total"] == 1075.0
    assert data["items"] == [
        {"source": "OCBC", "value": 1000.0, "percent": 93.02},
        {"source": "Ethereum", "value": 45.0, "percent": 4.19},
        {"source": "Solana", "value": 30.0, "percent": 2.79},
    ]


def test_dashboard_cash_deposits_converts_non_sgd_cash_positions(client: TestClient, db_engine, monkeypatch):
    from datetime import datetime, timezone
    from sqlalchemy import text

    as_of = datetime(2026, 2, 6, tzinfo=timezone.utc)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country) VALUES "
                "(60, 'IBKR', 'Interactive Brokers', 'BROKER', 'US')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, platform_id) VALUES "
                "(60, 'IBKR Cash', 'IBKR', 'BROKER', 'USD', 'US', 60)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(60, 'USD', 'USD Cash', 'CASH', 'USD', 'US')"
            )
        )
    seed_canonical_account_balance_for_test(
        db_engine,
        account_id=60,
        as_of=as_of,
        currency="USD",
        balance_base=200,
        balance_type="broker_cash",
    )

    def fake_rates(_date, base, symbols):
        assert base == "SGD"
        assert symbols == {"USD"}
        return {"USD": 1.5}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/cash-deposits?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200
    data = resp.json()

    assert data["total"] == 300.0
    assert data["items"] == [{"source": "IBKR", "value": 300.0, "percent": 100.0}]


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("ethereum", "Ethereum"),
        ("ETHEREUM", "Ethereum"),
        ("OCBC", "OCBC"),
        ("IBKR", "IBKR"),
        ("", "UNKNOWN"),
        (None, "UNKNOWN"),
    ],
)
def test_display_source_normalizes_values(raw_value: str | None, expected: str):
    assert _display_source(raw_value) == expected


@pytest.mark.parametrize(
    ("symbol", "home", "platform", "quote_currency", "exchange_code", "expected"),
    [
        ("AAPL", "US", "IBKR", "USD", "US", "US"),
        ("700", None, "IBKR", "HKD", "HKEX", "HK"),
        ("SGD", None, "DBS", "SGD", None, "SG"),
        ("SGD", None, "IBKR", "SGD", None, "SG"),
        ("FOO", None, "IBKR", "USD", None, "US"),
        ("FOO", None, "IBKR", "HKD", None, "HK"),
        ("FOO", None, "IBKR", "INR", None, "IN"),
        ("FOO", None, "IBKR", "EUR", None, "UNKNOWN"),
    ],
)
def test_infer_country_uses_currency_fallbacks(
    symbol: str | None,
    home: str | None,
    platform: str | None,
    quote_currency: str | None,
    exchange_code: str | None,
    expected: str,
):
    assert _infer_country(symbol, home, platform, quote_currency, exchange_code) == expected


def test_dashboard_geography_exposure_maps_sgd_cash_to_sg_when_home_country_missing(client: TestClient, db_engine, monkeypatch):
    from datetime import datetime, timezone
    from sqlalchemy import text

    as_of = datetime(2026, 2, 6, tzinfo=timezone.utc)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country) VALUES "
                "(990, 'DBS', 'DBS Bank', 'BANK', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, platform_id) VALUES "
                "(990, 'DBS Cash', 'DBS', 'BANK', 'SGD', 'SG', 990)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(990, 'SGD', 'SGD Cash', 'CASH', 'SGD', NULL)"
            )
        )
    seed_canonical_account_balance_for_test(
        db_engine,
        account_id=990,
        as_of=as_of,
        currency="SGD",
        balance_base=1000,
        balance_type="bank_cash",
    )

    def fake_rates(_date, _base, symbols):
        return {symbol: 1.0 for symbol in symbols}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/geography-exposure?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200
    data = resp.json()

    by_country = {row["country"]: row for row in data["items"]}
    assert "UNKNOWN" not in by_country
    assert by_country["SG"]["cash"] == 1000.0


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
    seed_canonical_position_snapshot_for_test(
        db_engine,
        account_id=10,
        asset_id=10,
        as_of=as_of,
        quantity=100,
        market_value_base=100000,
        market_price=1000,
        cost_basis_base=100000,
        currency="INR",
        platform_code="SHAREKHAN",
    )
    seed_canonical_position_snapshot_for_test(
        db_engine,
        account_id=10,
        asset_id=11,
        as_of=as_of,
        quantity=10,
        market_value_base=2000,
        market_price=200,
        cost_basis_base=2000,
        currency="USD",
        platform_code="SHAREKHAN",
    )

    def fake_rates(_date, base, symbols):
        assert base == "SGD"
        return {"SGD": 1.0, "INR": 0.01, "USD": 1.5}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/summary?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200
    data = resp.json()
    # Canonical backfill stores market_value_base in the account base currency (INR).
    assert data["net_worth"]["stocks_funds"] == 1020.0
    assert data["net_worth"]["total"] == 1020.0


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
                "INSERT INTO prices (id, asset_id, ts, price, currency, source, trade_date, exchange_code, provider_symbol) VALUES "
                "(20, 20, :as_of, 200, 'USD', 'eodhd_bulk', '2026-02-06', 'US', 'AAPL.US')"
            ),
            {"as_of": as_of},
        )
    seed_canonical_position_snapshot_for_test(
        db_engine,
        account_id=20,
        asset_id=20,
        as_of=as_of,
        quantity=10,
        market_value_base=2000,
        market_price=200,
        cost_basis_base=1000,
        currency="USD",
        platform_code="IBKR",
    )

    def fake_rates(_date, base, symbols):
        assert base == "USD"
        return {"USD": 1.0}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/summary?month=2026-02&base_currency=USD")
    assert resp.status_code == 200
    data = resp.json()
    # Canonical snapshot value is authoritative for the read path.
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
                "INSERT INTO prices (id, asset_id, ts, price, currency, source, trade_date, exchange_code, provider_symbol) VALUES "
                "(30, 30, :as_of, 150, 'HKD', 'eodhd_bulk', '2026-02-06', 'HKEX', '700.HK')"
            ),
            {"as_of": as_of},
        )
        conn.execute(
            text(
                "INSERT INTO market_symbol_map (id, asset_id, exchange_code, exchange_symbol, quote_currency, is_active) VALUES "
                "(30, 30, 'HKEX', '700', 'HKD', TRUE)"
            )
        )
    seed_canonical_position_snapshot_for_test(
        db_engine,
        account_id=30,
        asset_id=30,
        as_of=as_of,
        quantity=10,
        market_value_base=1000,
        market_price=100,
        cost_basis_base=1000,
        currency="HKD",
        platform_code="IBKR",
    )
    seed_canonical_position_snapshot_for_test(
        db_engine,
        account_id=31,
        asset_id=30,
        as_of=as_of,
        quantity=20,
        market_value_base=4000,
        market_price=200,
        cost_basis_base=4000,
        currency="HKD",
        platform_code="IBKR",
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
    assert row["value"] == pytest.approx(4500.0)
    assert row["latest_price"] == 150.0
    assert row["quote_currency"] == "HKD"
    assert row["latest_trade_date"] == "2026-02-06"
    assert row["price_source"] == "eodhd_bulk"
    assert row["price_provider"] == "eodhd"


def test_dashboard_top_holdings_default_limit_supports_top_20_pagination(client: TestClient, db_engine, monkeypatch):
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
                    "quantity": 10,
                    "market_value_base": value,
                }
            )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) "
                "VALUES (:id, :symbol, :name, 'STOCK', 'USD', 'US')"
            ),
            asset_rows,
        )
    for row in position_rows:
        seed_canonical_position_snapshot_for_test(
            db_engine,
            account_id=row["account_id"],
            asset_id=row["asset_id"],
            as_of=as_of,
            quantity=row["quantity"],
            market_value_base=row["market_value_base"],
            market_price=row["market_value_base"] / row["quantity"],
            cost_basis_base=row["market_value_base"],
            currency="USD",
            platform_code="IBKR",
        )

    def fake_rates(_date, base, symbols):
        assert base == "USD"
        return {"USD": 1.0}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/summary?month=2026-02&base_currency=USD")
    assert resp.status_code == 200
    data = resp.json()
    non_cash = [row for row in data["top_holdings"] if row["asset_class"] != "CASH"]
    assert len(non_cash) == 18


def test_dashboard_fallback_join_multiple_crypto_assets_no_doublecount(client: TestClient, db_engine, monkeypatch):
    """Verify fallback JOIN path (asset_id=NULL) with multiple matching crypto_assets does not double-count value_usd."""
    from datetime import datetime, timezone
    from sqlalchemy import text

    as_of = datetime(2026, 2, 6, tzinfo=timezone.utc)
    with db_engine.begin() as conn:
        # Create test wallet
        conn.execute(
            text(
                "INSERT INTO crypto_wallets (id, chain_type, chain, address, label, status, created_at) VALUES "
                "('wallet-dupe-test', 'evm', 'ethereum', '0xDUPE', 'Dupe Test Wallet', 'active', :as_of)"
            ),
            {"as_of": as_of},
        )
        # Create snapshot
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshots (id, wallet_id, as_of_date, fetched_at, total_usd) VALUES "
                "(999, 'wallet-dupe-test', '2026-02-06', :as_of, 5000)"
            ),
            {"as_of": as_of},
        )
        # Create DUPLICATE crypto_assets entries with same symbol+chain
        conn.execute(
            text(
                "INSERT INTO crypto_assets (id, chain_type, chain, asset_kind, symbol, base_asset) VALUES "
                "(9991, 'evm', 'ethereum', 'token', 'USDT', 'USDT'), "
                "(9992, 'evm', 'ethereum', 'token', 'USDT', 'USDT')"
            )
        )
        # Create snapshot item with asset_id=NULL to trigger fallback JOIN
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshot_items "
                "(id, snapshot_id, asset_id, chain_type, chain, asset_kind, symbol, normalized_amount, value_usd) VALUES "
                "(999, 999, NULL, 'evm', 'ethereum', 'token', 'USDT', 5000, 5000)"
            )
        )

    def fake_rates(_date, _base, symbols):
        return {symbol: 1.0 for symbol in symbols}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/summary?month=2026-02&base_currency=USD")
    assert resp.status_code == 200
    data = resp.json()

    # Verify USDT appears once in top_holdings
    usdt_holdings = [h for h in data["top_holdings"] if h["symbol"] == "USDT"]
    assert len(usdt_holdings) == 1, "USDT should appear exactly once despite multiple crypto_assets rows"
    
    # Verify value is NOT multiplied (should be 5000, not 10000)
    assert usdt_holdings[0]["value"] == 5000.0, "Value should not be doubled by multiple crypto_assets matches"


def test_dashboard_bootstrap_returns_correct_schema(client: TestClient, db_engine, monkeypatch):
    """GET /dashboard/bootstrap must return net_worth, stock_exposure_total, crypto_exposure_total,
    cash_percent as numeric fields and must NOT include geography, top_holdings, cashflow, or compare."""
    from datetime import datetime, timezone
    from sqlalchemy import text

    as_of = datetime(2026, 2, 6, tzinfo=timezone.utc)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country) VALUES "
                "(80, 'OCBC', 'OCBC Bank', 'BANK', 'SG'), "
                "(81, 'IBKR', 'Interactive Brokers', 'BROKER', 'US')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, platform_id) VALUES "
                "(80, 'OCBC Savings', 'OCBC', 'BANK', 'SGD', 'SG', 80), "
                "(81, 'IBKR Brokerage', 'IBKR', 'BROKER', 'USD', 'US', 81)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(80, 'SGDCASH', 'SGD Cash', 'CASH', 'SGD', 'SG'), "
                "(81, 'AAPL', 'Apple Inc', 'STOCK', 'USD', 'US')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallets (id, chain_type, chain, address, label, status, created_at) VALUES "
                "('wallet-bootstrap-test', 'evm', 'ethereum', '0xBOOT', 'Bootstrap Wallet', 'active', :as_of)"
            ),
            {"as_of": as_of},
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshots (id, wallet_id, as_of_date, fetched_at, total_usd) VALUES "
                "(800, 'wallet-bootstrap-test', '2026-02-06', :as_of, 5000.0)"
            ),
            {"as_of": as_of},
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshot_items "
                "(id, snapshot_id, chain_type, chain, asset_kind, symbol, normalized_amount, value_usd) VALUES "
                "(800, 800, 'evm', 'ethereum', 'native', 'ETH', 2.0, 5000.0)"
            )
        )
    seed_canonical_account_balance_for_test(
        db_engine,
        account_id=80,
        as_of=as_of,
        currency="SGD",
        balance_base=50000,
        balance_type="bank_cash",
    )
    seed_canonical_position_snapshot_for_test(
        db_engine,
        account_id=81,
        asset_id=81,
        as_of=as_of,
        quantity=100,
        market_value_base=20000,
        market_price=200,
        cost_basis_base=15000,
        currency="USD",
        platform_code="IBKR",
    )

    def fake_rates(_date, _base, symbols):
        return {s: 1.0 for s in symbols}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/bootstrap?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200
    body = resp.json()

    # All four required BootstrapResponse numeric fields must be present
    assert "net_worth" in body, "net_worth missing from bootstrap response"
    assert isinstance(body["net_worth"]["total"], (int, float))
    assert "stock_exposure_total" in body, "stock_exposure_total missing"
    # AAPL: no latest price, so falls back to cost_basis_base=20000 (rate=1.0 for USD)
    assert body["stock_exposure_total"] == pytest.approx(20000.0, rel=1e-4), (
        f"stock_exposure_total expected ~20000, got {body['stock_exposure_total']}"
    )
    assert "crypto_exposure_total" in body, "crypto_exposure_total missing"
    assert isinstance(body["crypto_exposure_total"], (int, float))
    assert "cash_percent" in body, "cash_percent missing"
    assert isinstance(body["cash_percent"], (int, float))
    # snapshot_day must reflect configured env value
    assert body["snapshot_day"] == 1, f"snapshot_day expected 1, got {body['snapshot_day']}"

    # Secondary fields must NOT be present
    for forbidden in ("geography", "top_holdings", "cashflow", "compare", "net_worth_change"):
        assert forbidden not in body, f"bootstrap response must not include '{forbidden}'"


def test_dashboard_summary_skip_networth(client: TestClient, seed_dashboard_data, monkeypatch):
    """skip_networth=true must omit net_worth/net_worth_as_of/net_worth_change and still return geography etc."""
    def fake_rates(_date, _base, symbols):
        return {s: 1.0 for s in symbols}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/summary?month=2026-02&skip_networth=true")
    assert resp.status_code == 200
    body = resp.json()

    # These fields must be absent when skip_networth=true
    assert "net_worth" not in body, "net_worth must be omitted when skip_networth=true"
    assert "net_worth_as_of" not in body, "net_worth_as_of must be omitted when skip_networth=true"
    assert "net_worth_change" not in body, "net_worth_change must be omitted when skip_networth=true"

    # These fields must still be present
    assert "geography" in body
    assert "top_holdings" in body
    assert "cash_flow" in body
    assert "cash_balances" in body
    assert "snapshot_day" in body
    assert body["snapshot_day"] == 1

    # Denominator fix: geography and top_holdings must be non-empty when seed data provides positions
    assert len(body["geography"]) > 0, "geography must be non-empty when position data exists"
    assert len(body["top_holdings"]) > 0, "top_holdings must be non-empty when position data exists"

    # All geography entries must have a non-zero percent (denominator was real, not 0.0)
    for entry in body["geography"]:
        assert entry["percent"] != 0.0, f"geography entry {entry} has zero percent — denominator was 0.0"


def test_dashboard_summary_snapshot_day_returned(client: TestClient, seed_dashboard_data, monkeypatch):
    """snapshot_day must reflect the SNAPSHOT_DAY env var value, not null."""
    def fake_rates(_date, _base, symbols):
        return {s: 1.0 for s in symbols}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/summary?month=2026-02")
    assert resp.status_code == 200
    body = resp.json()
    assert body["snapshot_day"] == 1, f"snapshot_day expected 1, got {body['snapshot_day']}"


def test_dashboard_summary_snapshot_day_drives_next_month_anchor(client: TestClient, seed_dashboard_data, monkeypatch):
    def fake_rates(_date, _base, symbols):
        return {s: 1.0 for s in symbols}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)
    monkeypatch.setenv("SNAPSHOT_DAY", "6")

    resp = client.get("/dashboard/summary?month=2026-02")
    assert resp.status_code == 200
    body = resp.json()
    assert body["snapshot_day"] == 6
    assert body["net_worth_as_of"] == "2026-03-06T00:00:00+00:00"
    assert body["net_worth_boundary_at"] == "2026-03-06T00:00:00+00:00"


def test_dashboard_summary_exposes_current_net_worth_separately_from_snapshot(client: TestClient, db_engine, seed_dashboard_data, monkeypatch):
    def fake_rates(_date, _base, symbols):
        return {s: 1.0 for s in symbols}

    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO broker_import_runs "
                "(id, broker_account_id, legacy_account_id, platform_code, source_type, import_scope, status, metadata_json) VALUES "
                "(3, 1, 2, 'IBKR', 'test', 'daily', 'completed', '{}')"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO portfolio_nav_snapshots
                  (id, broker_account_id, legacy_account_id, import_run_id, report_date, base_currency,
                   cash_base, stock_base, total_nav_base, authority_status, metadata_json)
                VALUES
                  (3, 1, 2, 3, '2026-03-09', 'SGD', 0, 55000, 55000, 'authoritative', '{}')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO portfolio_position_snapshots
                  (id, broker_account_id, legacy_account_id, broker_instrument_id, import_run_id, report_date,
                   quantity, currency, market_price, market_value_local, market_value_base,
                   cost_basis_local, cost_basis_base, fx_rate_to_base, authority_status, metadata_json)
                VALUES
                  (3, 1, 2, 1, 3, '2026-03-09', 10, 'USD', 5500, 55000, 55000, 50000, 50000, 1, 'authoritative', '{}')
                """
            )
        )

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)
    monkeypatch.setattr(
        "app.routers.dashboard._current_anchor_ts",
        lambda: datetime(2026, 3, 10, tzinfo=timezone.utc),
    )

    resp = client.get("/dashboard/summary?month=2026-02&compare=prev_month")
    assert resp.status_code == 200
    body = resp.json()

    assert body["net_worth_as_of"] == "2026-03-01T00:00:00+00:00"
    assert body["current_net_worth_as_of"] == "2026-03-10T00:00:00+00:00"
    assert body["current_net_worth"]["stocks_funds"] == body["net_worth"]["stocks_funds"] + 5000.0
    assert body["current_net_worth_freshness"]["market_data_as_of"] == "2026-03-09"


def test_dashboard_summary_current_month_uses_last_completed_snapshot_anchor(client: TestClient, db_engine, monkeypatch):
    def fake_rates(_date, _base, symbols):
        return {s: 1.0 for s in symbols}

    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country) VALUES "
                "(610, 'IBKR', 'Interactive Brokers', 'BROKER', 'US')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country, platform_id) VALUES "
                "(610, 'IBKR Main', 'IBKR', 1, 'BROKER', 'USD', 'US', 610)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(610, 'AAPL', 'Apple Inc.', 'STOCK', 'USD', 'US')"
            )
        )
        snapshot_as_of = datetime(2026, 5, 1, tzinfo=timezone.utc)
        current_as_of = datetime(2026, 5, 15, tzinfo=timezone.utc)
        conn.execute(
            text(
                "INSERT INTO prices (asset_id, ts, price, currency, source, trade_date, exchange_code, provider_symbol) VALUES "
                "(610, :snapshot_as_of, 100, 'USD', 'finnhub_market', '2026-05-01', 'US', 'AAPL'), "
                "(610, :current_as_of, 120, 'USD', 'finnhub_market', '2026-05-15', 'US', 'AAPL')"
            ),
            {"snapshot_as_of": snapshot_as_of, "current_as_of": current_as_of},
        )
    seed_canonical_position_snapshot_for_test(
        db_engine,
        account_id=610,
        asset_id=610,
        as_of=snapshot_as_of,
        quantity=10,
        market_value_base=1000,
        market_price=100,
        cost_basis_base=1000,
        currency="USD",
        platform_code="IBKR",
    )
    seed_canonical_position_snapshot_for_test(
        db_engine,
        account_id=610,
        asset_id=610,
        as_of=current_as_of,
        quantity=20,
        market_value_base=2400,
        market_price=120,
        cost_basis_base=2000,
        currency="USD",
        platform_code="IBKR",
    )

    monkeypatch.setenv("SNAPSHOT_DAY", "1")
    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)
    monkeypatch.setattr(
        "app.routers.dashboard._current_anchor_ts",
        lambda: datetime(2026, 5, 24, tzinfo=timezone.utc),
    )

    resp = client.get("/dashboard/summary?month=2026-05&base_currency=USD")
    assert resp.status_code == 200
    body = resp.json()

    assert body["net_worth_boundary_at"] == "2026-05-01T00:00:00+00:00"
    assert body["net_worth_snapshot_as_of"] == "2026-05-01T00:00:00+00:00"
    assert body["net_worth"]["stocks_funds"] == 1000.0
    assert body["current_net_worth_as_of"] == "2026-05-24T00:00:00+00:00"
    assert body["current_net_worth"]["stocks_funds"] == 2400.0
