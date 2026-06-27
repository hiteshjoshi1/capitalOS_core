from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.market_data import providers
import app.market_data.scheduler as market_scheduler


@pytest.fixture(autouse=True)
def _stub_dividend_yield_fetch(monkeypatch):
    monkeypatch.setattr(
        "app.market_data.providers.YFinanceProvider.fetch_dividend_yields",
        lambda self, symbols, **kwargs: {},
    )


def test_yfinance_nse_symbol_normalization():
    provider = providers.YFinanceProvider()
    assert provider._normalize_symbol("NSE:RELIANCE", "NSE") == "RELIANCE.NS"
    assert provider._normalize_symbol("RELIANCE.NSE", "NSE") == "RELIANCE.NS"
    assert provider._normalize_symbol("M&M", "NSE") == "M&M.NS"
    assert provider._normalize_symbol("BRK.B", "US") == "BRK-B"
    assert provider._normalize_symbol("BRK B", "US") == "BRK-B"


def test_yfinance_dividend_yield_subunit_percent_hint_for_non_us():
    provider = providers.YFinanceProvider()
    value = provider._choose_reported_yield_rate(0.23, prefer_percent_for_subunit=True)
    assert value is not None
    assert value == pytest.approx(0.0023, rel=1e-9)


def test_yfinance_dividend_yield_subunit_uses_implied_anchor():
    provider = providers.YFinanceProvider()
    value = provider._choose_reported_yield_rate(0.23, implied_yield=0.0021)
    assert value is not None
    assert value == pytest.approx(0.0023, rel=1e-9)


def test_market_data_refresh_and_status(client, db_engine, monkeypatch):
    published_events = []

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
    monkeypatch.setattr(
        "app.routers.market_data.publish_portfolio_refresh",
        lambda user_id, **kwargs: published_events.append({"user_id": user_id, **kwargs}),
    )

    resp = client.post("/market-data/refresh-now")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["exchanges"][0]["exchange_code"] == "US"
    assert body["exchanges"][0]["upserted_rows"] == 1
    assert body["exchanges"][0]["full_coverage"] is True
    assert body["exchanges"][0]["diagnostics"]["diagnostics_summary"]["refreshed"] >= 1
    assert len(published_events) == 1
    assert published_events[0]["user_id"] == 1
    assert published_events[0]["event_name"] == "market_data_refresh_completed"
    assert published_events[0]["source"] == "market-data"
    assert published_events[0]["status"] == "completed"
    assert published_events[0]["payload"]["exchange_count"] >= 1

    status = client.get("/market-data/status")
    assert status.status_code == 200
    rows = status.json()["status"]
    assert len(rows) >= 1
    us_row = next(row for row in rows if row["exchange_code"] == "US")
    assert us_row["diagnostics_summary"]["active_symbols"] >= 1
    assert any(item["symbol"] == "AAPL" for item in us_row["symbols"])

    runs = client.get("/market-data/runs?limit=5")
    assert runs.status_code == 200
    run_rows = runs.json()["runs"]
    assert len(run_rows) >= 1


def test_market_data_backfills_class_share_symbols_with_spaces(client, db_engine, monkeypatch):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(131, 'BRK B', 'Berkshire Hathaway Inc. Class B', 'STOCK', 'USD', 'US')"
            )
        )

    def fake_finnhub(self, symbols, exchange_code=None, trade_date=None):
        assert "BRK.B" in symbols
        return {
            "BRK.B": providers.EodQuote(
                provider="finnhub",
                symbol="BRK.B",
                trade_date=datetime(2026, 5, 22, tzinfo=timezone.utc).date(),
                close=486.38,
                currency="USD",
            )
        }

    monkeypatch.setattr("app.market_data.providers.FinnhubProvider.fetch_prices", fake_finnhub)
    monkeypatch.setattr("app.market_data.providers.EODHDProvider.fetch_eod_single", lambda self, symbols, trade_date=None: {})
    monkeypatch.setattr(
        "app.market_data.providers.YahooProvider.fetch_prices",
        lambda self, symbols, exchange_code=None, trade_date=None: {},
    )

    resp = client.post("/market-data/refresh-now")
    assert resp.status_code == 200

    with db_engine.begin() as conn:
        mapped = conn.execute(
            text(
                """
                SELECT exchange_symbol
                FROM market_symbol_map
                WHERE asset_id = 131 AND exchange_code = 'US'
                """
            )
        ).scalar_one()
        price = conn.execute(
            text(
                """
                SELECT price
                FROM prices
                WHERE asset_id = 131 AND provider_symbol = 'BRK.B'
                """
            )
        ).scalar_one()

    assert mapped == "BRK.B"
    assert float(price) == 486.38


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


def test_market_data_refresh_now_covers_all_active_symbols(client, db_engine, monkeypatch):
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

    response = client.post("/market-data/refresh-now")
    assert response.status_code == 200
    us_exchange = next(item for item in response.json()["exchanges"] if item["exchange_code"] == "US")
    assert us_exchange["requested_symbols"] == 2
    assert us_exchange["total_active_symbols"] == 2
    assert us_exchange["deferred_symbols"] == 0
    assert us_exchange["diagnostics"]["diagnostics_summary"]["refreshed"] == 2

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


def test_market_data_refresh_updates_all_assets_sharing_provider_symbol(client, db_engine, monkeypatch):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(210, '700', 'Tencent Holding Legacy', 'STOCK', 'HKD', 'HK'),"
                "(211, '0700', 'Tencent Holdings', 'STOCK', 'HKD', 'HK')"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO market_symbol_map
                  (asset_id, exchange_code, exchange_symbol, quote_currency, is_active, yahoo_symbol_override)
                VALUES
                  (210, 'HKEX', '700', 'HKD', 1, NULL),
                  (211, 'HKEX', '0700', 'HKD', 1, '0700.HK')
                """
            )
        )

    monkeypatch.setenv("STOCK_EXCHANGES", "HKEX")

    def fake_yfinance(self, symbols, exchange_code=None, trade_date=None):
        assert symbols == ["0700.HK"]
        return {
            "0700.HK": providers.EodQuote(
                provider="yfinance",
                symbol="0700.HK",
                trade_date=datetime(2026, 6, 12, tzinfo=timezone.utc).date(),
                close=512.5,
                currency="HKD",
            )
        }

    monkeypatch.setattr("app.market_data.providers.YFinanceProvider.fetch_prices", fake_yfinance)
    monkeypatch.setattr(
        "app.market_data.providers.YahooProvider.fetch_prices",
        lambda self, symbols, exchange_code=None, trade_date=None: {},
    )

    response = client.post("/market-data/refresh-now")
    assert response.status_code == 200

    hkex = next(item for item in response.json()["exchanges"] if item["exchange_code"] == "HKEX")
    assert hkex["upserted_rows"] == 2
    assert hkex["missing_symbols"] == 0
    assert hkex["diagnostics"]["diagnostics_summary"]["refreshed"] == 2

    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT COUNT(DISTINCT asset_id)
                FROM prices
                WHERE source = 'yfinance_market' AND asset_id IN (210, 211)
                """
            )
        ).scalar_one()
    assert int(rows) == 2


def test_market_data_status_surfaces_stale_and_failed_symbol_diagnostics(client, db_engine, monkeypatch):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(150, 'REGN', 'Regeneron', 'STOCK', 'USD', 'US')"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO market_symbol_map
                  (asset_id, exchange_code, exchange_symbol, quote_currency, is_active, yahoo_symbol_override)
                VALUES
                  (150, 'US', 'REGN', 'USD', 1, 'REGN')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO prices (asset_id, ts, price, currency, source, trade_date, exchange_code, provider_symbol)
                VALUES (150, :ts, 500, 'USD', 'finnhub_market', '2026-02-01', 'US', 'REGN')
                """
            ),
            {"ts": datetime(2026, 2, 1, tzinfo=timezone.utc)},
        )
        conn.execute(
            text(
                """
                INSERT INTO market_data_runs
                  (id, provider, exchange_code, trade_date, status, requested_symbols, received_rows, upserted_rows, missing_symbols, started_at, finished_at, error_summary)
                VALUES
                  (150, 'finnhub', 'US', '2026-02-06', 'partial', 1, 0, 0, 1, :ts, :ts, 'provider timeout')
                """
            ),
            {"ts": datetime(2026, 2, 6, tzinfo=timezone.utc)},
        )
        conn.execute(
            text(
                """
                INSERT INTO market_data_run_items
                  (run_id, asset_id, provider, exchange_code, symbol, trade_date, status, price, currency, source_note, created_at)
                VALUES
                  (150, 150, 'finnhub', 'US', 'REGN', '2026-02-06', 'missing', NULL, 'USD', 'provider timeout', :ts)
                """
            ),
            {"ts": datetime(2026, 2, 6, tzinfo=timezone.utc)},
        )

    status = client.get("/market-data/status")
    assert status.status_code == 200
    us_row = next(row for row in status.json()["status"] if row["exchange_code"] == "US")
    regn = next(item for item in us_row["symbols"] if item["symbol"] == "REGN")
    assert regn["freshness_status"] == "stale"
    assert regn["refresh_status"] == "failed"
    assert regn["failure_reason"] == "provider timeout"
    assert regn["latest_trade_date"] == "2026-02-01"


def test_market_data_scheduler_uses_grouped_refresh_windows(monkeypatch):
    added_jobs = []

    class DummyScheduler:
        def __init__(self, timezone=None):
            self.timezone = timezone

        def add_job(self, func, trigger, kwargs=None, id=None, replace_existing=None, **_extra):
            added_jobs.append({"func": func, "kwargs": kwargs, "id": id, "replace_existing": replace_existing})

        def start(self):
            return None

    monkeypatch.setattr(market_scheduler, "_scheduler", None)
    monkeypatch.setattr(market_scheduler, "BackgroundScheduler", DummyScheduler)
    monkeypatch.setattr(market_scheduler, "configured_exchanges", lambda: ["US", "SGX", "HKEX", "NSE"])
    monkeypatch.setattr(market_scheduler, "_latest_successful_run_finished_at", lambda: None)
    monkeypatch.setenv("STOCK_PRICE_SCHEDULER_ENABLED", "1")

    scheduler = market_scheduler.start_scheduler()

    assert scheduler is not None
    job_ids = {job["id"] for job in added_jobs}
    assert "stock_refresh_startup_catchup" in job_ids
    assert "stock_refresh_asia_close" in job_ids
    assert "stock_refresh_us_close" in job_ids
    catchup_job = next(job for job in added_jobs if job["id"] == "stock_refresh_startup_catchup")
    assert catchup_job["kwargs"]["window_name"] == "startup_catchup"
    assert catchup_job["kwargs"]["exchanges"] == ["US", "SGX", "HKEX", "NSE"]
    asia_job = next(job for job in added_jobs if job["id"] == "stock_refresh_asia_close")
    assert asia_job["kwargs"]["exchanges"] == ["SGX", "HKEX", "NSE"]


def test_market_data_scheduler_skips_startup_catchup_when_prices_are_fresh(monkeypatch):
    added_jobs = []

    class DummyScheduler:
        def __init__(self, timezone=None):
            self.timezone = timezone

        def add_job(self, func, trigger, kwargs=None, id=None, replace_existing=None, **_extra):
            added_jobs.append({"func": func, "kwargs": kwargs, "id": id, "replace_existing": replace_existing})

        def start(self):
            return None

    monkeypatch.setattr(market_scheduler, "_scheduler", None)
    monkeypatch.setattr(market_scheduler, "BackgroundScheduler", DummyScheduler)
    monkeypatch.setattr(market_scheduler, "configured_exchanges", lambda: ["US"])
    monkeypatch.setattr(
        market_scheduler,
        "_latest_successful_run_finished_at",
        lambda: datetime.now(tz=timezone.utc) - timedelta(hours=2),
    )
    monkeypatch.setenv("STOCK_PRICE_SCHEDULER_ENABLED", "1")

    scheduler = market_scheduler.start_scheduler()

    assert scheduler is not None
    job_ids = {job["id"] for job in added_jobs}
    assert "stock_refresh_startup_catchup" not in job_ids
    assert "stock_refresh_us_close" in job_ids


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


def test_market_data_prefers_asset_symbol_for_us_map_drift(client, db_engine, monkeypatch):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(121, 'COP', 'ConocoPhillips', 'STOCK', 'USD', 'US')"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO market_symbol_map
                  (asset_id, exchange_code, exchange_symbol, quote_currency, is_active)
                VALUES
                  (121, 'US', 'CONOCOPHILLIPS', 'USD', 1)
                """
            )
        )

    def fake_finnhub(self, symbols, exchange_code=None, trade_date=None):
        assert symbols == ["COP"]
        return {
            "COP": providers.EodQuote(
                provider="finnhub",
                symbol="COP",
                trade_date=datetime(2026, 2, 6, tzinfo=timezone.utc).date(),
                close=132.0,
                currency="USD",
            )
        }

    monkeypatch.setattr("app.market_data.providers.FinnhubProvider.fetch_prices", fake_finnhub)

    resp = client.post("/market-data/refresh-now")
    assert resp.status_code == 200

    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT provider_symbol, currency
                FROM prices
                WHERE asset_id = 121
                ORDER BY id DESC
                LIMIT 1
                """
            )
        ).fetchone()
    assert row is not None
    assert row[0] == "COP"
    assert row[1] == "USD"


def test_market_data_auto_backfills_missing_nse_symbol_map(client, db_engine, monkeypatch):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(140, 'INFOSYS LIMITED', 'INFY', 'STOCK', 'INR', 'IN')"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES
                (540, 'Sharekhan', 'SHAREKHAN', 'BROKER', 'INR', 'IN')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO positions (id, account_id, asset_id, as_of, quantity, avg_cost, cost_basis_base) VALUES
                (740, 540, 140, '2026-03-06T00:00:00+00:00', 10, 1500, 15000)
                """
            )
        )

    def fake_yfinance(self, symbols, exchange_code=None, trade_date=None):
        assert exchange_code == "NSE"
        assert "INFY.NS" in symbols
        return {
            "INFY.NS": providers.EodQuote(
                provider="yfinance",
                symbol="INFY.NS",
                trade_date=datetime(2026, 2, 6, tzinfo=timezone.utc).date(),
                close=1500.0,
                currency="INR",
            )
        }

    monkeypatch.setattr("app.market_data.providers.YFinanceProvider.fetch_prices", fake_yfinance)

    resp = client.post("/market-data/refresh-now")
    assert resp.status_code == 200
    nse = [x for x in resp.json()["exchanges"] if x["exchange_code"] == "NSE"][0]
    assert nse["backfilled_symbols"] >= 1
    assert nse["upserted_rows"] >= 1

    with db_engine.begin() as conn:
        map_row = conn.execute(
            text(
                """
                SELECT exchange_code, exchange_symbol
                FROM market_symbol_map
                WHERE asset_id = 140
                LIMIT 1
                """
            )
        ).fetchone()
        assert map_row is not None
        assert map_row[0] == "NSE"
        assert map_row[1] == "INFY"


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
