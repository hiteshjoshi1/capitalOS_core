"""Indian (NSE) holdings from Sharekhan get priced (#222).

Synthetic data only: the fixture reproduces Sharekhan's real layout (company
name first, scrip code second, under a "SKScripCode | Stock Name" header) with
made-up companies and quantities.
"""
from __future__ import annotations

import os
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

import app.market_data.scheduler as market_scheduler
from app.ingestion.registry import register_signature
from app.ingestion.signature import compute_format_signature
from app.market_data import providers
from app.market_data.service import _default_yahoo_symbol, run_exchange_refresh, unpriced_held_positions
from app.market_data.symbol_override import SymbolOverrideError, set_yahoo_symbol_override
from app.portfolio.sharekhan_instrument_repair import repair_sharekhan_instruments, summary_lines
from tests.auth_helpers import signed_in_client

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sharekhan_holdings_synthetic.xls"
TICKERS = {"ACMECHEM", "ZENPAPER", "NWTRADE", "ORBITLTD"}
SNAPSHOT_DATE = "2025-06-23"


@pytest.fixture(autouse=True)
def _nse_only(monkeypatch):
    monkeypatch.setenv("STOCK_EXCHANGES", "NSE")
    monkeypatch.setattr(
        "app.market_data.providers.YFinanceProvider.fetch_dividend_yields",
        lambda self, symbols, **kwargs: {},
    )


def _session(db_engine):
    return sessionmaker(bind=db_engine, autocommit=False, autoflush=False)()


def _upload(client: TestClient, db_engine, tmp_path: Path) -> None:
    os.makedirs(os.getenv("DATA_DIR", "/tmp/capitalos_test_data"), exist_ok=True)
    with db_engine.begin() as conn:
        exists = conn.execute(text("SELECT 1 FROM accounts WHERE id = 200")).fetchone()
        if not exists:
            conn.execute(
                text(
                    "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES "
                    "(200, 'Test Sharekhan', 'SHAREKHAN', 'BROKER', 'INR', 'IN', 1)"
                )
            )
    upload = tmp_path / "sharekhan_holdings.xls"
    shutil.copyfile(FIXTURE, upload)
    sig, _ = compute_format_signature(str(upload), platform_hint="SHAREKHAN")
    db = _session(db_engine)
    try:
        register_signature(db, sig, "sharekhan_holdings_xls_v1", 1)
    finally:
        db.close()
    with open(upload, "rb") as f:
        resp = client.post(
            "/ingest/upload?account_id=200",
            files={"file": ("sharekhan_holdings.xls", f, "application/vnd.ms-excel")},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "IMPORTED"


def _make_pre_fix(db_engine) -> None:
    """The state uploads were left in before #222: ticker and name swapped, the
    synthetic id built from the name, no asset, dated in the past."""
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE broker_instruments
                SET symbol = description,
                    description = symbol,
                    broker_instrument_id = UPPER(description) || '_' || currency,
                    asset_id = NULL,
                    country = NULL
                WHERE platform_code = 'SHAREKHAN'
                """
            )
        )
        conn.execute(text("DELETE FROM assets WHERE quote_currency = 'INR'"))
        conn.execute(text("UPDATE portfolio_position_snapshots SET report_date = :d"), {"d": SNAPSHOT_DATE})
        conn.execute(text("DELETE FROM wealth_rollup_dirty"))


def _instruments(db_engine) -> list[dict]:
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id, broker_instrument_id, symbol, description, asset_id, country "
                "FROM broker_instruments WHERE platform_code = 'SHAREKHAN' ORDER BY id"
            )
        ).mappings().all()
    return [dict(r) for r in rows]


def after_name(ticker: str, rows: dict) -> str:
    return next(r["description"] for r in rows.values() if r["symbol"] == ticker)


def _repair(db_engine, *, apply: bool):
    db = _session(db_engine)
    try:
        return repair_sharekhan_instruments(db, apply=apply)
    finally:
        db.close()


def test_upload_with_fixed_parser_links_tickers(client, db_engine, tmp_path):
    _upload(client, db_engine, tmp_path)
    rows = _instruments(db_engine)
    assert {r["symbol"] for r in rows} == TICKERS
    assert {r["broker_instrument_id"] for r in rows} == {f"{t}_INR" for t in TICKERS}
    assert all(r["asset_id"] is not None for r in rows)
    with db_engine.begin() as conn:
        countries = conn.execute(
            text("SELECT DISTINCT home_country FROM assets WHERE quote_currency = 'INR'")
        ).fetchall()
    assert [c[0] for c in countries] == ["IN"]


def test_repair_dry_run_apply_and_idempotent(client, db_engine, tmp_path):
    _upload(client, db_engine, tmp_path)
    _make_pre_fix(db_engine)
    before = _instruments(db_engine)
    assert all(" " in r["symbol"] or r["symbol"] == "ORBIT" for r in before)
    with db_engine.begin() as conn:
        snapshot_count = conn.execute(text("SELECT COUNT(*) FROM portfolio_position_snapshots")).scalar()

    dry = _repair(db_engine, apply=False)
    # The upload votes "swapped", so the one-word name ("ORBIT" / "ORBITLTD") is swapped too.
    assert dry.actions()["repaired"] == 4
    assert dry.actions()["ambiguous"] == 0
    assert dry.count("swapped") == 4
    assert dry.count("id_renamed") == 4
    assert dry.count("asset_created") == 4
    assert _instruments(db_engine) == before
    with db_engine.begin() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM assets WHERE quote_currency = 'INR'")).scalar() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM wealth_rollup_dirty")).scalar() == 0
    assert any("DRY RUN" in line for line in summary_lines(dry))

    applied = _repair(db_engine, apply=True)
    assert applied.actions()["repaired"] == 4
    assert applied.dirty_from == {200: date.fromisoformat(SNAPSHOT_DATE)}
    after = {r["id"]: r for r in _instruments(db_engine)}
    assert set(after) == {r["id"] for r in before}  # row ids stay: snapshots point at them
    assert {r["symbol"] for r in after.values()} == TICKERS
    assert after_name("ORBITLTD", after) == "ORBIT"
    for r in after.values():
        assert r["broker_instrument_id"] == f"{r['symbol']}_INR"
        assert r["description"] != r["symbol"]
        assert r["asset_id"] is not None
        assert r["country"] == "IN"
    with db_engine.begin() as conn:
        assets = conn.execute(
            text("SELECT symbol, home_country, asset_class FROM assets WHERE quote_currency = 'INR'")
        ).fetchall()
        assert {a[0] for a in assets} == TICKERS
        assert {(a[1], str(a[2])) for a in assets} == {("IN", "STOCK")}
        assert conn.execute(text("SELECT COUNT(*) FROM portfolio_position_snapshots")).scalar() == snapshot_count
        dirty = conn.execute(text("SELECT user_id, from_date FROM wealth_rollup_dirty")).fetchall()
    assert [(int(d[0]), str(d[1])[:10]) for d in dirty] == [(1, SNAPSHOT_DATE)]

    again = _repair(db_engine, apply=True)
    assert again.actions()["repaired"] == 0
    assert again.actions()["unchanged"] == 4
    assert again.dirty_from == {}

    # A fresh upload with the fixed parser reuses the repaired rows.
    _upload(client, db_engine, tmp_path)
    assert {r["id"] for r in _instruments(db_engine)} == set(after)


def test_repair_keeps_old_id_when_a_fixed_upload_already_added_the_ticker(client, db_engine, tmp_path):
    _upload(client, db_engine, tmp_path)
    _make_pre_fix(db_engine)
    _upload(client, db_engine, tmp_path)  # fixed parser: new <TICKER>_INR rows and INR assets
    result = _repair(db_engine, apply=True)
    assert result.count("id_collision") == 4
    assert result.count("id_renamed") == 0
    assert result.count("asset_created") == 0
    rows = _instruments(db_engine)
    by_symbol: dict[str, set] = {}
    for r in rows:
        by_symbol.setdefault(r["symbol"], set()).add(r["asset_id"])
    for ticker in TICKERS:
        assert len(by_symbol[ticker]) == 1  # old and new row share one asset
    assert any("id collision" in line for line in summary_lines(result))


def test_nse_run_with_unlinked_holdings_is_a_warning_not_a_silent_success(client, db_engine, tmp_path, monkeypatch):
    _upload(client, db_engine, tmp_path)
    _make_pre_fix(db_engine)
    db = _session(db_engine)
    try:
        result = run_exchange_refresh(db, "NSE", full_coverage=True)
    finally:
        db.close()
    assert result["requested_symbols"] == 0
    assert result["unpriced_holdings"] == 4
    assert result["status"] == "partial"
    assert market_scheduler.exchange_run_status(result) == "no_new_data"
    with db_engine.begin() as conn:
        run = conn.execute(
            text("SELECT provider, status, requested_symbols, error_summary FROM market_data_runs WHERE exchange_code = 'NSE'")
        ).one()
    assert run[0] == "none"
    assert run[1] == "partial"
    assert run[2] == 0
    assert "4 held positions on NSE" in run[3]

    # Still counts as the window's run, so the scheduler doesn't retry it all day (#137).
    monkeypatch.setattr(market_scheduler, "SessionLocal", sessionmaker(bind=db_engine, autocommit=False, autoflush=False))
    assert market_scheduler._latest_success_for_exchanges(["NSE"]) is not None

    db = _session(db_engine)
    try:
        market_scheduler.record_exchange_runs(db, [result], trigger="manual", started_at=datetime.now(tz=timezone.utc))
    finally:
        db.close()
    hub = client.get("/dashboard/data-hub-summary").json()
    assert hub["market_data"]["unpriced"] == 4
    assert {h["reason"] for h in hub["market_data"]["unpriced_holdings"]} == {"no_asset"}
    assert {h["exchange_code"] for h in hub["market_data"]["unpriced_holdings"]} == {"NSE"}
    quotes = next(job for job in hub["job_status"] if job["job"] == "market_data")
    assert quotes["state"] == "warning"
    nse = next(scope for scope in quotes["scopes"] if scope["scope"] == "exchange:NSE")
    assert nse["last_run_status"] == "no_new_data"
    assert "can't be priced" in nse["last_error"]

    # Another user's Data Hub doesn't list them.
    other = signed_in_client(db_engine, 2)
    assert other.get("/dashboard/data-hub-summary").json()["market_data"]["unpriced"] == 0


def test_repaired_holdings_are_priced_with_override_and_the_rest_listed(client, db_engine, tmp_path, monkeypatch):
    _upload(client, db_engine, tmp_path)
    _make_pre_fix(db_engine)
    _repair(db_engine, apply=True)

    db = _session(db_engine)
    try:
        dry = set_yahoo_symbol_override(
            db, symbol="ORBITLTD", currency="INR", exchange_code="NSE", yahoo_symbol="ORBITLTD.BO", apply=False
        )
        assert dry.action == "create_map"
        assert dry.quoted_as == "ORBITLTD.BO"
        set_yahoo_symbol_override(
            db, symbol="ORBITLTD", currency="INR", exchange_code="NSE", yahoo_symbol="ORBITLTD.BO", apply=True
        )
        again = set_yahoo_symbol_override(
            db, symbol="ORBITLTD", currency="INR", exchange_code="NSE", yahoo_symbol="orbitltd.bo", apply=True
        )
        assert again.action == "unchanged"
        with pytest.raises(SymbolOverrideError):
            set_yahoo_symbol_override(db, symbol="NOPE", currency="INR", exchange_code="NSE", yahoo_symbol="X.BO", apply=True)
    finally:
        db.close()

    requested: list[str] = []

    def fake_yfinance(self, symbols, exchange_code=None, trade_date=None):
        requested.extend(symbols)
        return {
            s: providers.EodQuote(
                provider="yfinance",
                symbol=s,
                trade_date=datetime(2026, 11, 5, tzinfo=timezone.utc).date(),
                close=123.0,
                currency="INR",
            )
            for s in symbols
            if s not in ("ZENPAPER.NS", "ZENPAPER.BO")  # a ticker no provider knows, on NSE or BSE
        }

    monkeypatch.setattr("app.market_data.providers.YFinanceProvider.fetch_prices", fake_yfinance)
    monkeypatch.setattr(
        "app.market_data.providers.YahooProvider.fetch_prices",
        lambda self, symbols, exchange_code=None, trade_date=None: {},
    )
    db = _session(db_engine)
    try:
        result = run_exchange_refresh(db, "NSE", full_coverage=True)
        unpriced = unpriced_held_positions(db, user_id=1)
    finally:
        db.close()
    # ZENPAPER has no NSE quote, so its BSE ticker is tried too (#320); it has none either.
    assert sorted(requested) == ["ACMECHEM.NS", "NWTRADE.NS", "ORBITLTD.BO", "ZENPAPER.BO", "ZENPAPER.NS"]
    assert result["requested_symbols"] == 4
    assert result["upserted_rows"] == 3
    assert result["unpriced_holdings"] == 1
    assert result["status"] == "partial"
    assert market_scheduler.exchange_run_status(result) == "partial"
    assert [(u["symbol"], u["reason"], u["exchange_code"]) for u in unpriced] == [("ZENPAPER", "no_quote", "NSE")]
    with db_engine.begin() as conn:
        priced = conn.execute(
            text("SELECT a.symbol, p.currency FROM prices p JOIN assets a ON a.id = p.asset_id ORDER BY a.symbol")
        ).fetchall()
    assert [(r[0], r[1]) for r in priced] == [("ACMECHEM", "INR"), ("NWTRADE", "INR"), ("ORBITLTD", "INR")]


def test_yahoo_symbol_already_qualified_is_kept():
    assert _default_yahoo_symbol("ABC", "NSE") == "ABC.NS"
    assert _default_yahoo_symbol("ABC.NS", "NSE") == "ABC.NS"
    assert _default_yahoo_symbol("ABC.BO", "NSE") == "ABC.BO"
    assert _default_yahoo_symbol("700", "HKEX") == "0700.HK"
    assert _default_yahoo_symbol("BRK.B", "US") == "BRK-B"
    yf = providers.YFinanceProvider()
    assert yf._normalize_symbol("ABC.BO", "NSE") == "ABC.BO"
    assert yf._normalize_symbol("ABC", "NSE") == "ABC.NS"
