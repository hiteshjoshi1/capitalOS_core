from datetime import datetime, timedelta, timezone

import httpx
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
                  (run_id, asset_id, provider, exchange_code, symbol, trade_date, status, price, currency, source_note, reason_code, created_at)
                VALUES
                  (150, 150, 'finnhub', 'US', 'REGN', '2026-02-06', 'missing', NULL, 'USD', 'provider timeout', 'PROVIDER_ERROR', :ts)
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
    assert regn["reason_code"] == "PROVIDER_ERROR"
    assert regn["latest_trade_date"] == "2026-02-01"


@pytest.mark.parametrize(
    "provider_name,provider_class",
    [
        ("eodhd", "EODHDProvider"),
        ("finnhub", "FinnhubProvider"),
        ("yfinance", "YFinanceProvider"),
        ("yahoo", "YahooProvider"),
    ],
)
@pytest.mark.parametrize(
    "outcome,expected_code",
    [("rate_limit", "RATE_LIMITED"), ("no_trade", "NO_TRADE_REPORTED")],
)
def test_market_data_classifies_provider_stale_reasons(
    client,
    db_engine,
    monkeypatch,
    provider_name,
    provider_class,
    outcome,
    expected_code,
):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(151, 'REGN', 'Regeneron', 'STOCK', 'USD', 'US')"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO market_symbol_map
                  (asset_id, exchange_code, exchange_symbol, quote_currency, is_active,
                   eodhd_symbol_override, yahoo_symbol_override)
                VALUES (151, 'US', 'REGN', 'USD', 1, 'REGN', 'REGN')
                """
            )
        )

    def fake_fetch(self, symbols, exchange_code=None, trade_date=None):
        if outcome == "no_trade":
            return {}
        request = httpx.Request("GET", "https://provider.example/quote")
        response = httpx.Response(429, request=request)
        raise httpx.HTTPStatusError("429 Too Many Requests", request=request, response=response)

    monkeypatch.setenv("STOCK_EXCHANGES", "US")
    monkeypatch.setenv("STOCK_PROVIDER_CHAIN_US", provider_name)
    monkeypatch.setattr(f"app.market_data.providers.{provider_class}.fetch_prices", fake_fetch)

    refresh = client.post("/market-data/refresh-now")
    assert refresh.status_code == 200
    status = client.get("/market-data/status")
    assert status.status_code == 200
    regn = status.json()["status"][0]["symbols"][0]
    assert regn["reason_code"] == expected_code
    if outcome == "rate_limit":
        assert regn["failure_reason"] == "429 Too Many Requests"
    else:
        assert regn["failure_reason"] is None


def test_market_data_scheduler_uses_grouped_refresh_windows(monkeypatch):
    monkeypatch.setattr(market_scheduler, "configured_exchanges", lambda: ["US", "SGX", "HKEX", "NSE"])
    for name in ("STOCK_REFRESH_ASIA_CLOSE", "STOCK_REFRESH_US_CLOSE"):
        monkeypatch.delenv(name, raising=False)

    plan = market_scheduler._window_plan(["US", "SGX", "HKEX", "NSE"])

    by_name = {name: (tz, hour, minute, exchanges) for name, tz, hour, minute, exchanges in plan}
    assert by_name["asia_close"] == ("Asia/Singapore", 18, 45, ["SGX", "HKEX", "NSE"])
    assert by_name["us_close"] == ("America/New_York", 17, 45, ["US"])


def test_market_data_scheduler_registers_one_due_check(monkeypatch):
    added_jobs = []
    created = {}

    class DummyScheduler:
        def __init__(self, timezone=None, job_defaults=None):
            created["job_defaults"] = job_defaults

        def add_job(self, func, trigger, kwargs=None, id=None, replace_existing=None, **extra):
            added_jobs.append({"func": func, "id": id})

        def start(self):
            return None

    monkeypatch.setattr(market_scheduler, "_scheduler", None)
    monkeypatch.setattr(market_scheduler, "BackgroundScheduler", DummyScheduler)
    monkeypatch.setattr(market_scheduler, "configured_exchanges", lambda: ["US"])
    monkeypatch.setenv("STOCK_PRICE_SCHEDULER_ENABLED", "1")

    assert market_scheduler.start_scheduler() is not None
    assert created["job_defaults"]["misfire_grace_time"] is None
    # The quote refresh check, plus the daily FX fill check (#139).
    assert [job["id"] for job in added_jobs] == ["stock_refresh_due_check", "fx_fill_due_check"]


def test_market_data_due_check_runs_only_windows_missed_since_their_close(monkeypatch):
    from app.core import catchup

    # 2026-11-03 08:00 SGT: the US close (17:45 New York, 2026-11-02) was slept
    # through; the Asia close (18:45 SGT, 2026-11-02) ran on time.
    now = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)
    last = {
        ("US",): datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc),
        ("SGX", "HKEX"): datetime(2026, 11, 2, 10, 45, 30, tzinfo=timezone.utc),
    }
    ran = []

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is None else now.astimezone(tz)

    monkeypatch.setattr(market_scheduler, "datetime", FrozenDatetime)
    monkeypatch.setattr(market_scheduler, "_retry_gates", {})
    monkeypatch.setattr(market_scheduler, "configured_exchanges", lambda: ["US", "SGX", "HKEX"])
    monkeypatch.setattr(market_scheduler, "_latest_success_for_exchanges", lambda ex: last[tuple(ex)])
    monkeypatch.setattr(market_scheduler, "_run_window", lambda name, ex: ran.append((name, ex)))
    for name in ("STOCK_REFRESH_ASIA_CLOSE", "STOCK_REFRESH_US_CLOSE"):
        monkeypatch.delenv(name, raising=False)

    market_scheduler._run_due_windows()

    assert ran == [("us_close", ["US"])]
    # The run didn't move US's last success, so it counts as failed: wait to retry.
    assert market_scheduler._retry_gates["us_close"].may_attempt(now + timedelta(minutes=5)) is False
    assert isinstance(market_scheduler._retry_gates["us_close"], catchup.RetryGate)


def test_market_data_due_check_runs_window_once_a_day_with_an_empty_exchange(db_engine, monkeypatch):
    """#137: SGX has no symbols, HKEX has one. The Asia window must run once after
    its close and then stay done; the real done-check reads market_data_runs."""
    from sqlalchemy.orm import sessionmaker

    import app.market_data.service as market_service
    from app.core.catchup import RetryGate

    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(170, 'TESTHK', 'Test HK Co', 'STOCK', 'HKD', 'HK')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO market_symbol_map (asset_id, exchange_code, exchange_symbol, quote_currency, is_active) "
                "VALUES (170, 'HKEX', '0001', 'HKD', 1)"
            )
        )

    clock = {"now": datetime(2026, 11, 3, 11, 0, tzinfo=timezone.utc)}  # 19:00 SGT, after the 18:45 close

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"] if tz is None else clock["now"].astimezone(tz)

    def fake_yfinance(self, symbols, exchange_code=None, trade_date=None):
        return {
            symbol: providers.EodQuote(
                provider="yfinance", symbol=symbol, trade_date=clock["now"].date(), close=10.0, currency="HKD"
            )
            for symbol in symbols
        }

    monkeypatch.setattr("app.market_data.providers.YFinanceProvider.fetch_prices", fake_yfinance)
    monkeypatch.setattr(market_scheduler, "datetime", FrozenDatetime)
    monkeypatch.setattr(market_service, "datetime", FrozenDatetime)
    monkeypatch.setattr(market_scheduler, "SessionLocal", sessionmaker(bind=db_engine, autocommit=False, autoflush=False))
    monkeypatch.setattr(market_scheduler, "_retry_gates", {})
    monkeypatch.setattr(market_scheduler, "configured_exchanges", lambda: ["SGX", "HKEX"])
    monkeypatch.delenv("STOCK_REFRESH_ASIA_CLOSE", raising=False)
    monkeypatch.delenv("SCHEDULER_RETRY_MINUTES", raising=False)
    windows = []
    real_run_window = market_scheduler._run_window
    monkeypatch.setattr(
        market_scheduler, "_run_window", lambda name, ex: (windows.append(name), real_run_window(name, ex))
    )

    def run_count() -> dict[str, int]:
        with db_engine.begin() as conn:
            rows = conn.execute(
                text("SELECT exchange_code, COUNT(*) FROM market_data_runs GROUP BY exchange_code")
            ).fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    market_scheduler._run_due_windows()
    assert windows == ["asia_close"]
    assert run_count() == {"SGX": 1, "HKEX": 1}
    with db_engine.begin() as conn:
        sgx = conn.execute(
            text("SELECT provider, status, requested_symbols, finished_at FROM market_data_runs WHERE exchange_code = 'SGX'")
        ).one()
    assert sgx[0] == market_service.EMPTY_EXCHANGE_PROVIDER
    assert sgx[1] == "success"
    assert sgx[2] == 0
    assert sgx[3] is not None
    assert market_scheduler._retry_gates["asia_close"].may_attempt(clock["now"])  # recorded as a success

    # Every later check that day, past several retry intervals: nothing runs.
    for minutes in (5, 30, 31, 60, 300, 600):
        clock["now"] = datetime(2026, 11, 3, 11, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)
        market_scheduler._run_due_windows()
    assert windows == ["asia_close"]
    assert run_count() == {"SGX": 1, "HKEX": 1}

    # The next day's close makes it due once more.
    clock["now"] = datetime(2026, 11, 4, 11, 0, tzinfo=timezone.utc)
    market_scheduler._run_due_windows()
    market_scheduler._run_due_windows()
    assert windows == ["asia_close", "asia_close"]
    assert run_count() == {"SGX": 2, "HKEX": 2}
    assert isinstance(market_scheduler._retry_gates["asia_close"], RetryGate)


def test_market_data_empty_exchange_run_is_listed_but_not_data_hub_activity(client, db_engine):
    """#137: the 0-symbol run shows in /market-data/runs and /market-data/status
    (it ran, nothing to fetch) but isn't 'Refreshed ... market data' activity."""
    from app.market_data.service import EMPTY_EXCHANGE_PROVIDER, run_exchange_refresh
    from sqlalchemy.orm import sessionmaker

    db = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)()
    try:
        result = run_exchange_refresh(db, "SGX", full_coverage=True)
    finally:
        db.close()
    assert result["status"] == "success"
    assert result["requested_symbols"] == 0
    assert list(result["run_ids"]) == [EMPTY_EXCHANGE_PROVIDER]

    runs = client.get("/market-data/runs?limit=5").json()["runs"]
    assert [(r["exchange_code"], r["provider"], r["status"], r["requested_symbols"]) for r in runs] == [
        ("SGX", EMPTY_EXCHANGE_PROVIDER, "success", 0)
    ]
    status = {row["exchange_code"]: row for row in client.get("/market-data/status").json()["status"]}
    if "SGX" in status:
        assert status["SGX"]["status"] == "success"
        assert status["SGX"]["diagnostics_summary"]["active_symbols"] == 0

    activity = client.get("/dashboard/data-hub-summary").json()["recent_activity"]
    assert not any(item["kind"] == "market_data" for item in activity)


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
