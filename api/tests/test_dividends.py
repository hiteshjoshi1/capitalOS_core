from sqlalchemy import text

from tests.canonical_test_helpers import seed_canonical_position_snapshot_for_test


def _seed_dividend_data(db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES
                (501, 'IBKR Main', 'IBKR', 'BROKER', 'USD', 'US')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES
                (901, 'AAPL', 'Apple Inc.', 'STOCK', 'USD', 'US')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO prices (id, asset_id, ts, price, currency, source, trade_date, exchange_code, provider_symbol) VALUES
                (801, 901, '2026-02-20T00:00:00+00:00', 200, 'USD', 'MANUAL', '2026-02-20', 'US', 'AAPL')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO transactions
                  (id, ts, account_id, amount, type, currency, asset_id, quantity, category, merchant_counterparty, source)
                VALUES
                  (601, '2026-01-15T00:00:00+00:00', 501, 100, 'INCOME', 'USD', 901, NULL, 'Brokerage::Dividend', 'AAPL DIVIDEND', 'IBKR'),
                  (602, '2026-01-15T00:00:00+00:00', 501, -15, 'TAX', 'USD', 901, NULL, 'Brokerage::Tax', 'AAPL DIVIDEND TAX', 'IBKR'),
                  (603, '2026-02-15T00:00:00+00:00', 501, 80, 'INCOME', 'USD', 901, NULL, 'Brokerage::Dividend', 'AAPL DIVIDEND', 'IBKR')
                """
            )
        )
    seed_canonical_position_snapshot_for_test(
        db_engine,
        account_id=501,
        asset_id=901,
        as_of="2026-02-06",
        quantity=100,
        market_value_base=15000,
        market_price=150,
        cost_basis_base=15000,
        currency="USD",
        platform_code="IBKR",
    )


def test_dividends_summary_by_month(client, db_engine):
    _seed_dividend_data(db_engine)
    resp = client.get(
        "/dividends/summary"
        "?from_month=2026-01&to_month=2026-02&period=month&base_currency=USD"
        "&assumed_tax_rate=0.1&country_tax_rates=US:0.2"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["from_month"] == "2026-01"
    assert data["to_month"] == "2026-02"
    assert data["period"] == "month"
    assert data["totals"]["gross"] == 180.0
    assert data["totals"]["withholding"] == 15.0
    assert data["totals"]["net_received"] == 165.0
    assert data["totals"]["estimated_tax"] == 36.0
    assert data["totals"]["payout_minus_tax"] == 129.0
    assert [bucket["bucket"] for bucket in data["buckets"]] == ["2026-01", "2026-02"]


def test_dividends_by_company_includes_yield(client, db_engine):
    _seed_dividend_data(db_engine)
    resp = client.get(
        "/dividends/by-company"
        "?from_month=2026-01&to_month=2026-02&base_currency=USD"
        "&assumed_tax_rate=0.1&country_tax_rates=US:0.2"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["totals"]["gross"] == 180.0
    assert len(data["items"]) == 1
    row = data["items"][0]
    assert row["asset_id"] == 901
    assert row["symbol"] == "AAPL"
    assert row["company"] == "Apple Inc."
    assert row["gross"] == 180.0
    assert row["withholding"] == 15.0
    assert row["net_received"] == 165.0
    assert row["estimated_tax"] == 36.0
    assert round(row["yield_pct"], 2) == 0.9


def test_dividends_history_by_asset(client, db_engine):
    _seed_dividend_data(db_engine)
    resp = client.get(
        "/dividends/history"
        "?asset_id=901&from_month=2026-01&to_month=2026-02&base_currency=USD"
        "&assumed_tax_rate=0.1&country_tax_rates=US:0.2"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["asset_id"] == 901
    assert data["symbol"] == "AAPL"
    assert data["company"] == "Apple Inc."
    assert data["totals"]["gross"] == 180.0
    assert data["totals"]["withholding"] == 15.0
    assert [event["month"] for event in data["events"]] == ["2026-01", "2026-02"]


def test_expected_dividends_overview_is_annualized_from_yield(client, db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES
                (510, 'IBKR Main', 'IBKR', 'BROKER', 'USD', 'US')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES
                (910, 'AAPL', 'Apple Inc.', 'STOCK', 'USD', 'US')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO market_symbol_map
                  (id, asset_id, exchange_code, exchange_symbol, quote_currency, is_active, yahoo_symbol_override)
                VALUES
                  (1, 910, 'US', 'AAPL', 'USD', 1, 'AAPL')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO market_dividend_yields
                  (asset_id, as_of_date, yield_rate, annual_dividend_per_share, price, currency, source, exchange_code, provider_symbol)
                VALUES
                  (910, '2026-03-31', 0.03, 6, 200, 'USD', 'yfinance_dividend', 'US', 'AAPL')
                """
            )
        )
    seed_canonical_position_snapshot_for_test(
        db_engine,
        account_id=510,
        asset_id=910,
        as_of="2026-03-06",
        quantity=10,
        market_value_base=1500,
        market_price=150,
        cost_basis_base=1500,
        currency="USD",
        platform_code="IBKR",
    )

    resp = client.get(
        "/dividends/expected/overview"
        "?from_month=2026-03&to_month=2026-03&base_currency=USD"
        "&assumed_tax_rate=10&country_tax_rates=US:15"
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["holdings_considered"] == 1
    assert payload["assets_with_actions"] == 1
    assert payload["actions_evaluated"] == 1
    # Annual gross = shares(10) * price(200) * yield(3%) = 60.
    assert round(payload["yearly"]["gross"], 2) == 60.0
    assert round(payload["yearly"]["estimated_tax"], 2) == 9.0
    assert round(payload["yearly"]["payout_minus_tax"], 2) == 51.0
    assert round(payload["quarterly"]["gross"], 2) == 15.0
    assert round(payload["monthly"]["gross"], 2) == 5.0
    assert len(payload["companies"]) == 1
    assert payload["companies"][0]["symbol"] == "AAPL"
    assert round(payload["companies"][0]["shares"], 2) == 10.0
    assert round(payload["companies"][0]["yield_pct"], 2) == 3.0
    assert round(payload["companies"][0]["yearly_dividend"], 2) == 60.0
    assert round(payload["companies"][0]["quarterly_dividend"], 2) == 15.0
    assert round(payload["companies"][0]["monthly_dividend"], 2) == 5.0


def test_expected_dividends_overview_ignores_dummy_source_snapshots(client, db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES
                (511, 'IBKR Main', 'IBKR', 'BROKER', 'USD', 'US')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES
                (911, 'COP', 'ConocoPhillips', 'STOCK', 'USD', 'US')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO market_dividend_yields
                  (asset_id, as_of_date, yield_rate, annual_dividend_per_share, price, currency, source, exchange_code, provider_symbol)
                VALUES
                  (911, '2026-03-31', 2.20, 2.53, 115, 'USD', 'DUMMY', 'US', 'COP'),
                  (911, '2026-03-30', 0.025, 3.18, 132, 'USD', 'yfinance_dividend', 'US', 'COP')
                """
            )
        )
    seed_canonical_position_snapshot_for_test(
        db_engine,
        account_id=511,
        asset_id=911,
        as_of="2026-03-06",
        quantity=10,
        market_value_base=1000,
        market_price=100,
        cost_basis_base=1000,
        currency="USD",
        platform_code="IBKR",
    )

    resp = client.get(
        "/dividends/expected/overview"
        "?from_month=2026-03&to_month=2026-03&base_currency=USD"
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload["companies"]) == 1
    # Uses yfinance snapshot (2.5%), not DUMMY (220%).
    assert round(payload["companies"][0]["yield_pct"], 2) == 2.5
    assert round(payload["companies"][0]["yearly_dividend"], 2) == 33.0
