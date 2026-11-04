"""History rollups follow imports (#138): dirty marks, lazy recompute on read,
completed months only, and the scheduler hook. Synthetic fixtures only."""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.crypto.ingest import SnapshotResult, upsert_snapshot
from app.ingestion.parsers.base import ParseResult
from app.ingestion.runner import _persist_credit_card_limit_metadata
from app.portfolio.ibkr_flex import run_ibkr_flex_import_from_xml
from app.portfolio.upload_canonical import run_upload_balance_canonical_adapter
from app.valuation.history import refresh_dirty_wealth_rollups
from app.valuation_cache import write_generation
from app.wealth_rollup_dirty import (
    dirty_state,
    latest_completed_anchor_date,
    mark_rollups_dirty,
)
from tests.canonical_test_helpers import (
    seed_canonical_account_balance_for_test,
    seed_canonical_position_snapshot_for_test,
)

SGT = ZoneInfo("Asia/Singapore")
BANK = 970


@pytest.fixture(autouse=True)
def _setup(monkeypatch, db_engine):
    monkeypatch.setenv("SNAPSHOT_DAY", "1")
    monkeypatch.setattr("app.valuation.fx.get_rates", lambda *_a, **_k: {"SGD": 1.0, "USD": 1.0})
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country) VALUES "
                "(:id, 'Synthetic bank', 'TESTBANK', 1, 'BANK', 'SGD', 'SG')"
            ),
            {"id": BANK},
        )


def _freeze(monkeypatch, when: datetime) -> None:
    monkeypatch.setattr("app.valuation.clock._current_anchor_ts", lambda: when)


def _rows(db_engine, currency: str = "SGD") -> dict[str, dict]:
    with db_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT month, anchor_date, total, input_generation, computed_at FROM wealth_monthly_rollups "
                "WHERE user_id = 1 AND base_currency = :c ORDER BY month"
            ),
            {"c": currency},
        ).mappings().all()
    return {r["month"]: {**dict(r), "anchor_date": str(r["anchor_date"])[:10], "total": float(r["total"])} for r in rows}


def _dirty(db_engine) -> tuple[date | None, int]:
    db = Session(bind=db_engine)
    try:
        return dirty_state(db, 1)
    finally:
        db.close()


def _import_bank_balance(db_engine, as_of: str, amount: float) -> None:
    """A real upload write path: the bank-statement canonical balance adapter."""
    db = Session(bind=db_engine)
    try:
        run_upload_balance_canonical_adapter(
            db,
            account_id=BANK,
            import_job_id=None,
            parse_result=ParseResult(
                transactions=[],
                positions=[{"asset_class": "CASH", "currency": "SGD", "quantity": amount}],
                section_counts={},
                parser_meta={"statement_period_end": as_of},
            ),
        )
        db.commit()
    finally:
        db.close()


def _timeline(client: TestClient, months: int = 4, currency: str = "SGD") -> dict:
    resp = client.get(f"/dashboard/net-worth-timeline?months={months}&base_currency={currency}")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ─── Acceptance: a back-dated import shows up without "Generate history" ─────


def test_back_dated_import_recomputes_affected_months_on_next_read(client: TestClient, db_engine, monkeypatch):
    _freeze(monkeypatch, datetime(2026, 3, 10, 12, 0, tzinfo=SGT))
    seed_canonical_account_balance_for_test(db_engine, account_id=BANK, as_of="2025-12-15", currency="SGD", balance_base=1000)
    assert client.post("/dashboard/net-worth-timeline/backfill?months=4&base_currency=SGD").json()["months_written"] == 3

    before = _rows(db_engine)
    assert {m: r["total"] for m, r in before.items()} == {"2025-12": 1000, "2026-01": 1000, "2026-02": 1000}

    # A statement for 20 Jan arrives in March: the Feb 1 and Mar 1 anchors change.
    _import_bank_balance(db_engine, "2026-01-20", 2500)
    assert _dirty(db_engine)[0] == date(2026, 1, 20)

    data = _timeline(client)
    totals = {p["month"]: p["total"] for p in data["points"]}
    assert totals == {"2025-12": 1000, "2026-01": 2500, "2026-02": 2500}

    after = _rows(db_engine)
    # Only the affected rows were recomputed; December's anchor (Jan 1) predates the change.
    assert after["2025-12"]["computed_at"] == before["2025-12"]["computed_at"]
    assert after["2026-01"]["input_generation"] == after["2026-02"]["input_generation"] == 1
    # The dirty mark is cleared once everything it covered was recomputed.
    assert _dirty(db_engine) == (None, 1)


def test_steady_state_read_writes_nothing(client: TestClient, db_engine, monkeypatch):
    """With nothing stale the timeline is a pure read, so it never invalidates
    the cross-request valuation cache (#147)."""
    _freeze(monkeypatch, datetime(2026, 3, 10, 12, 0, tzinfo=SGT))
    seed_canonical_account_balance_for_test(db_engine, account_id=BANK, as_of="2025-12-15", currency="SGD", balance_base=1000)
    client.post("/dashboard/net-worth-timeline/backfill?months=4&base_currency=SGD")
    _timeline(client)

    generation = write_generation()
    before = _rows(db_engine)
    _timeline(client)
    assert write_generation() == generation
    assert _rows(db_engine) == before


def test_rows_outside_a_dirty_range_or_already_recomputed_are_left_alone(client: TestClient, db_engine, monkeypatch):
    """The read endpoint stays a scan for clean rows: a poisoned clean row is served as is."""
    _freeze(monkeypatch, datetime(2026, 3, 10, 12, 0, tzinfo=SGT))
    client.post("/dashboard/net-worth-timeline/backfill?months=4&base_currency=SGD")
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE wealth_monthly_rollups SET total = 999 WHERE month = '2025-12'"))
    totals = {p["month"]: p["total"] for p in _timeline(client)["points"]}
    assert totals["2025-12"] == 999


# ─── Acceptance: a finished month is recomputed at its own anchor ────────────


def test_month_rollover_recomputes_the_finished_month_at_its_own_anchor(client: TestClient, db_engine, monkeypatch):
    seed_canonical_account_balance_for_test(db_engine, account_id=BANK, as_of="2025-12-15", currency="SGD", balance_base=1000)
    _freeze(monkeypatch, datetime(2026, 2, 20, 12, 0, tzinfo=SGT))
    client.post("/dashboard/net-worth-timeline/backfill?months=3&base_currency=SGD")
    assert set(_rows(db_engine)) == {"2025-12", "2026-01"}  # February is still open: not stored

    # A provisional February row written by the old rule (at January's anchor).
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO wealth_monthly_rollups (user_id, month, anchor_date, base_currency, total, cash, "
                "stocks_funds, crypto, liabilities, source_freshness, freshness_status, computed_at) VALUES "
                "(1, '2026-02', '2026-02-01', 'SGD', 1000, 1000, 0, 0, 0, '[]', 'fresh', :now)"
            ),
            {"now": datetime(2026, 2, 20, tzinfo=timezone.utc)},
        )
    data = _timeline(client, months=3)
    assert [p["month"] for p in data["points"]] == ["2025-12", "2026-01"]
    assert "2026-02" not in _rows(db_engine)  # the provisional row is gone; "now" covers February
    assert data["now"]["total"] == 1000

    # More February data, then the clock passes the Mar 1 anchor.
    seed_canonical_account_balance_for_test(db_engine, account_id=BANK, as_of="2026-02-25", currency="SGD", balance_base=4000)
    _freeze(monkeypatch, datetime(2026, 3, 2, 9, 0, tzinfo=SGT))
    data = _timeline(client, months=4)
    feb = next(p for p in data["points"] if p["month"] == "2026-02")
    assert feb["anchor_date"] == "2026-03-01"
    assert feb["total"] == 4000
    assert [p["month"] for p in data["points"]] == ["2025-12", "2026-01", "2026-02"]


def test_row_stored_at_another_anchor_is_recomputed(client: TestClient, db_engine, monkeypatch):
    """Rows written by the old rule (a finished month stored at the month before's
    anchor) are fixed on the next read."""
    seed_canonical_account_balance_for_test(db_engine, account_id=BANK, as_of="2026-01-20", currency="SGD", balance_base=700)
    _freeze(monkeypatch, datetime(2026, 3, 10, 12, 0, tzinfo=SGT))
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO wealth_monthly_rollups (user_id, month, anchor_date, base_currency, total, cash, "
                "stocks_funds, crypto, liabilities, source_freshness, freshness_status, computed_at) VALUES "
                "(1, '2026-01', '2026-01-01', 'SGD', 0, 0, 0, 0, 0, '[]', 'missing', :now)"
            ),
            {"now": datetime(2026, 1, 15, tzinfo=timezone.utc)},
        )
    data = _timeline(client, months=3)
    jan = next(p for p in data["points"] if p["month"] == "2026-01")
    assert jan["anchor_date"] == "2026-02-01"
    assert jan["total"] == 700
    # The newest finished month is filled in too (history exists from January on).
    assert [p["month"] for p in data["points"]] == ["2026-01", "2026-02"]


def test_backfill_never_stores_the_open_month(client: TestClient, db_engine, monkeypatch):
    # Before SNAPSHOT_DAY: February's anchor (Mar 6) hasn't passed either.
    monkeypatch.setenv("SNAPSHOT_DAY", "6")
    _freeze(monkeypatch, datetime(2026, 3, 3, 12, 0, tzinfo=SGT))
    written = client.post("/dashboard/net-worth-timeline/backfill?months=4&base_currency=SGD").json()["months_written"]
    assert written == 2
    rows = _rows(db_engine)
    assert set(rows) == {"2025-12", "2026-01"}
    assert rows["2026-01"]["anchor_date"] == "2026-02-06"


def test_current_month_uploads_go_on_the_now_point(client: TestClient, db_engine, monkeypatch):
    _freeze(monkeypatch, datetime(2026, 3, 10, 12, 0, tzinfo=SGT))
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO import_jobs (account_id, platform, original_filename, stored_path, file_sha256, status, created_at, updated_at) "
                "VALUES (:a, 'TESTBANK', 'stmt.csv', '/tmp/x', 'sha', 'IMPORTED', :t, :t)"
            ),
            {"a": BANK, "t": datetime(2026, 3, 5, tzinfo=timezone.utc)},
        )
    data = _timeline(client, months=3)
    assert data["now"]["uploads"] == ["TESTBANK"]


# ─── Dirty marks ─────────────────────────────────────────────────────────────


def test_mark_keeps_the_earliest_date_and_bumps_the_generation(db_engine):
    db = Session(bind=db_engine)
    try:
        assert mark_rollups_dirty(db, date(2026, 2, 10), user_ids=[1])
        assert mark_rollups_dirty(db, date(2026, 1, 5), user_ids=[1])
        assert mark_rollups_dirty(db, datetime(2026, 2, 1, 3, 0, tzinfo=timezone.utc), user_ids=[1])
        db.commit()
        assert dirty_state(db, 1) == (date(2026, 1, 5), 3)
    finally:
        db.close()


def test_change_after_the_latest_completed_anchor_marks_nothing(db_engine, monkeypatch):
    """A change dated after every completed anchor (a price or snapshot for
    today, any day but the snapshot day) can't affect a stored row."""
    monkeypatch.setattr("app.wealth_rollup_dirty._utc_now", lambda: datetime(2026, 3, 10, tzinfo=timezone.utc))
    assert latest_completed_anchor_date() == date(2026, 3, 1)
    db = Session(bind=db_engine)
    try:
        assert not mark_rollups_dirty(db, date(2026, 3, 10), user_ids=[1])
        assert mark_rollups_dirty(db, date(2026, 3, 1), user_ids=[1])  # the anchor day itself counts
        db.commit()
        assert dirty_state(db, 1) == (date(2026, 3, 1), 1)
    finally:
        db.close()


def test_mark_settles_per_currency(client: TestClient, db_engine, monkeypatch):
    """Reading one currency recomputes only its rows; the mark stays at the
    other currency's earliest stale row until that one is read too."""
    _freeze(monkeypatch, datetime(2026, 3, 10, 12, 0, tzinfo=SGT))
    seed_canonical_account_balance_for_test(db_engine, account_id=BANK, as_of="2025-12-15", currency="SGD", balance_base=1000)
    client.post("/dashboard/net-worth-timeline/backfill?months=4&base_currency=SGD")
    client.post("/dashboard/net-worth-timeline/backfill?months=4&base_currency=USD")

    _import_bank_balance(db_engine, "2026-01-20", 2500)
    _timeline(client, currency="SGD")
    assert _dirty(db_engine)[0] == date(2026, 2, 1)  # USD's January row (anchor Feb 1) is still stale

    usd = {p["month"]: p["total"] for p in _timeline(client, currency="USD")["points"]}
    assert usd["2026-01"] == 2500
    assert _dirty(db_engine)[0] is None


def test_scheduler_hook_recomputes_and_clears(db_engine, client: TestClient, monkeypatch):
    _freeze(monkeypatch, datetime(2026, 3, 10, 12, 0, tzinfo=SGT))
    seed_canonical_account_balance_for_test(db_engine, account_id=BANK, as_of="2025-12-15", currency="SGD", balance_base=1000)
    client.post("/dashboard/net-worth-timeline/backfill?months=4&base_currency=SGD")
    _import_bank_balance(db_engine, "2026-02-03", 3000)

    db = Session(bind=db_engine)
    try:
        assert refresh_dirty_wealth_rollups(db) == 1  # only February (anchor Mar 1)
    finally:
        db.close()
    assert _rows(db_engine)["2026-02"]["total"] == 3000
    assert _dirty(db_engine)[0] is None


def test_cached_valuation_is_not_served_after_a_back_dated_import(client: TestClient, db_engine, monkeypatch):
    """#165's shared cache must not hand the recompute a pre-import value."""
    _freeze(monkeypatch, datetime(2026, 3, 10, 12, 0, tzinfo=SGT))
    seed_canonical_account_balance_for_test(db_engine, account_id=BANK, as_of="2025-12-15", currency="SGD", balance_base=1000)
    client.post("/dashboard/net-worth-timeline/backfill?months=4&base_currency=SGD")
    # Warm the shared cache for January's anchor (Feb 1) through another GET.
    summary = client.get("/dashboard/summary?month=2026-01&base_currency=SGD")
    assert summary.status_code == 200
    assert summary.json()["net_worth"]["total"] == 1000

    _import_bank_balance(db_engine, "2026-01-20", 2500)
    totals = {p["month"]: p["total"] for p in _timeline(client)["points"]}
    assert totals["2026-01"] == 2500
    assert client.get("/dashboard/summary?month=2026-01&base_currency=SGD").json()["net_worth"]["total"] == 2500


# ─── Write paths record marks ────────────────────────────────────────────────


def test_price_rows_do_not_change_past_months(client: TestClient, db_engine, monkeypatch):
    """Past rollups are snapshot values (price_overlay=False): a daily quote,
    even one dated in the past, never changes them, so the quote job marks nothing."""
    _freeze(monkeypatch, datetime(2026, 3, 10, 12, 0, tzinfo=SGT))
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country) VALUES "
                "(971, 'Synthetic broker', 'TESTBROKER', 1, 'BROKER', 'SGD', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(971, 'SYNTH', 'SYNTH', 'STOCK', 'SGD', 'SG')"
            )
        )
    seed_canonical_position_snapshot_for_test(
        db_engine, account_id=971, asset_id=971, as_of=date(2026, 1, 20),
        quantity=10, market_value_base=500.0, market_price=50.0, platform_code="TESTBROKER",
    )
    client.post("/dashboard/net-worth-timeline/backfill?months=4&base_currency=SGD")
    before = {m: r["total"] for m, r in _rows(db_engine).items()}
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO prices (asset_id, ts, trade_date, price, currency, source) "
                "VALUES (971, '2026-01-30 08:00:00', '2026-01-30', 90, 'SGD', 'test')"
            )
        )
    client.post("/dashboard/net-worth-timeline/backfill?months=4&base_currency=SGD")
    assert {m: r["total"] for m, r in _rows(db_engine).items()} == before


def test_crypto_snapshot_marks_from_its_date(db_engine, monkeypatch):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO crypto_wallets (id, user_id, chain_type, chain, address, status, created_at) VALUES "
                "('wallet-syn', 1, 'evm', 'ethereum', '0xsyn', 'active', :t)"
            ),
            {"t": datetime(2026, 1, 1, tzinfo=timezone.utc)},
        )
    monkeypatch.setattr("app.crypto.ingest._as_of_date", lambda: date(2026, 2, 1))
    db = Session(bind=db_engine)
    try:
        upsert_snapshot(db, "wallet-syn", SnapshotResult(total_usd=10.0, items=[], source_versions={}))
        db.commit()
        assert dirty_state(db, 1)[0] == date(2026, 2, 1)
    finally:
        db.close()


def test_card_limit_update_marks_from_the_earlier_limit_date(db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country) VALUES "
                "(972, 'Synthetic card', 'DBS', 1, 'CREDIT_CARD', 'SGD', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO credit_card_accounts (account_id, card_name, issuer, credit_limit, available_limit, "
                "available_limit_as_of, statement_day, due_day) VALUES (972, 'Synthetic', 'DBS', 1000, 900, :t, 1, 20)"
            ),
            {"t": datetime(2026, 1, 10, tzinfo=timezone.utc)},
        )
    db = Session(bind=db_engine)
    try:
        _persist_credit_card_limit_metadata(
            db,
            account_id=972,
            parser_key="dbs_credit_card_csv_v1",
            parser_meta={"credit_limit": 1000, "available_limit": 600, "transactions_as_at": "2026-02-15T00:00:00+00:00"},
        )
        db.commit()
        assert dirty_state(db, 1)[0] == date(2026, 1, 10)
    finally:
        db.close()


def test_ibkr_flex_import_marks_from_the_new_authority_window(db_engine, tmp_path, monkeypatch):
    from tests.test_ibkr_flex_phase1 import _valid_flex_xml

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country) VALUES "
                "(973, 'Synthetic IBKR', 'IBKR', 1, 'BROKER', 'SGD', 'SG')"
            )
        )
    db = Session(bind=db_engine)
    try:
        run_ibkr_flex_import_from_xml(
            db, current_user_id=1, legacy_account_id=973, xml_text=_valid_flex_xml(), cutover_date=date(2026, 2, 1),
        )
        assert dirty_state(db, 1)[0] == date(2026, 2, 1)
        # A re-import of the same statement (window exists) marks from its report date.
        db.execute(text("UPDATE wealth_rollup_dirty SET from_date = NULL"))
        db.commit()
        run_ibkr_flex_import_from_xml(
            db, current_user_id=1, legacy_account_id=973, xml_text=_valid_flex_xml(), cutover_date=date(2026, 2, 1),
        )
        assert dirty_state(db, 1)[0] == date(2026, 2, 20)
    finally:
        db.close()


def test_new_or_corrected_past_fx_rate_marks_history_dirty_and_unchanged_rate_does_not(db_engine, monkeypatch):
    """Batch integration of #138 and #139: storing a rate for a past date changes
    History from that date on; re-storing the same rate (or today's) marks nothing."""
    from app import fx

    monkeypatch.setattr("app.wealth_rollup_dirty._utc_now", lambda: datetime(2026, 3, 10, tzinfo=timezone.utc))
    row = {"rate_date": date(2026, 2, 1), "base": "EUR", "quote": "SGD", "rate": 1.45, "source": "frankfurter",
           "fetched_at": datetime(2026, 3, 10, tzinfo=timezone.utc)}
    with db_engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, username, display_name, is_active) VALUES (1, 'fx-user', 'FX', 1)"))
    assert _dirty(db_engine) == (None, 0)

    fx._store_rows([row])
    assert _dirty(db_engine) == (date(2026, 2, 1), 1)

    fx._store_rows([row])  # same rate again: nothing changed
    assert _dirty(db_engine) == (date(2026, 2, 1), 1)

    fx._store_rows([{**row, "rate": 1.46}])  # corrected rate
    assert _dirty(db_engine) == (date(2026, 2, 1), 2)

    fx._store_rows([{**row, "rate_date": date(2026, 3, 10)}])  # today: no stored month affected
    assert _dirty(db_engine) == (date(2026, 2, 1), 2)
