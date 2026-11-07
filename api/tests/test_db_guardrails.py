"""DB guardrails (#158; #130 findings 1.8 and 1.11): migration 079's ON DELETE RESTRICT and
CHECK constraints, the read-only constraint precheck, and the delete paths that must keep
working under RESTRICT.

The tests without a marker run on the default SQLite suite: they tie 079's allowed values to
the code's constants (a new adapter's source kind fails here first) and check the precheck
generator. The `postgres`-marked ones run on a migrated Postgres 16 (`make db-schema-check`),
since SQLite enforces neither the foreign keys nor these CHECKs. Synthetic rows only.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ingestion.registry import register_signature
from app.ingestion.signature import compute_format_signature
from app.portfolio import authority
from app.portfolio.ibkr_flex import HOLDINGS_FACT_SCOPE, NAV_ONLY_STATUS, run_ibkr_flex_import_from_xml
from app.portfolio.ibkr_flex import SOURCE_TYPE as FLEX_SOURCE_TYPE
from app.portfolio.legacy_backfill import BACKFILL_SOURCE_KIND, BACKFILL_SOURCE_TYPE
from app.portfolio.upload_canonical import _BALANCE_SOURCE_KIND, _INCOMPLETE_SCOPES, _PLATFORM_SOURCE_KIND
from app.routers.health import _migrations_dir
from app.scripts.constraint_precheck import Drop, parse_checks, parse_drops, precheck_sql
from app.valuation.history import _FRESHNESS_STATUS_RANK
from app.valuation.state import CASH_BALANCE_TYPES
from tests.auth_helpers import signed_in_client
from tests.postgres_support import pg_engine  # noqa: F401  (fixture)
from tests.valuation_household import FLEX_REPORTS, flex_xml

MIGRATION = "079_db_guardrails.sql"


def _migrations() -> Path:
    for candidate in (Path(_migrations_dir()), Path(__file__).resolve().parents[2] / "migrations"):
        if (candidate / MIGRATION).is_file():
            return candidate
    raise AssertionError(f"{MIGRATION} not found")


def _sql() -> str:
    return (_migrations() / MIGRATION).read_text(encoding="utf-8")


def _allowed() -> dict[tuple[str, str], set[str]]:
    """(table, column) -> the values 079's CHECK allows."""
    return {(c.table, c.column): set(re.findall(r"'([^']*)'", c.expr)) for c in parse_checks(_sql()) if " IN (" in c.expr}


# ─── 079 against the code (SQLite suite) ──────────────────────────────────────


def test_authority_statuses_match_the_code():
    statuses = {authority.AUTHORITATIVE, authority.REFERENCE, authority.SUPERSEDED}
    allowed = _allowed()
    for table in (
        "portfolio_position_snapshots",
        "portfolio_cash_balance_snapshots",
        "portfolio_nav_snapshots",
        "account_balance_snapshots",
        "portfolio_source_authority_windows",
    ):
        assert allowed[(table, "authority_status")] == statuses, table
    for column in ("old_authority_status", "new_authority_status"):
        assert allowed[("portfolio_source_authority_window_changes", column)] == statuses


def test_every_source_kind_the_code_writes_is_allowed():
    """A new upload adapter (``_PLATFORM_SOURCE_KIND``) needs a migration widening 079 first."""
    sources = set(_PLATFORM_SOURCE_KIND.values()) | {FLEX_SOURCE_TYPE, authority.FLEX_SOURCE_KIND}
    allowed = _allowed()
    assert sources <= allowed[("portfolio_source_authority_windows", "source_kind")]
    assert sources <= allowed[("portfolio_source_authority_window_changes", "source_kind")]
    for table in ("broker_import_runs", "raw_broker_documents"):
        assert sources | {BACKFILL_SOURCE_TYPE, "DUMMY"} <= allowed[(table, "source_type")], table
    assert {_BALANCE_SOURCE_KIND, BACKFILL_SOURCE_KIND, "DUMMY"} <= allowed[("account_balance_snapshots", "source_kind")]


def test_every_scope_and_status_the_code_writes_is_allowed():
    allowed = _allowed()
    assert {authority.FLEX_FACT_SCOPE, authority.ALL_SCOPES, "holdings"} <= allowed[
        ("portfolio_source_authority_windows", "fact_scope")
    ]
    completeness_scopes = {"holdings", HOLDINGS_FACT_SCOPE} | {scope for scope, _reason in _INCOMPLETE_SCOPES}
    assert completeness_scopes <= allowed[("portfolio_data_completeness", "fact_scope")]
    assert {"complete", "incomplete", "failed", NAV_ONLY_STATUS} <= allowed[
        ("portfolio_data_completeness", "completeness_status")
    ]
    assert set(CASH_BALANCE_TYPES) <= allowed[("account_balance_snapshots", "balance_type")]
    assert set(_FRESHNESS_STATUS_RANK) <= allowed[("wealth_monthly_rollups", "freshness_status")]
    assert {"started", "completed", "failed", "removed"} <= allowed[("broker_import_runs", "status")]
    assert {"daily", "upload", "backfill"} <= allowed[("broker_import_runs", "import_scope")]


def test_079_adds_restrict_keys_and_validates_every_constraint_it_adds():
    sql = _sql()
    added = re.findall(r"ADD CONSTRAINT (\w+)\s+(?:FOREIGN KEY|CHECK)", sql)
    validated = set(re.findall(r"VALIDATE CONSTRAINT (\w+);", sql))
    assert added and set(added) == validated
    assert len(added) == len(set(added))
    for fk in re.findall(r"FOREIGN KEY \([^)]*\) REFERENCES [^;]*;", sql):
        assert "ON DELETE RESTRICT NOT VALID" in fk, fk
    assert not re.search(r"^\s*(BEGIN|COMMIT)\s*;", sql, re.MULTILINE | re.IGNORECASE)


def test_precheck_reads_every_check_and_only_reads():
    checks = parse_checks(_sql())
    assert len(checks) == len(re.findall(r"CHECK \(", _sql()))
    assert {c.column for c in checks if c.table == "wealth_monthly_rollups"} == {"freshness_status", "month"}
    assert next(c for c in checks if c.name.endswith("old_authority_status_check")).column == "old_authority_status"
    drops = parse_drops(_sql())
    assert len(drops) == len(re.findall(r"FOREIGN KEY", _sql())) and all(d.name.endswith("_fkey") for d in drops)
    sql = precheck_sql(checks, drops)
    assert sql.startswith("-- Generated") and "BEGIN TRANSACTION READ ONLY;" in sql
    assert sql.rstrip().endswith("ROLLBACK;")
    statements = re.findall(r"^\s*([A-Z]+)\b", sql, re.MULTILINE)
    assert not {"INSERT", "UPDATE", "DELETE", "ALTER", "DROP", "CREATE", "TRUNCATE"} & set(statements)


def test_precheck_with_nothing_pending_says_so():
    assert "No pending" in precheck_sql([], [])


# ─── On Postgres ──────────────────────────────────────────────────────────────

OWNER = 15801
BROKER = 15811
BROKER_FLEX = 15812


def _fk_delete_rules(engine, referenced: str) -> dict[str, str]:
    """'table.column' -> ON DELETE rule ('r' restrict, 'c' cascade, 'n' set null, 'a' no action)."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT c.conrelid::regclass::text || '.' || a.attname, c.confdeltype
                FROM pg_constraint c
                JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
                WHERE c.contype = 'f' AND c.confrelid = CAST(:ref AS regclass)
                """
            ),
            {"ref": referenced},
        ).fetchall()
    return {name: str(rule) for name, rule in rows}


@pytest.mark.postgres
def test_nothing_cascades_or_unlinks_from_runs_raw_documents_or_legacy_accounts(pg_engine):  # noqa: F811
    runs = _fk_delete_rules(pg_engine, "broker_import_runs")
    raw = _fk_delete_rules(pg_engine, "raw_broker_documents")
    accounts = {k: v for k, v in _fk_delete_rules(pg_engine, "accounts").items() if k.endswith(".legacy_account_id")}
    assert len(runs) == 14 and len(raw) == 13 and len(accounts) == 5
    assert {k: v for k, v in {**runs, **raw, **accounts}.items() if v != "r"} == {}


@pytest.mark.postgres
def test_every_079_constraint_exists_and_is_validated(pg_engine):  # noqa: F811
    names = re.findall(r"ADD CONSTRAINT (\w+)", _sql())
    with pg_engine.connect() as conn:
        rows = dict(
            conn.execute(
                text("SELECT conname, convalidated FROM pg_constraint WHERE conname = ANY(:names)"), {"names": names}
            ).fetchall()
        )
    assert set(rows) == set(names)
    assert all(rows.values())


def _seed_run(engine) -> dict[str, int]:
    """A broker account with one run, its raw document and a position fact on it."""
    signed_in_client(engine, OWNER)  # the user row
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country) "
                "VALUES (:id, 'Test Broker 158', 'IBKR', :u, 'BROKER', 'USD', 'US')"
            ),
            {"id": BROKER, "u": OWNER},
        )
        connection_id = conn.execute(
            text(
                "INSERT INTO broker_connections (user_id, platform_code, connection_type, display_name, status) "
                "VALUES (:u, 'IBKR', 'manual_upload', 'Test', 'active') RETURNING id"
            ),
            {"u": OWNER},
        ).scalar_one()
        broker_account_id = conn.execute(
            text(
                "INSERT INTO broker_accounts (connection_id, legacy_account_id, broker_account_id, base_currency, status) "
                "VALUES (:c, :a, 'SYNTH-158', 'USD', 'active') RETURNING id"
            ),
            {"c": connection_id, "a": BROKER},
        ).scalar_one()
        run_id = conn.execute(
            text(
                "INSERT INTO broker_import_runs (broker_account_id, legacy_account_id, platform_code, source_type, "
                "import_scope, status) VALUES (:b, :a, 'IBKR', 'ibkr_csv_upload', 'upload', 'completed') RETURNING id"
            ),
            {"b": broker_account_id, "a": BROKER},
        ).scalar_one()
        raw_id = conn.execute(
            text(
                "INSERT INTO raw_broker_documents (import_run_id, broker_account_id, source_type, content_hash, "
                "storage_path, parser_version) VALUES (:r, :b, 'ibkr_csv_upload', 'synthetic-hash', "
                "'/synthetic/path.csv', 'test') RETURNING id"
            ),
            {"r": run_id, "b": broker_account_id},
        ).scalar_one()
        instrument_id = conn.execute(
            text(
                "INSERT INTO broker_instruments (platform_code, broker_instrument_id, symbol, currency) "
                "VALUES ('IBKR', 'SYNTH158', 'SYNTH158', 'USD') RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO portfolio_position_snapshots (broker_account_id, legacy_account_id, broker_instrument_id, "
                "import_run_id, raw_document_id, report_date, quantity, currency, market_value_local, "
                "market_value_base, fx_rate_to_base, authority_status) VALUES (:b, :a, :i, :r, :d, '2026-03-16', "
                "10, 'USD', 1000, 1000, 1, 'authoritative')"
            ),
            {"b": broker_account_id, "a": BROKER, "i": instrument_id, "r": run_id, "d": raw_id},
        )
    return {"run": run_id, "raw": raw_id, "broker_account": broker_account_id}


def _refused(engine, sql: str, **params) -> str:
    with pytest.raises(IntegrityError) as excinfo, engine.begin() as conn:
        conn.execute(text(sql), params)
    return str(excinfo.value.orig)


@pytest.mark.postgres
def test_a_run_raw_document_or_account_with_rows_cannot_be_deleted(pg_engine):  # noqa: F811
    ids = _seed_run(pg_engine)
    assert "violates foreign key" in _refused(pg_engine, "DELETE FROM broker_import_runs WHERE id = :id", id=ids["run"])
    assert "violates foreign key" in _refused(pg_engine, "DELETE FROM raw_broker_documents WHERE id = :id", id=ids["raw"])
    assert "violates foreign key" in _refused(pg_engine, "DELETE FROM accounts WHERE id = :id", id=BROKER)
    with pg_engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM portfolio_position_snapshots")).scalar_one() == 1

    # Deleting the rows first, explicitly, is the way (as seed_dummy.sql does).
    with pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM portfolio_position_snapshots WHERE import_run_id = :r"), {"r": ids["run"]})
        conn.execute(text("DELETE FROM raw_broker_documents WHERE id = :d"), {"d": ids["raw"]})
        conn.execute(text("DELETE FROM broker_import_runs WHERE id = :r"), {"r": ids["run"]})
        conn.execute(text("DELETE FROM broker_accounts WHERE id = :b"), {"b": ids["broker_account"]})
        conn.execute(text("DELETE FROM accounts WHERE id = :a"), {"a": BROKER})


@pytest.mark.postgres
def test_check_constraints_reject_unknown_values(pg_engine):  # noqa: F811
    ids = _seed_run(pg_engine)
    for sql in (
        "UPDATE portfolio_position_snapshots SET authority_status = 'Authoritative'",
        "UPDATE broker_import_runs SET status = 'done'",
        "UPDATE broker_import_runs SET source_type = 'typo_upload'",
        "UPDATE raw_broker_documents SET source_type = 'typo_upload'",
    ):
        assert "violates check constraint" in _refused(pg_engine, sql)
    with pg_engine.begin() as conn:  # every allowed value is accepted
        for status in ("started", "completed", "failed", "removed"):
            conn.execute(text("UPDATE broker_import_runs SET status = :s WHERE id = :r"), {"s": status, "r": ids["run"]})
        user = conn.execute(text("SELECT id FROM users WHERE id = :u"), {"u": OWNER}).scalar_one()
        conn.execute(
            text(
                "INSERT INTO wealth_monthly_rollups (user_id, month, anchor_date, base_currency, total, cash, "
                "stocks_funds, crypto, liabilities, freshness_status) "
                "VALUES (:u, '2026-03', '2026-04-01', 'SGD', 0, 0, 0, 0, 0, 'carried')"
            ),
            {"u": user},
        )
    assert "violates check constraint" in _refused(
        pg_engine,
        "INSERT INTO wealth_monthly_rollups (user_id, month, anchor_date, base_currency, total, cash, "
        "stocks_funds, crypto, liabilities, freshness_status) "
        "VALUES (:u, '2026-3', '2026-04-01', 'USD', 0, 0, 0, 0, 0, 'fresh')",
        u=OWNER,
    )


def _run_precheck(engine, migration_sql: str) -> list[str]:
    """Run the precheck in a read-only session; returns its notices (raises on violations)."""
    raw = engine.raw_connection()
    try:
        raw.autocommit = True
        cursor = raw.cursor()
        cursor.execute("SET default_transaction_read_only = on")
        cursor.execute(precheck_sql(parse_checks(migration_sql), parse_drops(migration_sql)))
        return list(raw.notices)
    finally:
        raw.close()


@pytest.mark.postgres
def test_precheck_passes_on_a_clean_database_and_lists_rejected_rows(pg_engine):  # noqa: F811
    _seed_run(pg_engine)
    notices = _run_precheck(pg_engine, _sql())
    assert any("All pass" in n for n in notices)

    # A database from before 079 with a value 079 would reject.
    with pg_engine.begin() as conn:
        conn.execute(text("ALTER TABLE broker_import_runs DROP CONSTRAINT broker_import_runs_status_check"))
        conn.execute(text("UPDATE broker_import_runs SET status = 'running'"))
    with pytest.raises(Exception, match=r"1 problem\(s\)"):
        _run_precheck(pg_engine, _sql())
    with pg_engine.connect() as conn:  # and it changed nothing
        assert conn.execute(text("SELECT status FROM broker_import_runs")).scalar_one() == "running"


# ─── Delete paths that must keep working under RESTRICT (Postgres) ───────────

_HOLDINGS_HTML = """<html><body>
<table>
  <tr><th>Symbol</th><th>Stock Name</th><th>Qty</th><th>Avg Price</th><th>Mkt Value</th></tr>
  <tr><td>S68</td><td>SGX</td><td>{qty}</td><td>9.5</td><td>{value}</td></tr>
</table>
</body></html>"""


def _count(engine, sql: str, params: dict | None = None) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(sql), params or {}).scalar_one())


def _rows(engine, sql: str) -> list:
    with engine.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql))]


@pytest.mark.postgres
def test_removing_holdings_uploads_keeps_runs_and_raw_documents(pg_engine, tmp_path):  # noqa: F811
    """#180's undo deletes an upload's facts by run id and keeps the run (status 'removed')
    and its raw document, so RESTRICT never blocks it."""
    client = signed_in_client(pg_engine, OWNER)
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country) "
                "VALUES (:id, 'Test Vickers 158', 'DBS_VICKERS', :u, 'BROKER', 'SGD', 'SG')"
            ),
            {"id": BROKER, "u": OWNER},
        )
    jobs = []
    for qty in (100, 150):
        path = tmp_path / f"holdings_{qty}_2026_02_19.xls"
        path.write_text(_HOLDINGS_HTML.format(qty=qty, value=qty * 9.5), encoding="utf-8")
        if not jobs:
            with Session(bind=pg_engine) as db:
                signature, _ = compute_format_signature(str(path), platform_hint="DBS_VICKERS")
                register_signature(db, signature, "dbs_vickers_holdings_xls_v1", 1)
        with open(path, "rb") as f:
            resp = client.post(
                f"/ingest/upload?account_id={BROKER}", files={"file": (path.name, f, "text/csv")}, data={"as_of": "2026-02-19"}
            )
        assert resp.status_code == 200 and resp.json()["status"] == "IMPORTED", resp.text
        jobs.append(resp.json()["job_id"])
    assert _count(pg_engine, "SELECT COUNT(*) FROM portfolio_position_snapshots") == 1

    for job_id in reversed(jobs):
        removed = client.post(f"/ingest/jobs/{job_id}/remove")
        assert removed.status_code == 200, removed.text

    assert _count(pg_engine, "SELECT COUNT(*) FROM portfolio_position_snapshots") == 0
    assert _count(pg_engine, "SELECT COUNT(*) FROM portfolio_data_completeness") == 0
    assert _count(pg_engine, "SELECT COUNT(*) FROM broker_import_runs WHERE status = 'removed'") == 2
    assert _count(pg_engine, "SELECT COUNT(*) FROM raw_broker_documents") == 2
    assert _count(pg_engine, "SELECT COUNT(*) FROM portfolio_source_authority_windows") == 0


@pytest.mark.postgres
def test_an_ibkr_flex_reimport_replaces_the_dates_facts(pg_engine):  # noqa: F811
    """A Flex re-import of the same dates deletes the earlier run's facts by date and keeps
    the earlier run and its raw XML."""
    signed_in_client(pg_engine, OWNER)
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country) "
                "VALUES (:id, 'Test IBKR 158', 'IBKR', :u, 'BROKER', 'USD', 'US')"
            ),
            {"id": BROKER_FLEX, "u": OWNER},
        )
    xml = flex_xml(FLEX_REPORTS[2])
    for _ in range(2):
        with Session(bind=pg_engine) as db:
            run_ibkr_flex_import_from_xml(db, current_user_id=OWNER, legacy_account_id=BROKER_FLEX, xml_text=xml)
            db.commit()
    assert _count(pg_engine, "SELECT COUNT(*) FROM broker_import_runs") == 2
    assert _count(pg_engine, "SELECT COUNT(*) FROM raw_broker_documents") == 2
    with pg_engine.connect() as conn:
        runs_with_positions = conn.execute(
            text("SELECT COUNT(DISTINCT import_run_id) FROM portfolio_position_snapshots WHERE report_date = :d"),
            {"d": FLEX_REPORTS[2].report_date},
        ).scalar_one()
    assert runs_with_positions == 1


@pytest.mark.postgres
def test_the_dummy_seed_reruns_and_clears_under_restrict(pg_engine):  # noqa: F811
    """make db-seed-dummy (twice: it is re-runnable) then make db-clear-dummy, on the
    migrated database (033 seeds the demo user they need)."""
    seed = (_migrations() / "seed_dummy.sql").read_text(encoding="utf-8")
    cleanup = (_migrations() / "seed_dummy_cleanup.sql").read_text(encoding="utf-8")
    raw = pg_engine.raw_connection()
    try:
        raw.autocommit = True
        cursor = raw.cursor()
        for script in (seed, seed):
            cursor.execute(script)
        assert _count(pg_engine, "SELECT COUNT(*) FROM broker_import_runs WHERE source_type = 'DUMMY'") > 0
        _assert_seed_shape(pg_engine)
        cursor.execute(cleanup)
    finally:
        raw.close()
    assert _count(pg_engine, "SELECT COUNT(*) FROM fx_rates WHERE source = 'DUMMY'") == 0
    assert _count(pg_engine, "SELECT COUNT(*) FROM accounts WHERE name LIKE 'DUMMY - %'") == 0
    assert _count(pg_engine, "SELECT COUNT(*) FROM broker_import_runs WHERE source_type = 'DUMMY'") == 0
    assert _count(pg_engine, "SELECT COUNT(*) FROM portfolio_position_snapshots") == 0


def _assert_seed_shape(pg_engine) -> None:
    """#291: what the demo seed must look like for History and past months to be honest."""
    # Snapshots on the anchor day (the 1st, SNAPSHOT_DAY=1) of every month, plus today.
    days = [
        row[0]
        for row in _rows(pg_engine, "SELECT DISTINCT report_date FROM portfolio_position_snapshots ORDER BY 1")
    ]
    firsts = [d for d in days if d.day == 1]
    assert len(firsts) == 12, days
    assert all(d.day == 1 for d in days[:-1]), days
    # Exchange rates for every day the snapshots span (USD-based, SGD and HKD).
    for quote in ("SGD", "HKD"):
        missing = _count(
            pg_engine,
            "SELECT COUNT(*) FROM generate_series(0, CURRENT_DATE - :lo) AS n "
            "WHERE NOT EXISTS (SELECT 1 FROM fx_rates f WHERE f.base = 'USD' AND f.quote = :q "
            "AND f.rate_date = :lo + n)",
            {"lo": firsts[0], "q": quote},
        )
        assert missing == 0, quote
    # *_base is in the account's currency: IBKR's HKD holdings are converted to its USD base.
    hkd = _rows(
        pg_engine,
        "SELECT ps.market_value_local, ps.market_value_base, ps.fx_rate_to_base FROM portfolio_position_snapshots ps "
        "WHERE ps.currency = 'HKD' LIMIT 1",
    )[0]
    assert float(hkd[2]) < 0.2 and abs(float(hkd[0]) * float(hkd[2]) - float(hkd[1])) < 1
    # No empty, non-DUMMY card left for the demo user (migration 059's placeholder).
    assert _count(
        pg_engine,
        "SELECT COUNT(*) FROM accounts a JOIN users u ON u.id = a.user_id "
        "WHERE LOWER(u.username) = 'demo' AND a.name NOT LIKE 'DUMMY - %'",
    ) == 0


@pytest.mark.postgres
def test_the_dummy_cleanup_marks_history_dirty_from_the_earliest_dummy_price(pg_engine):  # noqa: F811
    """#221: DUMMY prices are shared, so the cleanup marks every user's History from the
    earliest DUMMY price date, and the dummy rows' owner (demo) from all of history."""
    seed = (_migrations() / "seed_dummy.sql").read_text(encoding="utf-8")
    cleanup = (_migrations() / "seed_dummy_cleanup.sql").read_text(encoding="utf-8")
    with pg_engine.begin() as conn:
        conn.execute(text("INSERT INTO users (username) VALUES ('real_a'), ('real_b'), ('real_c')"))
        # real_b has a later mark pending (it moves earlier), real_c an earlier one (it stays).
        conn.execute(text(
            "INSERT INTO wealth_rollup_dirty (user_id, from_date, generation, marked_at, reason) "
            "SELECT id, CASE username WHEN 'real_b' THEN DATE '2099-01-01' ELSE DATE '1990-01-01' END, 5, now(), 'earlier' "
            "FROM users WHERE username IN ('real_b', 'real_c')"
        ))
    raw = pg_engine.raw_connection()
    try:
        raw.autocommit = True
        cursor = raw.cursor()
        cursor.execute(seed)
        # The earliest DUMMY price or DUMMY exchange rate (#291): both are shared tables.
        cursor.execute(
            "SELECT LEAST("
            "(SELECT MIN(LEAST(trade_date, (ts AT TIME ZONE 'UTC')::date)) FROM prices WHERE source = 'DUMMY'), "
            "(SELECT MIN(rate_date) FROM fx_rates WHERE source = 'DUMMY'))"
        )
        earliest = cursor.fetchone()[0]
        assert earliest is not None
        cursor.execute(cleanup)
    finally:
        raw.close()
    with pg_engine.connect() as conn:
        marks = {
            row.username: row
            for row in conn.execute(text(
                "SELECT u.username, d.from_date, d.generation, d.reason "
                "FROM users u LEFT JOIN wealth_rollup_dirty d ON d.user_id = u.id"
            ))
        }
    assert _count(pg_engine, "SELECT COUNT(*) FROM prices WHERE source = 'DUMMY'") == 0
    assert str(marks["demo"].from_date) == "1970-01-01"
    assert marks["real_a"].from_date == earliest and marks["real_a"].reason == "dummy_cleanup"
    assert marks["real_b"].from_date == earliest and marks["real_b"].generation == 6
    assert str(marks["real_c"].from_date) == "1990-01-01" and marks["real_c"].generation == 6
    assert all(row.from_date is not None for row in marks.values()), "every user is marked"



@pytest.mark.postgres
def test_precheck_names_a_constraint_to_drop_that_is_not_there(pg_engine):  # noqa: F811
    sql = "ALTER TABLE broker_import_runs DROP CONSTRAINT broker_import_runs_renamed_fkey;\n"
    assert parse_drops(sql) == [Drop("broker_import_runs", "broker_import_runs_renamed_fkey")]
    with pytest.raises(Exception, match=r"1 problem\(s\)"):
        _run_precheck(pg_engine, sql)
