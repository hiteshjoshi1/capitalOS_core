"""Dividend calendar (#417, U17, D-117): projection, the provider fetch (mocked), the refresh and
GET /dividends/calendar. Synthetic data only."""
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
from sqlalchemy import text

from app.market_data import providers
from app.market_data.dividend_events import refresh_dividend_events_for_exchange
from app.portfolio.dividend_calendar import PastDividend, typical_gap_days, upcoming_dividends
from tests.test_dividends import _seed_dividend_data

# The real method: conftest's autouse fixture replaces it on the class during each test.
_REAL_FETCH_EVENTS = providers.YFinanceProvider.fetch_dividend_events


def _past(*items):
    return [PastDividend(date.fromisoformat(d), Decimal(str(a))) for d, a in items]


# ---- projection ----

def test_quarterly_rhythm_projects_the_next_dates_and_amounts():
    history = _past(("2026-02-09", 0.25), ("2026-05-11", 0.26), ("2026-08-10", 0.26), ("2026-11-09", 0.27))
    assert typical_gap_days(history) == 91
    out = upcoming_dividends(history, None, start=date(2026, 11, 12), end=date(2027, 2, 11))
    assert [(u.ex_date.isoformat(), u.basis) for u in out] == [("2027-02-08", "projected")]
    # The same dividend a year earlier (Feb 2026) gives the amount.
    assert out[0].amount_per_share == Decimal("0.25")


def test_interim_and_final_keep_their_own_amounts():
    # A Singapore bank: a small interim (Aug) and a larger final (Apr/May).
    history = _past(("2025-05-02", 0.80), ("2025-08-15", 0.60), ("2026-05-04", 0.84), ("2026-08-14", 0.62))
    out = upcoming_dividends(history, None, start=date(2027, 4, 1), end=date(2027, 6, 30))
    assert len(out) == 1
    assert out[0].amount_per_share == Decimal("0.84")


def test_a_listed_date_replaces_the_projection_near_it():
    history = _past(("2026-02-09", 0.25), ("2026-05-11", 0.26), ("2026-08-10", 0.26))
    out = upcoming_dividends(
        history, (date(2026, 11, 14), date(2026, 11, 28)), start=date(2026, 11, 1), end=date(2027, 1, 31)
    )
    assert [(u.ex_date.isoformat(), u.basis) for u in out] == [("2026-11-14", "announced")]
    assert out[0].pay_date == date(2026, 11, 28)
    assert out[0].amount_per_share == Decimal("0.26")


def test_one_off_or_irregular_dividends_project_nothing():
    assert upcoming_dividends(_past(("2026-06-01", 1.0)), None, start=date(2026, 11, 1), end=date(2027, 1, 31)) == []
    assert typical_gap_days(_past(("2024-01-01", 1.0), ("2026-01-01", 1.0))) is None  # 731 days: no rhythm


def test_a_missed_refresh_still_lands_in_the_window():
    history = _past(("2025-07-10", 0.5), ("2025-10-10", 0.5), ("2026-01-10", 0.5))
    out = upcoming_dividends(history, None, start=date(2026, 11, 1), end=date(2027, 1, 31))
    assert len(out) == 1 and out[0].basis == "projected"


def test_a_holding_that_stopped_paying_is_not_projected():
    history = _past(("2025-01-10", 0.5), ("2025-04-10", 0.5), ("2025-07-10", 0.5))
    assert upcoming_dividends(history, None, start=date(2026, 11, 1), end=date(2027, 1, 31)) == []


def test_a_year_of_history_repeats_each_dividend_a_year_on():
    history = _past(("2025-08-20", 0.10), ("2025-11-20", 0.10), ("2026-02-20", 0.10), ("2026-05-20", 0.30), ("2026-08-20", 0.10))
    out = upcoming_dividends(history, None, start=date(2026, 11, 12), end=date(2027, 6, 1))
    assert [(u.ex_date.isoformat(), str(u.amount_per_share)) for u in out] == [
        ("2026-11-20", "0.1"),
        ("2027-02-20", "0.1"),
        ("2027-05-20", "0.3"),
    ]


# ---- provider fetch (mocked yfinance) ----

class _FakeTicker:
    def __init__(self, symbol):
        self.symbol = symbol
        idx = pd.to_datetime(["2025-02-10", "2026-02-09", "2026-05-11"]).tz_localize("America/New_York")
        self.dividends = pd.Series([0.24, 0.25, 0.26], index=idx)
        self.calendar = {"Ex-Dividend Date": date(2026, 11, 14), "Dividend Date": date(2026, 11, 28)}


def test_provider_returns_history_and_the_listed_date(monkeypatch):
    provider = providers.YFinanceProvider()
    monkeypatch.setattr(provider, "_load_yfinance", lambda: SimpleNamespace(Ticker=_FakeTicker))
    monkeypatch.setenv("YFINANCE_SLEEP_MS", "0")
    out = _REAL_FETCH_EVENTS(provider, ["AAPL"], exchange_code="US", history_days=5000)
    assert out["AAPL"]["announced"] == {"ex_date": date(2026, 11, 14), "pay_date": date(2026, 11, 28)}
    assert [d.isoformat() for d, _a in out["AAPL"]["history"]] == ["2025-02-10", "2026-02-09", "2026-05-11"]


# ---- refresh ----

class _FakeYF:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def fetch_dividend_events(self, symbols, **kwargs):
        self.calls.append(list(symbols))
        return {s: self.payload[s] for s in symbols if s in self.payload}


def _row(asset_id, symbol, ccy="USD"):
    return SimpleNamespace(asset_id=asset_id, yahoo_symbol=symbol, quote_currency=ccy)


def _events(db_engine, asset_id):
    with db_engine.begin() as conn:
        return conn.execute(
            text("SELECT kind, ex_date, pay_date, amount_per_share FROM market_dividend_events WHERE asset_id = :a ORDER BY kind, ex_date"),
            {"a": asset_id},
        ).fetchall()


def test_refresh_stores_events_skips_fresh_ones_and_moves_a_listed_date(db_engine):
    from sqlalchemy.orm import Session

    with db_engine.begin() as conn:
        conn.execute(text("INSERT INTO assets (id, symbol, name, asset_class, quote_currency) VALUES (901, 'AAPL', 'Apple', 'STOCK', 'USD')"))
    now = datetime(2026, 11, 12, 6, 0, tzinfo=timezone.utc)
    yf = _FakeYF({"AAPL": {"history": [(date(2026, 8, 11), 0.26)], "announced": {"ex_date": date(2026, 11, 14), "pay_date": None}}})
    with Session(db_engine) as db:
        assert refresh_dividend_events_for_exchange(db, exchange_code="US", symbols=[_row(901, "AAPL")], yfinance=yf, now=now) == 2
        db.commit()
        # Fetched 2 hours ago: skipped.
        assert refresh_dividend_events_for_exchange(
            db, exchange_code="US", symbols=[_row(901, "AAPL")], yfinance=yf, now=now.replace(hour=8)
        ) == 0
        # A day later the listing moved to 17 Nov: the old ahead-listing goes.
        yf.payload["AAPL"]["announced"] = {"ex_date": date(2026, 11, 17), "pay_date": date(2026, 12, 1)}
        refresh_dividend_events_for_exchange(db, exchange_code="US", symbols=[_row(901, "AAPL")], yfinance=yf, now=now.replace(day=13))
        db.commit()
    rows = _events(db_engine, 901)
    announced = [r for r in rows if r[0] == "announced"]
    assert len(announced) == 1 and str(announced[0][1]) == "2026-11-17"
    assert len(yf.calls) == 2


def test_refresh_caps_the_symbols_per_run(db_engine, monkeypatch):
    from sqlalchemy.orm import Session

    monkeypatch.setenv("DIVIDEND_EVENTS_MAX_SYMBOLS", "2")
    rows = [_row(900 + i, f"S{i}") for i in range(5)]
    yf = _FakeYF({})
    with Session(db_engine) as db:
        refresh_dividend_events_for_exchange(db, exchange_code="US", symbols=rows, yfinance=yf)
    assert yf.calls == [["S0", "S1"]]


# ---- GET /dividends/calendar ----

def _add_events(db_engine, asset_id, rows):
    with db_engine.begin() as conn:
        for kind, ex_date, pay_date, amount in rows:
            conn.execute(
                text(
                    "INSERT INTO market_dividend_events (asset_id, kind, ex_date, pay_date, amount_per_share, currency, fetched_at) "
                    "VALUES (:a, :k, :e, :p, :m, 'USD', '2026-03-01T00:00:00+00:00')"
                ),
                {"a": asset_id, "k": kind, "e": ex_date, "p": pay_date, "m": amount},
            )


def test_calendar_lists_projected_and_announced_dividends(client, db_engine):
    _seed_dividend_data(db_engine)  # AAPL, 100 shares
    _add_events(
        db_engine,
        901,
        [
            ("history", "2025-05-12", None, 0.25),
            ("history", "2025-08-11", None, 0.26),
            ("history", "2025-11-10", None, 0.26),
            ("history", "2026-02-09", None, 0.26),
            ("announced", "2026-05-11", "2026-05-14", None),
        ],
    )
    resp = client.get("/dividends/calendar?base_currency=USD&months=3&as_of=2026-03-01")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["from_date"] == "2026-03-01" and data["to_date"] == "2026-05-31"
    events = data["events"]
    assert [(e["basis"], e["ex_date"], e["date"]) for e in events] == [("announced", "2026-05-11", "2026-05-14")]
    event = events[0]
    assert event["shares"] == 100
    assert event["amount_per_share"] == 0.25  # May a year earlier
    assert event["amount"] == 25.0 and event["amount_base"] == 25.0
    assert [m["month"] for m in data["months"]] == ["2026-03", "2026-04", "2026-05"]
    assert data["months"][2]["amount_base"] == 25.0
    assert data["total_base"] == 25.0
    assert data["holdings_considered"] == 1 and data["holdings_with_events"] == 1
    assert data["data_as_of"]


def test_calendar_falls_back_to_your_payments_a_year_back(client, db_engine):
    _seed_dividend_data(db_engine)  # AAPL paid you 100 (15 Jan 2026) and 80 (15 Feb 2026); no events
    data = client.get("/dividends/calendar?base_currency=USD&months=3&as_of=2027-01-01").json()
    assert [(e["basis"], e["date"], e["amount"]) for e in data["events"]] == [
        ("your_payments", "2027-01-15", 100.0),
        ("your_payments", "2027-02-15", 80.0),
    ]
    assert data["total_base"] == 180.0
    assert data["holdings_without_data"] == 0


def test_calendar_with_nothing_to_go_on(client, db_engine):
    _seed_dividend_data(db_engine)
    data = client.get("/dividends/calendar?base_currency=USD&months=3&as_of=2026-06-01").json()
    assert data["events"] == []
    assert data["holdings_without_data"] == 1
    assert data["holdings_no_dividend_history"] == 1
    assert data["total_base"] == 0


def test_calendar_rejects_a_bad_date(client):
    assert client.get("/dividends/calendar?as_of=nope").status_code == 422
