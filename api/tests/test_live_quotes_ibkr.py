"""#124: live views price IBKR (NAV-snapshot) holdings with the price job's quote
when it is at least as recent as IBKR's report; IBKR's price is a marked fallback."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.portfolio.ibkr_flex import run_ibkr_flex_import_from_xml
from tests.test_ibkr_flex_phase1 import _seed_ibkr_account, _valid_flex_xml

TODAY = date.today()
REPORT = TODAY - timedelta(days=3)
CURRENT_MONTH = TODAY.strftime("%Y-%m")


def _import_recent_statement(db_engine, tmp_path, monkeypatch) -> None:
    # The phase-1 fixture (AAPL: 10 @ 100 USD, 1350 in base; NAV 1521, cash 167.5),
    # moved to a few days ago so the current month is a live view.
    xml = (
        _valid_flex_xml()
        .replace("2026-02-20", REPORT.isoformat())
        .replace("2026-02-21", (REPORT + timedelta(days=1)).isoformat())
        .replace("2026-02-22", (REPORT + timedelta(days=2)).isoformat())
    )
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_ibkr_account(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) "
                "VALUES (950, 'AAPL', 'Apple Inc.', 'STOCK', 'USD', 'US')"
            )
        )
    db = sessionmaker(bind=db_engine)()
    try:
        run_ibkr_flex_import_from_xml(
            db,
            current_user_id=1,
            legacy_account_id=300,
            xml_text=xml,
            cutover_date=REPORT - timedelta(days=10),
        )
    finally:
        db.close()


def _add_quote(db_engine, trade_date: date, price: float) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO prices (asset_id, ts, price, currency, source, trade_date, exchange_code, provider_symbol) "
                "VALUES (950, :ts, :price, 'USD', 'finnhub_market', :trade_date, 'US', 'AAPL')"
            ),
            {"ts": f"{trade_date.isoformat()}T21:00:00+00:00", "price": price, "trade_date": trade_date.isoformat()},
        )


def _aapl(payload: dict) -> dict:
    return next(row for row in payload["top_holdings"] if row["symbol"] == "AAPL")


def _stock_holdings(client) -> dict:
    response = client.get(f"/dashboard/stock-holdings?month={CURRENT_MONTH}&base_currency=SGD")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["is_live"] is True
    return payload


def test_newer_quote_prices_ibkr_holding_and_moves_the_totals(client, db_engine, tmp_path, monkeypatch):
    _import_recent_statement(db_engine, tmp_path, monkeypatch)
    _add_quote(db_engine, TODAY - timedelta(days=1), 150.0)

    payload = _stock_holdings(client)
    aapl = _aapl(payload)
    assert aapl["latest_price"] == pytest.approx(150.0)
    assert aapl["price_source"] == "finnhub_market"
    assert aapl["price_fallback_reason"] is None
    # 10 x 150 USD at the statement's own USD->SGD rate (1.35, in portfolio_fx_rates,
    # #139): it is the newest stored rate within the lookback, so no provider call.
    assert aapl["value"] == pytest.approx(2025.0)
    # IBKR stock value 1353.5 (NAV 1521 - cash 167.5) + (2025 - 1350) at the new price.
    assert payload["stock_current_total"] == pytest.approx(2028.5)

    allocation = client.get(f"/dashboard/platform-allocation?month={CURRENT_MONTH}&base_currency=SGD").json()
    assert allocation["total"] == pytest.approx(2196.0)  # NAV 1521 + 675


def test_no_quote_falls_back_to_ibkr_price_with_reason(client, db_engine, tmp_path, monkeypatch):
    _import_recent_statement(db_engine, tmp_path, monkeypatch)

    aapl = _aapl(_stock_holdings(client))
    assert aapl["latest_price"] == pytest.approx(100.0)
    assert aapl["price_source"] == "ibkr_flex"
    assert aapl["price_fallback_reason"] == "no_quote"
    assert aapl["latest_trade_date"].startswith(REPORT.isoformat())


def test_quote_older_than_ibkr_report_is_not_used(client, db_engine, tmp_path, monkeypatch):
    _import_recent_statement(db_engine, tmp_path, monkeypatch)
    _add_quote(db_engine, REPORT - timedelta(days=2), 90.0)

    payload = _stock_holdings(client)
    aapl = _aapl(payload)
    assert aapl["latest_price"] == pytest.approx(100.0)
    assert aapl["price_fallback_reason"] == "quote_older"
    assert payload["stock_current_total"] == pytest.approx(1353.5)


def test_implausible_quote_is_ignored(client, db_engine, tmp_path, monkeypatch):
    _import_recent_statement(db_engine, tmp_path, monkeypatch)
    _add_quote(db_engine, TODAY - timedelta(days=1), 1000.0)  # 10x: a mis-mapped symbol

    aapl = _aapl(_stock_holdings(client))
    assert aapl["latest_price"] == pytest.approx(100.0)
    assert aapl["price_fallback_reason"] == "quote_implausible"


def test_past_months_keep_ibkr_snapshot_values(client, db_engine, tmp_path, monkeypatch):
    _import_recent_statement(db_engine, tmp_path, monkeypatch)
    _add_quote(db_engine, TODAY - timedelta(days=1), 150.0)
    next_month = (TODAY.replace(day=1) + timedelta(days=32)).replace(day=1)
    # A past-month view is never live: snapshot values, no fallback marker.
    from app.valuation.clock import _anchor_ts, _parse_month
    from app.valuation.facts import _networth_components

    db = sessionmaker(bind=db_engine)()
    try:
        components = _networth_components(
            db,
            _anchor_ts(_parse_month(CURRENT_MONTH)).replace(year=next_month.year, month=next_month.month),
            "SGD",
            1,
            price_overlay=False,
        )
    finally:
        db.close()
    assert components["stocks_funds"] == pytest.approx(1353.5)
