"""#313: realised P&L for any period, grouped per stock, and the one-off IBKR Flex back-fill.
Synthetic data only; IBKR is never called (a fake client)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app import fx
from app.portfolio import realised as r
from app.portfolio.ibkr_flex import IbkrFlexClient, run_ibkr_flex_import_from_xml
from app.portfolio.ibkr_flex_backfill import plan_windows, run_backfill, summary_lines


def _fill(tid, day, side, qty, proceeds, commission="-1", *, ibkr=None, rate=None, base="USD", inst="X", cur="USD", acct=1):
    return r.Fill(
        trade_id=tid,
        account_key=acct,
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


# ─── periods ─────────────────────────────────────────────────────────────────
M_START, M_END = date(2026, 11, 1), date(2026, 11, 8)


def _period(key, today, **kw):
    return r.resolve_period(key, today=today, month_start=M_START, month_end=M_END, **kw)


def test_periods_resolve_in_the_users_calendar():
    today = date(2026, 11, 8)
    assert (_period("month", today).start, _period("month", today).end) == (M_START, M_END)
    ytd = _period("ytd", today)
    assert (ytd.start, ytd.end, ytd.label) == (date(2026, 1, 1), today, "2026 to date")
    last = _period("last_year", today)
    assert (last.start, last.end, last.label) == (date(2025, 1, 1), date(2025, 12, 31), "2025")
    assert _period("year", today, year=2025).end == date(2025, 12, 31)
    this_year = _period("year", today, year=2026)
    assert (this_year.end, this_year.label) == (today, "2026 to date")
    rng = _period("range", today, start=date(2026, 3, 1), end=date(2027, 1, 1))
    assert rng.end == today  # never after today


def test_new_years_day_edges():
    # On 1 Jan, "last year" is the whole year just ended and YTD is that one day.
    jan1 = date(2027, 1, 1)
    assert (_period("last_year", jan1).start, _period("last_year", jan1).end) == (date(2026, 1, 1), date(2026, 12, 31))
    assert (_period("ytd", jan1).start, _period("ytd", jan1).end) == (jan1, jan1)
    # On 31 Dec, "last year" is still the year before.
    assert _period("last_year", date(2026, 12, 31)).start == date(2025, 1, 1)


@pytest.mark.parametrize(
    "key,kw",
    [("bogus", {}), ("year", {}), ("year", {"year": 2099}), ("range", {"start": date(2026, 1, 1)}),
     ("range", {"start": date(2026, 5, 1), "end": date(2026, 4, 1)})],
)
def test_bad_periods_are_refused(key, kw):
    with pytest.raises(ValueError):
        _period(key, date(2026, 11, 8), **kw)


# ─── grouping ────────────────────────────────────────────────────────────────
def _sales(monkeypatch, fills, base="USD", rates=None):
    monkeypatch.setattr(
        fx, "get_rates_by_date",
        lambda dates, b, symbols: {fx.rate_date(d): fx.FxRates(b, dict(rates or {})) for d in dates},
    )
    sales = r.realised_sales(fills)
    r.to_base(sales, {f.trade_id: f for f in fills}, base)
    return sales


def test_grouped_per_stock_biggest_move_first_including_losses(monkeypatch):
    fills = [
        _fill(1, "2025-02-01", "BUY", 10, -1000, inst="AAA"),
        _fill(2, "2025-06-01", "SELL", -5, 600, inst="AAA"),   # +100 - 1 commission... fifo
        _fill(3, "2025-07-01", "SELL", -5, 650, inst="AAA"),
        _fill(4, "2025-03-01", "BUY", 1, -500, inst="BBB"),
        _fill(5, "2025-09-01", "SELL", -1, 100, inst="BBB"),    # a big loss
        _fill(6, "2026-01-02", "SELL", -1, 999, ibkr=1, inst="CCC"),  # next year: not in 2025
    ]
    sales = _sales(monkeypatch, fills)
    groups = r.by_instrument(sales, date(2025, 1, 1), date(2025, 12, 31))
    assert [g["symbol"] for g in groups] == ["BBB", "AAA"]  # |-402| > |+246|
    bbb, aaa = groups
    assert bbb["realised_base"] < 0 and aaa["realised_base"] > 0
    assert aaa["sales_count"] == 2 and aaa["quantity"] == 10
    assert aaa["realised_base"] == round(aaa["proceeds_base"] - aaa["cost_base"], 2)
    assert [s["trade_date"] for s in aaa["sales"]] == ["2025-06-01", "2025-07-01"]
    assert (aaa["first_sale"], aaa["last_sale"]) == ("2025-06-01", "2025-07-01")


def test_a_sale_on_31_dec_and_one_on_1_jan_fall_in_their_own_years(monkeypatch):
    fills = [
        _fill(1, "2025-12-31", "SELL", -1, 100, ibkr=10, inst="AAA"),
        _fill(2, "2026-01-01", "SELL", -1, 100, ibkr=20, inst="AAA"),
    ]
    sales = _sales(monkeypatch, fills)
    y25 = r.by_instrument(sales, date(2025, 1, 1), date(2025, 12, 31))
    y26 = r.by_instrument(sales, date(2026, 1, 1), date(2026, 12, 31))
    assert y25[0]["realised_base"] == 10 and y26[0]["realised_base"] == 20


def test_cost_unknown_is_named_and_kept_out_of_the_totals(monkeypatch):
    fills = [
        _fill(1, "2025-05-01", "SELL", -2, 300, inst="OLD"),  # bought before the history starts
        _fill(2, "2025-01-05", "BUY", 1, -100, inst="NEW"),
        _fill(3, "2025-05-01", "SELL", -1, 150, inst="NEW"),
    ]
    groups = r.by_instrument(_sales(monkeypatch, fills), date(2025, 1, 1), date(2025, 12, 31))
    assert [g["symbol"] for g in groups] == ["NEW", "OLD"]  # nothing in the total sorts last
    old = groups[1]
    assert old["cost_unknown"] == 1 and old["in_total"] == 0
    assert old["realised_base"] == 0 and old["proceeds_base"] == 0 and old["cost_base"] == 0
    assert old["sales"][0]["source"] == "cost_unknown" and old["sales"][0]["cost"] is None


def test_missing_fx_is_named_never_1(monkeypatch):
    fills = [
        _fill(1, "2025-01-05", "BUY", 1, -100, cur="JPY", inst="JJJ"),
        _fill(2, "2025-04-05", "SELL", -1, 300, cur="JPY", inst="JJJ"),
        _fill(3, "2025-01-05", "BUY", 1, -100, inst="UUU"),
        _fill(4, "2025-04-05", "SELL", -1, 200, inst="UUU"),
    ]
    groups = r.by_instrument(_sales(monkeypatch, fills, base="SGD", rates={"USD": 1.35}), date(2025, 1, 1), date(2025, 12, 31))
    jjj = next(g for g in groups if g["symbol"] == "JJJ")
    uuu = next(g for g in groups if g["symbol"] == "UUU")
    assert jjj["fx_missing"] and jjj["in_total"] == 0 and jjj["realised_base"] == 0
    assert jjj["realised"] == 198.0  # still known in its own currency
    assert uuu["proceeds_base"] == round(199 * 1.35, 2)
    assert uuu["cost_base"] == round(101 * 1.35, 2)


def test_the_same_stock_in_two_accounts_is_two_rows(monkeypatch):
    fills = [
        _fill(1, "2025-02-01", "SELL", -1, 10, ibkr=5, inst="AAA", acct=1),
        _fill(2, "2025-02-01", "SELL", -1, 10, ibkr=7, inst="AAA", acct=2),
    ]
    assert len(r.by_instrument(_sales(monkeypatch, fills), date(2025, 1, 1), date(2025, 12, 31))) == 2


# ─── endpoint ────────────────────────────────────────────────────────────────
def _import_sale(db_engine, tmp_path, monkeypatch, xml):
    from tests.test_ibkr_flex_phase1 import _seed_ibkr_account

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_ibkr_account(db_engine)
    db = sessionmaker(bind=db_engine)()
    try:
        run_ibkr_flex_import_from_xml(
            db, current_user_id=1, legacy_account_id=300, xml_text=xml,
            cutover_date=date(2026, 2, 1), reference_code="REF1",
        )
    finally:
        db.close()


def test_endpoint_period_and_by_instrument(client, db_engine, tmp_path, monkeypatch):
    from tests.test_realised_pnl import _xml_with_sale

    _import_sale(db_engine, tmp_path, monkeypatch, _xml_with_sale())
    params = {"month": "2026-03", "base_currency": "USD", "period": "year", "year": 2026}
    body = client.get("/dashboard/realised-pnl", params=params).json()
    assert body["month"]["sales"] == 0  # the month part is unchanged
    assert body["period"]["key"] == "year" and body["period"]["start"] == "2026-01-01"
    assert body["period_totals"]["realised"] == 28.0
    assert body["by_instrument"][0]["symbol"] == "AAPL"
    assert body["by_instrument"][0]["sales"][0]["source"] == "ibkr"
    assert 2026 in body["years_with_sales"]
    assert body["trades_from"] is not None
    # A platform with holdings but no trades is named; IBKR (with trades) isn't.
    assert "IBKR" not in body["platforms_without_trades"]
    # Without period: the month, as before #313.
    plain = client.get("/dashboard/realised-pnl", params={"month": "2026-02", "base_currency": "USD"}).json()
    assert plain["period"]["key"] == "month" and plain["period_totals"]["realised"] == 28.0
    assert client.get("/dashboard/realised-pnl", params={"month": "2026-02", "period": "year"}).status_code == 422


def test_platforms_without_trades_lists_holdings_only_brokers(client, db_engine):
    db = sessionmaker(bind=db_engine)()
    try:
        db.execute(text(
            "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) "
            "VALUES (901, 'Holdings only', 'SHAREKHAN', 'BROKER', 'INR', 'IN', 1)"
        ))
        db.commit()
    finally:
        db.close()
    body = client.get("/dashboard/realised-pnl", params={"month": "2026-02"}).json()
    assert body["platforms_without_trades"] == ["SHAREKHAN"]


# ─── IBKR Flex back-fill ─────────────────────────────────────────────────────
def test_windows_cover_the_range_at_most_365_days_each():
    assert plan_windows(date(2025, 1, 1), date(2025, 10, 31)) == [(date(2025, 1, 1), date(2025, 10, 31))]
    two = plan_windows(date(2024, 1, 1), date(2025, 6, 30))
    assert two[0] == (date(2024, 1, 1), date(2024, 12, 30)) and two[1][0] == date(2024, 12, 31)
    assert all((b - a).days + 1 <= 365 for a, b in two)
    with pytest.raises(ValueError):
        plan_windows(date(2025, 2, 1), date(2025, 1, 1))


def test_client_sends_the_date_override_only_when_asked(monkeypatch):
    seen = []

    class FakeResponse:
        text = "<FlexStatementResponse><Status>Success</Status><ReferenceCode>R1</ReferenceCode></FlexStatementResponse>"

        def raise_for_status(self):
            return None

    class FakeHttp:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None, headers=None):
            seen.append(dict(params))
            return FakeResponse()

    import app.portfolio.ibkr_flex as flex

    monkeypatch.setattr(flex.httpx, "Client", FakeHttp)
    client = IbkrFlexClient(token="t", query_id="q")
    client.send_request()
    client.send_request(date(2025, 1, 1), date(2025, 10, 31))
    assert "fd" not in seen[0] and "td" not in seen[0]
    assert (seen[1]["fd"], seen[1]["td"]) == ("20250101", "20251031")
    with pytest.raises(ValueError):
        client.send_request(date(2025, 1, 1), None)


def test_query_id_override_replaces_the_env_query(monkeypatch):
    monkeypatch.setenv("IBKR_FLEX_TOKEN", "tok")
    monkeypatch.setenv("IBKR_FLEX_QUERY_ID", "111")
    assert IbkrFlexClient.from_env()._query_id == "111"
    assert IbkrFlexClient.from_env("222")._query_id == "222"


EARLIER_TRADE = """
            <Trade tradeDate="2025-06-10" settleDateTarget="2025-06-12" conid="265598" symbol="AAPL"
              description="APPLE INC" assetCategory="STK" listingExchange="NASDAQ" currency="USD"
              buySell="SELL" quantity="-1" tradePrice="150.00" proceeds="150.00" ibCommission="-1.00"
              fifoPnlRealized="40.00" fxRateToBase="1.35" ibExecID="E2025" />
"""


def test_backfill_dry_run_fetches_nothing_and_apply_imports_once(db_engine, tmp_path, monkeypatch):
    from tests.test_realised_pnl import _xml_with_sale

    _import_sale(db_engine, tmp_path, monkeypatch, _xml_with_sale())
    monkeypatch.setenv("IBKR_FLEX_USER_ID", "1")
    earlier_xml = _xml_with_sale().replace("</Trades>", EARLIER_TRADE + "          </Trades>")
    calls = []

    class FakeClient:
        def fetch_statement(self, **kw):
            calls.append(kw)
            return "REF-BACKFILL", earlier_xml

    db = sessionmaker(bind=db_engine)()
    try:
        dry = run_backfill(db, date(2025, 1, 1), date(2025, 10, 31), apply=False, client_factory=lambda q: FakeClient())
        assert calls == [] and dry.legacy_account_ids == [300]
        assert any("request 2025-01-01 → 2025-10-31" in line for line in summary_lines(dry, applied=False))

        done = run_backfill(
            db, date(2025, 1, 1), date(2025, 10, 31), apply=True,
            client_factory=lambda q: FakeClient(), sleep=lambda s: None,
        )
        assert calls == [{"from_date": date(2025, 1, 1), "to_date": date(2025, 10, 31)}]
        assert done.windows[0].status == "imported" and done.windows[0].trades_added == 1
        # Fetched again: deduplicated by execution id, nothing added.
        again = run_backfill(
            db, date(2025, 1, 1), date(2025, 10, 31), apply=True,
            client_factory=lambda q: FakeClient(), sleep=lambda s: None,
        )
        assert again.windows[0].trades_added == 0
        assert db.execute(text("SELECT COUNT(*) FROM portfolio_trades WHERE broker_execution_id = 'E2025'")).scalar() == 1
        assert db.execute(text("SELECT COUNT(*) FROM raw_broker_documents")).scalar() == 3  # each report kept
    finally:
        db.close()


def test_backfill_failure_is_reported_with_the_portal_hint(db_engine, tmp_path, monkeypatch):
    from tests.test_realised_pnl import _xml_with_sale

    _import_sale(db_engine, tmp_path, monkeypatch, _xml_with_sale())
    monkeypatch.setenv("IBKR_FLEX_USER_ID", "1")

    class Refusing:
        def fetch_statement(self, **kw):
            raise RuntimeError("IBKR Flex SendRequest did not return success: 1003 Statement is not available.")

    db = sessionmaker(bind=db_engine)()
    try:
        run = run_backfill(db, date(2025, 1, 1), date(2025, 10, 31), apply=True,
                           client_factory=lambda q: Refusing(), sleep=lambda s: None)
    finally:
        db.close()
    lines = summary_lines(run, applied=True)
    assert run.windows[0].status == "failed"
    assert any("FAILED" in line and "1003" in line for line in lines)
    assert any("Custom Date Range" in line for line in lines)
