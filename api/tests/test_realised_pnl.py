"""#293 (D-78): realised P&L on sales. Synthetic trades only."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app import fx
from app.portfolio import realised as r
from app.portfolio.ibkr_flex import parse_flex_statement, run_ibkr_flex_import_from_xml, trade_metadata
from app.portfolio.realised_backfill import backfill_realised
from app.valuation import bridge


def _fill(tid, day, side, qty, proceeds, commission="-1", *, ibkr=None, rate=None, base="USD", inst="X", cur="USD"):
    return r.Fill(
        trade_id=tid,
        account_key=1,
        instrument_key=inst,
        trade_date=date.fromisoformat(day),
        side=side,
        quantity=Decimal(str(qty)),
        proceeds=Decimal(str(proceeds)),
        commission=Decimal(str(commission)),
        currency=cur,
        symbol=inst,
        account_base=base,
        ibkr_realised=Decimal(str(ibkr)) if ibkr is not None else None,
        fx_rate_to_base=Decimal(str(rate)) if rate is not None else None,
    )


def test_fifo_closes_the_oldest_lots_first_across_partial_sales():
    fills = [
        _fill(1, "2026-01-05", "BUY", 10, -1000),   # 10 @ 100 + 1 commission
        _fill(2, "2026-02-05", "BUY", 10, -1200),   # 10 @ 120 + 1
        _fill(3, "2026-03-05", "SELL", -5, 650),    # 5 from lot 1
        _fill(4, "2026-04-05", "SELL", -10, 1500),  # 5 from lot 1, 5 from lot 2
    ]
    sales = r.realised_sales(fills)
    assert [s.source for s in sales] == ["fifo", "fifo"]
    # sale 1: 650 - 1 - 5 x 100.1
    assert round(sales[0].realised, 2) == round(649 - 500.5, 2)
    # sale 2: 1500 - 1 - (5 x 100.1 + 5 x 120.1)
    assert round(sales[1].realised, 2) == round(1499 - 500.5 - 600.5, 2)


def test_a_sale_with_no_known_buy_has_no_cost_not_zero():
    sales = r.realised_sales([_fill(1, "2026-03-05", "SELL", -5, 650)])
    assert sales[0].source == "cost_unknown"
    assert sales[0].realised is None and sales[0].cost is None
    # A sale bigger than the known buys is unknown too.
    sales = r.realised_sales([_fill(1, "2026-01-05", "BUY", 2, -200), _fill(2, "2026-03-05", "SELL", -5, 650)])
    assert sales[0].source == "cost_unknown"


def test_ibkr_figure_wins_and_lots_are_still_closed():
    fills = [
        _fill(1, "2026-01-05", "BUY", 10, -1000),
        _fill(2, "2026-03-05", "SELL", -5, 650, ibkr="123.45"),
        _fill(3, "2026-04-05", "SELL", -5, 700),
    ]
    first, second = r.realised_sales(fills)
    assert first.source == "ibkr" and first.realised == 123.45
    assert round(first.cost, 2) == round(649 - 123.45, 2)
    # The IBKR sale still consumed 5 shares, so the next sale closes the other 5 by FIFO.
    assert second.source == "fifo" and round(second.realised, 2) == round(699 - 500.5, 2)


def test_lots_are_per_account_and_instrument():
    fills = [
        _fill(1, "2026-01-05", "BUY", 10, -1000, inst="A"),
        _fill(2, "2026-03-05", "SELL", -5, 650, inst="B"),
    ]
    assert r.realised_sales(fills)[0].source == "cost_unknown"


def test_base_uses_the_trade_dates_rate_and_leaves_out_a_missing_one(monkeypatch):
    calls = {}

    def fake_rates(dates, base, symbols):
        calls["symbols"] = set(symbols)
        return {fx.rate_date(d): fx.FxRates(base, {"USD": 1.35}) for d in dates}

    monkeypatch.setattr(fx, "get_rates_by_date", fake_rates)
    fills = [
        _fill(1, "2026-01-05", "BUY", 10, -1000),
        _fill(2, "2026-03-05", "SELL", -10, 1200),
        _fill(3, "2026-01-05", "BUY", 1, -100, cur="JPY", inst="J"),
        _fill(4, "2026-03-05", "SELL", -1, 200, cur="JPY", inst="J"),
    ]
    sales = r.realised_sales(fills)
    r.to_base(sales, {f.trade_id: f for f in fills}, "SGD")
    usd = next(s for s in sales if s.currency == "USD")
    jpy = next(s for s in sales if s.currency == "JPY")
    assert round(usd.realised_base, 2) == round(usd.realised * 1.35, 2)
    assert jpy.fx_missing and jpy.realised_base is None  # D-30: never 1.0
    t = r.totals(sales, date(2026, 1, 1), date(2026, 12, 31))
    assert t.realised_base == round(usd.realised * 1.35, 2)
    assert t.fx_missing_currencies == ["JPY"]


def test_the_fills_own_ibkr_rate_is_used_when_the_base_is_the_accounts(monkeypatch):
    monkeypatch.setattr(fx, "get_rates_by_date", lambda *a, **k: {})
    fills = [_fill(1, "2026-01-05", "BUY", 1, -100), _fill(2, "2026-03-05", "SELL", -1, 201, rate="1.30", base="SGD")]
    sales = r.realised_sales(fills)
    r.to_base(sales, {f.trade_id: f for f in fills}, "SGD")
    assert round(sales[0].realised_base, 2) == round(99.0 * 1.30, 2)


def test_totals_window_is_inclusive():
    sales = r.realised_sales([
        _fill(1, "2026-01-05", "BUY", 2, -200),
        _fill(2, "2026-03-01", "SELL", -1, 150),
        _fill(3, "2026-03-31", "SELL", -1, 150),
    ])
    for s in sales:
        s.realised_base = s.realised
    assert r.totals(sales, date(2026, 3, 1), date(2026, 3, 31)).sales == 2


SELL_XML_TRADE = """
            <Trade tradeDate="2026-02-21" settleDateTarget="2026-02-23" conid="265598" symbol="AAPL"
              description="APPLE INC" assetCategory="STK" listingExchange="NASDAQ" currency="USD"
              buySell="SELL" quantity="-1" tradePrice="130.00" proceeds="130.00" ibCommission="-1.00"
              fifoPnlRealized="28.00" fxRateToBase="1.34" ibExecID="E2" />
"""


def _xml_with_sale() -> str:
    from tests.test_ibkr_flex_phase1 import _valid_flex_xml

    return _valid_flex_xml().replace("</Trades>", SELL_XML_TRADE + "          </Trades>")


def test_flex_parser_keeps_ibkrs_realised_figure_and_rate():
    statement = parse_flex_statement(_xml_with_sale())
    sale = next(t for t in statement.trades if t.side == "SELL")
    assert trade_metadata(sale) == {"fifo_pnl_realized": "28.00", "fx_rate_to_base": "1.34"}
    buy = next(t for t in statement.trades if t.side == "BUY")
    assert "fifo_pnl_realized" not in trade_metadata(buy)


def test_imported_sale_reaches_the_endpoint_and_the_backfill_is_idempotent(client, db_engine, tmp_path, monkeypatch):
    from tests.test_ibkr_flex_phase1 import _seed_ibkr_account

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_ibkr_account(db_engine)
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        run_ibkr_flex_import_from_xml(
            db, current_user_id=1, legacy_account_id=300, xml_text=_xml_with_sale(),
            cutover_date=date(2026, 2, 1), reference_code="REF1",
        )
        meta = db.execute(text("SELECT metadata_json FROM portfolio_trades WHERE broker_execution_id = 'E2'")).scalar()
        assert json.loads(meta)["fifo_pnl_realized"] == "28.00"
        # The stored values are what the kept report says: the backfill has nothing to do.
        assert backfill_realised(db, apply=False).trades_updated == 0
        db.execute(text("UPDATE portfolio_trades SET metadata_json = '{}'"))
        db.commit()
        assert backfill_realised(db, apply=True).trades_updated == 1  # the sale; the fixture's buy has neither value
        assert json.loads(
            db.execute(text("SELECT metadata_json FROM portfolio_trades WHERE broker_execution_id = 'E2'")).scalar()
        )["fifo_pnl_realized"] == "28.00"
    finally:
        db.close()

    body = client.get("/dashboard/realised-pnl", params={"month": "2026-02", "base_currency": "USD"}).json()
    assert body["month"]["sales"] == 1
    assert body["month"]["sources"] == {"ibkr": 1}
    assert body["month"]["realised"] == 28.0
    assert body["year_to_date"]["realised"] == 28.0
    assert body["sales"][0]["symbol"] == "AAPL" and body["sales"][0]["source"] == "ibkr"
    # Another month: nothing.
    assert client.get("/dashboard/realised-pnl", params={"month": "2026-03"}).json()["month"]["sales"] == 0


def test_bridge_note_leaves_the_markets_total_unchanged(monkeypatch):
    lines = [
        {"key": "markets", "amount": 100.0, "parts": [{"key": "stocks", "label": "Stocks & funds", "amount": 100.0}], "notes": []},
        {"key": "fx", "amount": 5.0, "parts": [], "notes": []},
    ]
    monkeypatch.setattr(
        "app.portfolio.realised.realised_summary",
        lambda *a, **k: {"month": {"sales": 2, "realised": 42.5, "cost_unknown": 1, "fx_missing_currencies": []}},
    )
    from datetime import datetime, timezone

    bridge._add_realised_note(lines, None, 1, "SGD", datetime(2026, 3, 1, tzinfo=timezone.utc), datetime(2026, 3, 15, tzinfo=timezone.utc))
    markets = lines[0]
    assert markets["amount"] == 100.0 and sum(p["amount"] for p in markets["parts"]) == 100.0
    assert markets["notes"][0]["key"] == "realised" and markets["notes"][0]["amount"] == 42.5
    assert "1 with no known cost" in markets["notes"][0]["label"]
    assert lines[1] == {"key": "fx", "amount": 5.0, "parts": [], "notes": []}
