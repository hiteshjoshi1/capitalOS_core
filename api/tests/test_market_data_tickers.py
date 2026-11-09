"""#320: NSE → BSE ticker fallback, and setting a Yahoo ticker from the Market data page.
Yahoo (yfinance) is always mocked; synthetic symbols only."""
from datetime import date

import pytest
from sqlalchemy import text

from app.market_data import providers
from app.market_data.service import bse_symbol_for
from tests.auth_helpers import signed_in_client

TRADE = date(2026, 11, 6)


@pytest.fixture(autouse=True)
def _no_dividend_fetch(monkeypatch):
    monkeypatch.setattr(
        "app.market_data.providers.YFinanceProvider.fetch_dividend_yields",
        lambda self, symbols, exchange_code=None, trade_date=None: {},
    )


def _asset(db_engine, asset_id, symbol, *, override=None):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) "
                "VALUES (:id, :symbol, :symbol, 'STOCK', 'INR', 'IN')"
            ),
            {"id": asset_id, "symbol": symbol},
        )
        conn.execute(
            text(
                """
                INSERT INTO market_symbol_map
                  (asset_id, exchange_code, exchange_symbol, quote_currency, is_active, yahoo_symbol_override)
                VALUES (:id, 'NSE', :symbol, 'INR', 1, :override)
                """
            ),
            {"id": asset_id, "symbol": symbol, "override": override},
        )


def _quote(symbol, close):
    return providers.EodQuote(provider="yfinance", symbol=symbol, trade_date=TRADE, close=close, currency="INR")


def _fake_yfinance(prices, calls):
    def fake(self, symbols, exchange_code=None, trade_date=None):
        calls.append(list(symbols))
        return {s.upper(): _quote(s.upper(), prices[s.upper()]) for s in symbols if s.upper() in prices}

    return fake


def _override(db_engine, asset_id):
    with db_engine.begin() as conn:
        return conn.execute(
            text("SELECT yahoo_symbol_override FROM market_symbol_map WHERE asset_id = :id"), {"id": asset_id}
        ).scalar()


def _latest_price(db_engine, asset_id):
    with db_engine.begin() as conn:
        return conn.execute(
            text("SELECT price, provider_symbol FROM prices WHERE asset_id = :id ORDER BY id DESC LIMIT 1"),
            {"id": asset_id},
        ).fetchone()


def test_bse_symbol_for():
    assert bse_symbol_for("SYNTHA.NS") == "SYNTHA.BO"
    assert bse_symbol_for("SYNTHA.BO") is None
    assert bse_symbol_for("D05.SI") is None


def test_no_nse_quote_falls_back_to_bse_and_saves_the_override(client, db_engine, monkeypatch):
    _asset(db_engine, 3201, "SYNTHA")
    calls = []
    monkeypatch.setattr(
        "app.market_data.providers.YFinanceProvider.fetch_prices", _fake_yfinance({"SYNTHA.BO": 1908.35}, calls)
    )
    monkeypatch.setattr("app.market_data.providers.YahooProvider.fetch_prices", lambda self, s, **kw: {})

    resp = client.post("/market-data/refresh-now?exchange=NSE")
    assert resp.status_code == 200
    nse = resp.json()["exchanges"][0]
    assert nse["upserted_rows"] == 1 and nse["missing_symbols"] == 0
    assert "yfinance_bse" in nse["providers"]
    assert _override(db_engine, 3201) == "SYNTHA.BO"
    assert _latest_price(db_engine, 3201) == (1908.35, "SYNTHA.BO")
    with db_engine.begin() as conn:
        note = conn.execute(
            text("SELECT source_note FROM market_data_run_items WHERE asset_id = 3201 AND status = 'fallback_upserted'")
        ).scalar()
    assert note and note.startswith("auto:")

    # The next refresh asks for the BSE ticker directly.
    calls.clear()
    client.post("/market-data/refresh-now?exchange=NSE")
    assert calls and calls[0] == ["SYNTHA.BO"]


def test_neither_nse_nor_bse_stays_unpriced(client, db_engine, monkeypatch):
    _asset(db_engine, 3202, "SYNTHB")
    calls = []
    monkeypatch.setattr("app.market_data.providers.YFinanceProvider.fetch_prices", _fake_yfinance({}, calls))
    monkeypatch.setattr("app.market_data.providers.YahooProvider.fetch_prices", lambda self, s, **kw: {})

    nse = client.post("/market-data/refresh-now?exchange=NSE").json()["exchanges"][0]
    assert nse["upserted_rows"] == 0 and nse["missing_symbols"] == 1
    assert ["SYNTHB.BO"] in calls
    assert _override(db_engine, 3202) is None
    assert _latest_price(db_engine, 3202) is None


def test_a_set_override_is_never_replaced_by_the_fallback(client, db_engine, monkeypatch):
    _asset(db_engine, 3203, "SYNTHC", override="SYNTHCX.NS")
    calls = []
    monkeypatch.setattr(
        "app.market_data.providers.YFinanceProvider.fetch_prices", _fake_yfinance({"SYNTHCX.BO": 10.0}, calls)
    )
    monkeypatch.setattr("app.market_data.providers.YahooProvider.fetch_prices", lambda self, s, **kw: {})

    client.post("/market-data/refresh-now?exchange=NSE")
    assert all("SYNTHCX.BO" not in batch for batch in calls)
    assert _override(db_engine, 3203) == "SYNTHCX.NS"


def test_fallback_can_be_turned_off(client, db_engine, monkeypatch):
    monkeypatch.setenv("MARKET_DATA_BSE_FALLBACK", "0")
    _asset(db_engine, 3204, "SYNTHD")
    calls = []
    monkeypatch.setattr(
        "app.market_data.providers.YFinanceProvider.fetch_prices", _fake_yfinance({"SYNTHD.BO": 5.0}, calls)
    )
    monkeypatch.setattr("app.market_data.providers.YahooProvider.fetch_prices", lambda self, s, **kw: {})

    client.post("/market-data/refresh-now?exchange=NSE")
    assert all("SYNTHD.BO" not in batch for batch in calls)
    assert _override(db_engine, 3204) is None


def test_refresh_one_unknown_exchange_is_refused(client):
    assert client.post("/market-data/refresh-now?exchange=MOON").status_code == 422


def test_ticker_test_is_admin_only_and_reports_the_close(client, db_engine, monkeypatch):
    monkeypatch.setattr(
        "app.market_data.providers.YFinanceProvider.fetch_prices", _fake_yfinance({"SYNTHE.BO": 42.5}, [])
    )
    found = client.post("/market-data/ticker-test", json={"yahoo_symbol": "synthe.bo", "exchange_code": "NSE"}).json()
    assert found["found"] is True and found["yahoo_symbol"] == "SYNTHE.BO" and found["close"] == 42.5
    assert found["trade_date"] == TRADE.isoformat()

    missing = client.post("/market-data/ticker-test", json={"yahoo_symbol": "SYNTHE", "exchange_code": "NSE"}).json()
    assert missing["found"] is False and missing["yahoo_symbol"] == "SYNTHE.NS"
    assert "no quote" in missing["error"]

    bad = client.post("/market-data/ticker-test", json={"yahoo_symbol": "not a ticker"}).json()
    assert bad["found"] is False and bad["error"] == "Not a ticker"

    viewer = signed_in_client(db_engine, 3290)
    assert viewer.post("/market-data/ticker-test", json={"yahoo_symbol": "SYNTHE.BO"}).status_code == 403


def test_set_ticker_saves_the_override_and_prices_the_holding(client, db_engine, monkeypatch):
    _asset(db_engine, 3205, "SYNTHF")
    monkeypatch.setattr(
        "app.market_data.providers.YFinanceProvider.fetch_prices", _fake_yfinance({"SYNTHF.BO": 77.0}, [])
    )
    resp = client.post("/market-data/ticker", json={"asset_id": 3205, "exchange_code": "NSE", "yahoo_symbol": "SYNTHF.BO"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["action"] == "set" and body["close"] == 77.0 and body["currency"] == "INR"
    assert _override(db_engine, 3205) == "SYNTHF.BO"
    assert _latest_price(db_engine, 3205) == (77.0, "SYNTHF.BO")

    # Yahoo has nothing: nothing is saved.
    resp = client.post("/market-data/ticker", json={"asset_id": 3205, "exchange_code": "NSE", "yahoo_symbol": "NOPE.BO"})
    assert resp.status_code == 422
    assert _override(db_engine, 3205) == "SYNTHF.BO"

    viewer = signed_in_client(db_engine, 3291)
    resp = viewer.post("/market-data/ticker", json={"asset_id": 3205, "exchange_code": "NSE", "yahoo_symbol": "SYNTHF.BO"})
    assert resp.status_code == 403


def test_set_ticker_creates_the_map_row_when_there_is_none(client, db_engine, monkeypatch):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) "
                "VALUES (3206, 'SYNTHG', 'SYNTHG', 'STOCK', 'INR', 'IN')"
            )
        )
    monkeypatch.setattr(
        "app.market_data.providers.YFinanceProvider.fetch_prices", _fake_yfinance({"SYNTHG.BO": 3.0}, [])
    )
    body = client.post(
        "/market-data/ticker", json={"asset_id": 3206, "exchange_code": "NSE", "yahoo_symbol": "SYNTHG.BO"}
    ).json()
    assert body["action"] == "create_map"
    assert _override(db_engine, 3206) == "SYNTHG.BO"


def test_unpriced_list_suggests_tickers_and_says_who_can_fix(client, db_engine, monkeypatch):
    item = {
        "instrument_id": 1, "asset_id": 3207, "symbol": "SYNTHH", "name": "Synthetic H", "currency": "INR",
        "exchange_code": "NSE", "platform": "SHAREKHAN", "reason": "no_quote",
    }
    monkeypatch.setattr("app.routers.market_data.unpriced_held_positions", lambda db, user_id=None: [item])
    body = client.get("/market-data/unpriced").json()
    assert body["can_fix"] is True
    assert body["items"][0]["suggested_yahoo_symbols"] == ["SYNTHH.NS", "SYNTHH.BO"]

    viewer = signed_in_client(db_engine, 3292)
    assert viewer.get("/market-data/unpriced").json()["can_fix"] is False
