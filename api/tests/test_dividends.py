from sqlalchemy import text


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
                INSERT INTO positions (id, account_id, asset_id, as_of, quantity, avg_cost, cost_basis_base) VALUES
                (701, 501, 901, '2026-02-06T00:00:00+00:00', 100, 150, 15000)
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
                INSERT INTO positions (id, account_id, asset_id, as_of, quantity, avg_cost, cost_basis_base) VALUES
                (710, 510, 910, '2026-03-06T00:00:00+00:00', 10, 150, 1500)
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
