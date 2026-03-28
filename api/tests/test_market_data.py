from datetime import datetime, timezone

from sqlalchemy import text

from app.market_data import providers


def test_market_data_refresh_and_status(client, db_engine, monkeypatch):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(100, 'AAPL', 'Apple', 'STOCK', 'USD', 'US')"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO market_symbol_map
                  (asset_id, exchange_code, exchange_symbol, quote_currency, is_active, eodhd_symbol_override, yahoo_symbol_override)
                VALUES
                  (100, 'US', 'AAPL', 'USD', 1, 'AAPL.US', 'AAPL')
                """
            )
        )

    def fake_finnhub(self, symbols, exchange_code=None, trade_date=None):
        return {
            "AAPL": providers.EodQuote(
                provider="finnhub",
                symbol="AAPL",
                trade_date=datetime(2026, 2, 6, tzinfo=timezone.utc).date(),
                close=195.0,
                currency="USD",
            )
        }

    def fake_eod(self, symbols, trade_date=None):
        return {}

    def fake_yahoo(self, symbols, exchange_code=None, trade_date=None):
        return {
            "AAPL": providers.EodQuote(
                provider="yahoo",
                symbol="AAPL",
                trade_date=datetime(2026, 2, 6, tzinfo=timezone.utc).date(),
                close=190.0,
                currency="USD",
            ),
        }

    monkeypatch.setattr("app.market_data.providers.FinnhubProvider.fetch_prices", fake_finnhub)
    monkeypatch.setattr("app.market_data.providers.EODHDProvider.fetch_eod_single", fake_eod)
    monkeypatch.setattr("app.market_data.providers.YahooProvider.fetch_prices", fake_yahoo)

    resp = client.post("/market-data/refresh-now")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["exchanges"][0]["exchange_code"] == "US"
    assert body["exchanges"][0]["upserted_rows"] == 1

    status = client.get("/market-data/status")
    assert status.status_code == 200
    rows = status.json()["status"]
    assert len(rows) >= 1
    assert rows[0]["exchange_code"] == "US"

    runs = client.get("/market-data/runs?limit=5")
    assert runs.status_code == 200
    run_rows = runs.json()["runs"]
    assert len(run_rows) >= 1


def test_market_data_fallback_to_yahoo(client, db_engine, monkeypatch):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(101, 'RELIANCE', 'Reliance', 'STOCK', 'INR', 'IN')"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO market_symbol_map
                  (asset_id, exchange_code, exchange_symbol, quote_currency, is_active, eodhd_symbol_override, yahoo_symbol_override)
                VALUES
                  (101, 'NSE', 'RELIANCE', 'INR', 1, 'RELIANCE.NSE', 'RELIANCE.NS')
                """
            )
        )

    def fake_yfinance(self, symbols, exchange_code=None, trade_date=None):
        return {}

    def fake_yahoo(self, symbols, exchange_code=None, trade_date=None):
        return {
            "RELIANCE.NS": providers.EodQuote(
                provider="yahoo",
                symbol="RELIANCE.NS",
                trade_date=datetime(2026, 2, 6, tzinfo=timezone.utc).date(),
                close=2941.25,
                currency="INR",
            )
        }

    monkeypatch.setattr("app.market_data.providers.YFinanceProvider.fetch_prices", fake_yfinance)
    monkeypatch.setattr("app.market_data.providers.YahooProvider.fetch_prices", fake_yahoo)

    resp = client.post("/market-data/refresh-now")
    assert resp.status_code == 200
    body = resp.json()
    nse = [x for x in body["exchanges"] if x["exchange_code"] == "NSE"][0]
    assert nse["upserted_rows"] == 1
    assert nse["missing_symbols"] == 0


def test_market_data_daily_limit_rotates_symbols(client, db_engine, monkeypatch):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(110, 'AAPL', 'Apple', 'STOCK', 'USD', 'US'),"
                "(111, 'MSFT', 'Microsoft', 'STOCK', 'USD', 'US')"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO market_symbol_map
                  (asset_id, exchange_code, exchange_symbol, quote_currency, is_active, yahoo_symbol_override)
                VALUES
                  (110, 'US', 'AAPL', 'USD', 1, 'AAPL'),
                  (111, 'US', 'MSFT', 'USD', 1, 'MSFT')
                """
            )
        )

    monkeypatch.setenv("STOCK_DAILY_SYMBOL_LIMIT", "1")

    def fake_finnhub(self, symbols, exchange_code=None, trade_date=None):
        out = {}
        for symbol in symbols:
            out[symbol] = providers.EodQuote(
                provider="finnhub",
                symbol=symbol,
                trade_date=datetime(2026, 2, 6, tzinfo=timezone.utc).date(),
                close=100.0 if symbol == "AAPL" else 200.0,
                currency="USD",
            )
        return out

    monkeypatch.setattr("app.market_data.providers.FinnhubProvider.fetch_prices", fake_finnhub)

    first = client.post("/market-data/refresh-now")
    assert first.status_code == 200
    assert first.json()["exchanges"][0]["requested_symbols"] == 1

    second = client.post("/market-data/refresh-now")
    assert second.status_code == 200
    assert second.json()["exchanges"][0]["requested_symbols"] == 1

    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT COUNT(DISTINCT asset_id)
                FROM prices
                WHERE source = 'finnhub_market'
                """
            )
        ).fetchone()
    assert int(rows[0]) == 2


def test_market_data_uses_asset_quote_currency_for_prices(client, db_engine, monkeypatch):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(120, '700', 'Tencent', 'STOCK', 'HKD', 'HK')"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO market_symbol_map
                  (asset_id, exchange_code, exchange_symbol, quote_currency, is_active, eodhd_symbol_override)
                VALUES
                  (120, 'HKEX', '700', 'HKD', 1, '700.HK')
                """
            )
        )

    def fake_yfinance(self, symbols, exchange_code=None, trade_date=None):
        assert symbols == ["0700.HK"]
        return {
            "0700.HK": providers.EodQuote(
                provider="yfinance",
                symbol="0700.HK",
                trade_date=datetime(2026, 2, 6, tzinfo=timezone.utc).date(),
                close=500.0,
                currency="USD",  # provider can be wrong/inconsistent
            )
        }

    monkeypatch.setattr("app.market_data.providers.YFinanceProvider.fetch_prices", fake_yfinance)

    resp = client.post("/market-data/refresh-now")
    assert resp.status_code == 200

    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT currency
                FROM prices
                WHERE asset_id = 120
                ORDER BY id DESC
                LIMIT 1
                """
            )
        ).fetchone()
    assert row is not None
    assert row[0] == "HKD"


def test_market_data_does_not_update_on_invalid_price(client, db_engine, monkeypatch):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(130, 'AAPL', 'Apple', 'STOCK', 'USD', 'US')"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO market_symbol_map
                  (asset_id, exchange_code, exchange_symbol, quote_currency, is_active, yahoo_symbol_override)
                VALUES
                  (130, 'US', 'AAPL', 'USD', 1, 'AAPL')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO prices (id, asset_id, ts, price, currency, source, trade_date, exchange_code, provider_symbol)
                VALUES (130, 130, :ts, 180, 'USD', 'finnhub_market', '2026-02-05', 'US', 'AAPL')
                """
            ),
            {"ts": datetime(2026, 2, 5, tzinfo=timezone.utc)},
        )

    def fake_finnhub(self, symbols, exchange_code=None, trade_date=None):
        return {
            "AAPL": providers.EodQuote(
                provider="finnhub",
                symbol="AAPL",
                trade_date=datetime(2026, 2, 6, tzinfo=timezone.utc).date(),
                close=0.0,  # invalid price; should not write
                currency="USD",
            )
        }

    monkeypatch.setattr("app.market_data.providers.FinnhubProvider.fetch_prices", fake_finnhub)

    resp = client.post("/market-data/refresh-now")
    assert resp.status_code == 200
    us = [x for x in resp.json()["exchanges"] if x["exchange_code"] == "US"][0]
    assert us["upserted_rows"] == 0

    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT trade_date, price
                FROM prices
                WHERE asset_id = 130 AND source = 'finnhub_market'
                ORDER BY trade_date DESC
                """
            )
        ).fetchall()
    assert len(rows) == 1
    assert str(rows[0][0]) == "2026-02-05"
    assert float(rows[0][1]) == 180.0
