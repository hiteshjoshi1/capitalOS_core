"""Source authority windows (#140): one per broker account/source/scope, never
moved by an import, moved only explicitly (logged), and one reader mechanism.

Synthetic fixtures only.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.portfolio.authority import (
    AuthorityWindowError,
    ensure_window,
    get_window,
    move_window,
)
from app.portfolio.ibkr_flex import (
    is_ibkr_flex_cutover_active,
    latest_authoritative_nav_by_legacy_account,
    run_ibkr_flex_import_from_xml,
)
from app.valuation_cache import clear_shared_cache
from app.wealth_rollup_dirty import dirty_state
from tests.test_ibkr_flex_phase1 import _valid_flex_xml

ACCOUNT_ID = 1401
USER_ID = 1

_MIGRATION_PATHS = (
    Path(__file__).resolve().parents[2] / "migrations" / "075_authority_windows_one_per_scope.sql",
    Path("/app/migrations/075_authority_windows_one_per_scope.sql"),
)

# The reader predicate before #140, kept here only to prove the migration keeps
# the same rows authoritative.
_OLD_COUNTS_SQL = """
    {t}.authority_status = 'authoritative'
    OR EXISTS (
      SELECT 1 FROM portfolio_source_authority_windows aw
      WHERE aw.broker_account_id = {t}.broker_account_id
        AND aw.source_kind = 'ibkr_flex_daily' AND aw.fact_scope = 'all'
        AND aw.authority_status = 'authoritative'
        AND aw.effective_from <= {t}.report_date
        AND (aw.effective_to IS NULL OR aw.effective_to >= {t}.report_date))
"""
_FACT_TABLES = ("portfolio_position_snapshots", "portfolio_cash_balance_snapshots", "portfolio_nav_snapshots")


def migration_075_portable_statements() -> list[str]:
    for path in _MIGRATION_PATHS:
        if path.exists():
            sql = path.read_text(encoding="utf-8")
            break
    else:  # pragma: no cover - the repo always has it
        raise FileNotFoundError("migrations/075_authority_windows_one_per_scope.sql")
    body = sql.split("-- @portable-begin", 1)[1].split("-- @portable-end", 1)[0]
    body = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("--"))
    return [stmt.strip() for stmt in re.split(r";\s*\n", body) if stmt.strip()]


def run_migration_075_portable(conn) -> None:
    """Run the data part of migration 075 (the same SQL Postgres runs)."""
    for stmt in migration_075_portable_statements():
        conn.exec_driver_sql(stmt)


def _old_authoritative_ids(conn) -> dict[str, set[int]]:
    return {
        t: {int(r[0]) for r in conn.exec_driver_sql(f"SELECT id FROM {t} WHERE {_OLD_COUNTS_SQL.format(t=t)}")}
        for t in _FACT_TABLES
    }


def _status_authoritative_ids(conn) -> dict[str, set[int]]:
    return {
        t: {int(r[0]) for r in conn.exec_driver_sql(f"SELECT id FROM {t} WHERE authority_status = 'authoritative'")}
        for t in _FACT_TABLES
    }


def _covered(conn, broker_account_id: int, source_kind: str, fact_scope: str, on: str) -> bool:
    return (
        conn.exec_driver_sql(
            "SELECT 1 FROM portfolio_source_authority_windows WHERE broker_account_id = ? AND source_kind = ? "
            "AND fact_scope = ? AND authority_status = 'authoritative' AND effective_from <= ? "
            "AND (effective_to IS NULL OR effective_to >= ?)",
            (broker_account_id, source_kind, fact_scope, on, on),
        ).fetchone()
        is not None
    )


@pytest.fixture()
def pre_075_windows(db_engine):
    """Lift the one-per-scope index so a test can lay out windows the way the
    pre-#140 code left them; put it back afterwards."""
    with db_engine.begin() as conn:
        conn.exec_driver_sql("DROP INDEX IF EXISTS uq_portfolio_source_authority_windows_scope")
    yield
    with db_engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM portfolio_source_authority_windows WHERE id > 0")
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_source_authority_windows_scope "
            "ON portfolio_source_authority_windows (broker_account_id, source_kind, fact_scope)"
        )


def _seed_account(db_engine, account_id: int = ACCOUNT_ID) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country) VALUES "
                "(:id, 'Synthetic IBKR', 'IBKR', :user_id, 'BROKER', 'SGD', 'SG')"
            ),
            {"id": account_id, "user_id": USER_ID},
        )


def _flex_xml_on(day: str) -> str:
    """The phase-1 synthetic statement, moved to another date (distinct broker ids)."""
    return (
        _valid_flex_xml()
        .replace("2026-02-20", day)
        .replace("2026-02-21", day)
        .replace("2026-02-22", day)
        .replace('ibExecID="E1"', f'ibExecID="E{day}"')
        .replace('transactionID="D1"', f'transactionID="D{day}"')
    )


def _import(db: Session, xml: str, cutover: date | None = None) -> dict:
    return run_ibkr_flex_import_from_xml(
        db, current_user_id=USER_ID, legacy_account_id=ACCOUNT_ID, xml_text=xml, cutover_date=cutover
    )


def _nav_rows(db: Session, anchor: date) -> list[dict]:
    clear_shared_cache()
    return latest_authoritative_nav_by_legacy_account(db, current_user_id=USER_ID, anchor_date=anchor)


# --- Acceptance: a backfill with an earlier start doesn't change which source counts.


def test_backfill_with_an_earlier_start_does_not_move_the_window(db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_account(db_engine)
    db = Session(bind=db_engine)
    try:
        first = _import(db, _valid_flex_xml())  # statement starts 2026-02-20
        assert first["authority_window"] == {"effective_from": "2026-02-20", "effective_to": None, "created": True}
        assert not is_ibkr_flex_cutover_active(db, ACCOUNT_ID, on_date=date(2026, 1, 15))

        backfill = _import(db, _flex_xml_on("2026-01-15"))  # an older period, no explicit action
        assert backfill["authority_window"]["effective_from"] == "2026-02-20"
        assert backfill["authority_window"]["created"] is False

        windows = db.execute(text("SELECT effective_from FROM portfolio_source_authority_windows")).fetchall()
        assert [str(w[0]) for w in windows] == ["2026-02-20"]
        assert not is_ibkr_flex_cutover_active(db, ACCOUNT_ID, on_date=date(2026, 1, 15))
        statuses = {
            str(r[0]): r[1]
            for r in db.execute(text("SELECT report_date, authority_status FROM portfolio_nav_snapshots")).fetchall()
        }
        assert statuses == {"2026-01-15": "reference", "2026-02-20": "authoritative"}
        assert db.execute(
            text("SELECT DISTINCT authority_status FROM portfolio_position_snapshots WHERE report_date = '2026-01-15'")
        ).scalar() == "reference"
        # Readers don't count the backfilled period as IBKR Flex authority.
        assert _nav_rows(db, date(2026, 1, 31)) == []
        assert [str(r["report_date"]) for r in _nav_rows(db, date(2026, 2, 28))] == ["2026-02-20"]
        # The import says what it did and how to change it.
        event = db.execute(
            text(
                "SELECT severity, message FROM portfolio_data_quality_events "
                "WHERE event_code = 'authority_window_unchanged'"
            )
        ).fetchone()
        assert event is not None and event[0] == "warning"
        assert "authority-window-move" in event[1]
        # Only the creation is logged: nothing moved.
        actions = [r[0] for r in db.execute(text("SELECT action FROM portfolio_source_authority_window_changes"))]
        assert actions == ["created"]
    finally:
        db.close()


def test_an_explicit_cutover_earlier_than_the_window_does_not_move_it_either(db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_account(db_engine)
    db = Session(bind=db_engine)
    try:
        _import(db, _valid_flex_xml(), cutover=date(2026, 2, 1))
        result = _import(db, _flex_xml_on("2026-01-15"), cutover=date(2026, 1, 1))
        assert result["authority_window"]["effective_from"] == "2026-02-01"
        assert db.execute(text("SELECT COUNT(*) FROM portfolio_source_authority_windows")).scalar() == 1
        assert db.execute(
            text("SELECT authority_status FROM portfolio_nav_snapshots WHERE report_date = '2026-01-15'")
        ).scalar() == "reference"
    finally:
        db.close()


def test_daily_imports_keep_one_window_instead_of_one_per_start_date(db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_account(db_engine)
    db = Session(bind=db_engine)
    try:
        for day in ("2026-02-20", "2026-02-23", "2026-02-24"):
            _import(db, _flex_xml_on(day))
        rows = db.execute(text("SELECT effective_from, effective_to FROM portfolio_source_authority_windows")).fetchall()
        assert [(str(r[0]), r[1]) for r in rows] == [("2026-02-20", None)]
        assert {r[0] for r in db.execute(text("SELECT authority_status FROM portfolio_nav_snapshots"))} == {
            "authoritative"
        }
    finally:
        db.close()


# --- The explicit move.


def test_explicit_move_restamps_logs_and_marks_history_dirty(db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_account(db_engine)
    db = Session(bind=db_engine)
    try:
        _import(db, _valid_flex_xml())
        _import(db, _flex_xml_on("2026-01-15"))
        broker_account_id = int(db.execute(text("SELECT id FROM broker_accounts")).scalar())
        db.execute(text("UPDATE wealth_rollup_dirty SET from_date = NULL"))
        db.commit()

        dry = move_window(
            db,
            broker_account_id=broker_account_id,
            source_kind="ibkr_flex_daily",
            fact_scope="all",
            effective_from=date(2026, 1, 1),
            reason="backfill reviewed",
            actor="test",
            apply=False,
        )
        assert dry.applied is False
        assert dry.rows_promoted["portfolio_nav_snapshots"] == 1
        assert get_window(db, broker_account_id, "ibkr_flex_daily", "all").effective_from == date(2026, 2, 20)

        moved = move_window(
            db,
            broker_account_id=broker_account_id,
            source_kind="ibkr_flex_daily",
            fact_scope="all",
            effective_from=date(2026, 1, 1),
            reason="backfill reviewed",
            actor="test",
        )
        db.commit()
        assert moved.after.effective_from == date(2026, 1, 1)
        assert moved.rows_promoted == {
            "portfolio_position_snapshots": 1,
            "portfolio_cash_balance_snapshots": 2,
            "portfolio_nav_snapshots": 1,
        }
        assert is_ibkr_flex_cutover_active(db, ACCOUNT_ID, on_date=date(2026, 1, 15))
        assert [str(r["report_date"]) for r in _nav_rows(db, date(2026, 1, 31))] == ["2026-01-15"]
        assert dirty_state(db, USER_ID)[0] == date(2026, 1, 1)
        log = db.execute(
            text(
                "SELECT action, old_effective_from, new_effective_from, reason, actor "
                "FROM portfolio_source_authority_window_changes ORDER BY id"
            )
        ).fetchall()
        assert [r[0] for r in log] == ["created", "moved"]
        assert (str(log[1][1]), str(log[1][2]), log[1][3], log[1][4]) == (
            "2026-02-20",
            "2026-01-01",
            "backfill reviewed",
            "test",
        )

        # Moving it forward again demotes what falls out of it.
        back = move_window(
            db,
            broker_account_id=broker_account_id,
            source_kind="ibkr_flex_daily",
            fact_scope="all",
            effective_from=date(2026, 2, 1),
            reason="undo",
            actor="test",
        )
        db.commit()
        assert back.rows_demoted["portfolio_nav_snapshots"] == 1
        assert _nav_rows(db, date(2026, 1, 31)) == []
    finally:
        db.close()


def test_closing_a_window_needs_a_reason_and_valid_dates(db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_account(db_engine)
    db = Session(bind=db_engine)
    try:
        _import(db, _valid_flex_xml())
        broker_account_id = int(db.execute(text("SELECT id FROM broker_accounts")).scalar())
        with pytest.raises(AuthorityWindowError):
            move_window(
                db, broker_account_id=broker_account_id, source_kind="ibkr_flex_daily", fact_scope="all",
                effective_from=date(2026, 2, 20), reason=" ", actor="test",
            )
        with pytest.raises(AuthorityWindowError):
            move_window(
                db, broker_account_id=broker_account_id, source_kind="ibkr_flex_daily", fact_scope="all",
                effective_from=date(2026, 2, 20), effective_to=date(2026, 2, 1), reason="close", actor="test",
            )
        closed = move_window(
            db, broker_account_id=broker_account_id, source_kind="ibkr_flex_daily", fact_scope="all",
            effective_from=date(2026, 2, 20), effective_to=date(2026, 2, 20), reason="close", actor="test",
        )
        db.commit()
        assert closed.after.effective_to == date(2026, 2, 20)
        assert not is_ibkr_flex_cutover_active(db, ACCOUNT_ID, on_date=date(2026, 2, 21))
    finally:
        db.close()


# --- No overlaps.


def test_one_window_per_scope_is_a_unique_index(db_engine):
    with db_engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO portfolio_source_authority_windows (broker_account_id, source_kind, fact_scope, effective_from) "
            "VALUES (91, 'ibkr_flex_daily', 'all', '2026-01-01')"
        )
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            conn.exec_driver_sql(
                "INSERT INTO portfolio_source_authority_windows "
                "(broker_account_id, source_kind, fact_scope, effective_from) "
                "VALUES (91, 'ibkr_flex_daily', 'all', '2025-06-01')"
            )


def test_another_source_cannot_hold_an_overlapping_window_on_the_same_account(db_engine):
    db = Session(bind=db_engine)
    try:
        ensure_window(
            db, broker_account_id=92, source_kind="ibkr_flex_daily", fact_scope="all",
            effective_from=date(2026, 2, 1), reason="test",
        )
        with pytest.raises(AuthorityWindowError):
            ensure_window(
                db, broker_account_id=92, source_kind="ibkr_csv_upload", fact_scope="holdings",
                effective_from=date(2026, 3, 1), reason="test",
            )
        # Ending before the other starts is fine.
        move_window(
            db, broker_account_id=92, source_kind="ibkr_csv_upload", fact_scope="holdings",
            effective_from=date(2025, 1, 1), effective_to=date(2026, 1, 31), reason="history", actor="test",
        )
        with pytest.raises(AuthorityWindowError):
            move_window(
                db, broker_account_id=92, source_kind="ibkr_csv_upload", fact_scope="holdings",
                effective_from=date(2025, 1, 1), effective_to=date(2026, 2, 1), reason="overlap", actor="test",
            )
    finally:
        db.rollback()
        db.close()


def test_a_new_flex_window_closes_the_upload_window_it_supersedes(db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_account(db_engine)
    with db_engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO broker_connections (id, user_id, platform_code, connection_type, display_name, status, metadata_json) "
            "VALUES (1490, 1, 'IBKR', 'upload', 'IBKR upload', 'active', '{}')"
        )
        conn.exec_driver_sql(
            "INSERT INTO broker_accounts (id, connection_id, legacy_account_id, broker_account_id, base_currency, status, metadata_json) "
            "VALUES (1490, 1490, ?, 'upload_key', 'USD', 'active', '{}')",
            (ACCOUNT_ID,),
        )
        conn.exec_driver_sql(
            "INSERT INTO portfolio_source_authority_windows (broker_account_id, source_kind, fact_scope, effective_from) "
            "VALUES (1490, 'ibkr_csv_upload', 'holdings', '2025-10-01')"
        )
    db = Session(bind=db_engine)
    try:
        _import(db, _valid_flex_xml())
        upload = get_window(db, 1490, "ibkr_csv_upload", "holdings")
        assert upload.effective_to == date(2026, 2, 19)
        assert db.execute(
            text("SELECT COUNT(*) FROM portfolio_source_authority_window_changes WHERE action = 'closed'")
        ).scalar() == 1
    finally:
        db.close()


def test_an_older_upload_does_not_add_a_window(db_engine):
    db = Session(bind=db_engine)
    try:
        for day in (date(2026, 3, 1), date(2026, 1, 1), date(2026, 4, 1)):
            ensure_window(
                db, broker_account_id=93, source_kind="sharekhan_upload", fact_scope="holdings",
                effective_from=day, reason="upload",
            )
        rows = db.execute(
            text("SELECT effective_from FROM portfolio_source_authority_windows WHERE broker_account_id = 93")
        ).fetchall()
        assert [str(r[0]) for r in rows] == ["2026-03-01"]
    finally:
        db.rollback()
        db.close()


# --- One reader mechanism.


def test_no_reader_copies_the_window_predicate():
    """Only app/portfolio/authority.py spells out a window's date test."""
    app_dir = Path(__file__).resolve().parents[1] / "app"
    offenders = [
        str(path.relative_to(app_dir))
        for path in app_dir.rglob("*.py")
        if path.name != "authority.py" and "aw.effective_to IS NULL OR aw.effective_to" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


# --- Migration 075 on data laid out the way the old code left it.


def _seed_pre_075_layout(conn) -> None:
    """Growing and overlapping windows, rows counted only through a window, and
    rows outside every window. IDs and amounts are synthetic."""
    conn.exec_driver_sql(
        "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country) VALUES "
        "(1410, 'Synthetic IBKR', 'IBKR', 1, 'BROKER', 'USD', 'US'), "
        "(1411, 'Synthetic Sharekhan', 'SHAREKHAN', 1, 'BROKER', 'INR', 'IN')"
    )
    conn.exec_driver_sql(
        "INSERT INTO broker_connections (id, user_id, platform_code, connection_type, display_name, status, metadata_json) VALUES "
        "(1410, 1, 'IBKR', 'flex_api', 'IBKR Flex', 'active', '{}'), "
        "(1411, 1, 'SHAREKHAN', 'upload', 'Sharekhan', 'active', '{}')"
    )
    conn.exec_driver_sql(
        "INSERT INTO broker_accounts (id, connection_id, legacy_account_id, broker_account_id, base_currency, status, metadata_json) VALUES "
        "(1410, 1410, 1410, 'U_SYN', 'USD', 'active', '{}'), "
        "(1411, 1411, 1411, 'SK_SYN', 'INR', 'active', '{}')"
    )
    conn.exec_driver_sql(
        "INSERT INTO broker_import_runs (id, broker_account_id, legacy_account_id, platform_code, source_type, status, metadata_json) VALUES "
        "(1410, 1410, 1410, 'IBKR', 'ibkr_flex_daily', 'completed', '{}'), "
        "(1411, 1411, 1411, 'SHAREKHAN', 'sharekhan_upload', 'completed', '{}')"
    )
    conn.exec_driver_sql(
        "INSERT INTO broker_instruments (id, platform_code, broker_instrument_id, symbol, currency, metadata_json) VALUES "
        "(1410, 'IBKR', 'SYN1', 'SYN', 'USD', '{}'), (1411, 'SHAREKHAN', 'SYN2', 'SYNI', 'INR', '{}')"
    )
    # Flex windows: a daily start, a later daily start, then a backfill with an
    # earlier start. All open. A stale non-authoritative row too.
    conn.exec_driver_sql(
        "INSERT INTO portfolio_source_authority_windows "
        "(id, broker_account_id, source_kind, fact_scope, effective_from, effective_to, authority_status) VALUES "
        "(1, 1410, 'ibkr_flex_daily', 'all', '2026-02-01', NULL, 'authoritative'), "
        "(2, 1410, 'ibkr_flex_daily', 'all', '2026-02-02', NULL, 'authoritative'), "
        "(3, 1410, 'ibkr_flex_daily', 'all', '2026-01-10', NULL, 'authoritative'), "
        "(4, 1410, 'ibkr_flex_daily', 'all', '2025-12-01', '2025-12-31', 'reference'), "
        "(5, 1411, 'sharekhan_upload', 'holdings', '2026-03-01', NULL, 'authoritative'), "
        "(6, 1411, 'sharekhan_upload', 'holdings', '2026-01-20', NULL, 'authoritative'), "
        "(7, 1411, 'sharekhan_upload', 'holdings', '2026-02-15', NULL, 'authoritative')"
    )
    # NAV: before every window (reference, stays out), inside only the backfill
    # window (reference, counted today), and inside the first window.
    conn.exec_driver_sql(
        "INSERT INTO portfolio_nav_snapshots "
        "(id, broker_account_id, import_run_id, report_date, base_currency, total_nav_base, authority_status, metadata_json) VALUES "
        "(1, 1410, 1410, '2026-01-05', 'USD', 100, 'reference', '{}'), "
        "(2, 1410, 1410, '2026-01-12', 'USD', 110, 'reference', '{}'), "
        "(3, 1410, 1410, '2026-02-03', 'USD', 120, 'authoritative', '{}')"
    )
    conn.exec_driver_sql(
        "INSERT INTO portfolio_cash_balance_snapshots "
        "(id, broker_account_id, import_run_id, report_date, currency, cash_balance, cash_balance_base, fx_rate_to_base, authority_status, metadata_json) VALUES "
        "(1, 1410, 1410, '2026-01-05', 'USD', 1, 1, 1, 'reference', '{}'), "
        "(2, 1410, 1410, '2026-01-12', 'USD', 2, 2, 1, 'reference', '{}'), "
        "(3, 1410, 1410, '2026-02-03', 'USD', 3, 3, 1, 'authoritative', '{}')"
    )
    conn.exec_driver_sql(
        "INSERT INTO portfolio_position_snapshots "
        "(id, broker_account_id, broker_instrument_id, import_run_id, report_date, quantity, currency, "
        " market_value_local, market_value_base, fx_rate_to_base, authority_status, metadata_json) VALUES "
        "(1, 1410, 1410, 1410, '2026-01-05', 1, 'USD', 10, 10, 1, 'reference', '{}'), "
        "(2, 1410, 1410, 1410, '2026-01-12', 1, 'USD', 11, 11, 1, 'superseded', '{}'), "
        "(3, 1410, 1410, 1410, '2026-02-03', 1, 'USD', 12, 12, 1, 'authoritative', '{}'), "
        "(4, 1411, 1411, 1411, '2026-01-25', 5, 'INR', 50, 50, 1, 'authoritative', '{}'), "
        "(5, 1411, 1411, 1411, '2026-01-26', 5, 'INR', 50, 50, 1, 'reference', '{}')"
    )


_PROBE_DATES = ("2025-11-30", "2025-12-15", "2026-01-09", "2026-01-10", "2026-01-19", "2026-01-20", "2026-02-01", "2027-01-01")


def test_migration_075_collapses_windows_and_keeps_the_same_rows_authoritative(db_engine, pre_075_windows):
    with db_engine.begin() as conn:
        _seed_pre_075_layout(conn)
        before_ids = _old_authoritative_ids(conn)
        before_cover = {
            (ba, src, scope, d): _covered(conn, ba, src, scope, d)
            for ba, src, scope in ((1410, "ibkr_flex_daily", "all"), (1411, "sharekhan_upload", "holdings"))
            for d in _PROBE_DATES
        }
        conn.exec_driver_sql("DELETE FROM wealth_rollup_dirty WHERE user_id > 0")

        run_migration_075_portable(conn)

        # Same rows count, by status alone now, and by the old predicate too.
        assert _status_authoritative_ids(conn) == before_ids
        assert _old_authoritative_ids(conn) == before_ids
        assert before_ids["portfolio_nav_snapshots"] == {2, 3}
        assert before_ids["portfolio_position_snapshots"] == {2, 3, 4}
        # The window covers exactly the dates the old union did.
        after_cover = {key: _covered(conn, *key) for key in before_cover}
        assert after_cover == before_cover
        windows = conn.exec_driver_sql(
            "SELECT id, broker_account_id, source_kind, fact_scope, effective_from, effective_to, authority_status "
            "FROM portfolio_source_authority_windows ORDER BY id"
        ).fetchall()
        assert [tuple(str(v) if v is not None else None for v in w) for w in windows] == [
            ("3", "1410", "ibkr_flex_daily", "all", "2026-01-10", None, "authoritative"),
            ("6", "1411", "sharekhan_upload", "holdings", "2026-01-20", None, "authoritative"),
        ]
        log = conn.exec_driver_sql(
            "SELECT window_id, action FROM portfolio_source_authority_window_changes ORDER BY window_id"
        ).fetchall()
        assert [(int(r[0]), r[1]) for r in log] == [
            (1, "collapsed"), (2, "collapsed"), (3, "merged"), (4, "collapsed"),
            (5, "collapsed"), (6, "merged"), (7, "collapsed"),
        ]
        # History is recomputed from the earliest promoted date (D-29).
        assert str(conn.exec_driver_sql("SELECT from_date FROM wealth_rollup_dirty WHERE user_id = 1").scalar()) == "2026-01-12"

        # A second run changes nothing.
        snapshot = (
            _status_authoritative_ids(conn),
            conn.exec_driver_sql("SELECT COUNT(*) FROM portfolio_source_authority_windows").scalar(),
            conn.exec_driver_sql("SELECT COUNT(*) FROM portfolio_source_authority_window_changes").scalar(),
            conn.exec_driver_sql("SELECT generation FROM wealth_rollup_dirty WHERE user_id = 1").scalar(),
        )
        run_migration_075_portable(conn)
        assert snapshot == (
            _status_authoritative_ids(conn),
            conn.exec_driver_sql("SELECT COUNT(*) FROM portfolio_source_authority_windows").scalar(),
            conn.exec_driver_sql("SELECT COUNT(*) FROM portfolio_source_authority_window_changes").scalar(),
            conn.exec_driver_sql("SELECT generation FROM wealth_rollup_dirty WHERE user_id = 1").scalar(),
        )


def test_migration_075_keeps_a_closed_window_closed(db_engine, pre_075_windows):
    with db_engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO portfolio_source_authority_windows "
            "(id, broker_account_id, source_kind, fact_scope, effective_from, effective_to, authority_status) VALUES "
            "(11, 94, 'ibkr_flex_daily', 'all', '2026-01-01', '2026-01-31', 'authoritative'), "
            "(12, 94, 'ibkr_flex_daily', 'all', '2026-01-15', '2026-02-28', 'authoritative')"
        )
        run_migration_075_portable(conn)
        rows = conn.exec_driver_sql(
            "SELECT id, effective_from, effective_to FROM portfolio_source_authority_windows WHERE broker_account_id = 94"
        ).fetchall()
        assert [(int(r[0]), str(r[1]), str(r[2])) for r in rows] == [(11, "2026-01-01", "2026-02-28")]
