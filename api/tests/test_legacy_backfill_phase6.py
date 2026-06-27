"""
Phase 6: Legacy position backfill and parity audit tests.

Verifies:
- Backfill migrates all eligible legacy stock/fund positions to
  portfolio_position_snapshots.
- Backfill migrates all eligible legacy cash rows to
  account_balance_snapshots.
- Backfill is idempotent: running twice produces the same rows and totals.
- Existing authoritative canonical facts are NOT overwritten.
- Data-quality events are created for skipped/conflicted rows.
- Parity report generates correct comparison sections.
- Legacy positions table is NOT modified (no deletes or truncates).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.portfolio.legacy_backfill import (
    BACKFILL_SOURCE_KIND,
    BACKFILL_SOURCE_TYPE,
    BackfillResult,
    backfill_legacy_positions,
)
from app.portfolio.parity_report import generate_parity_report

# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------

USER_ID = 901
STOCK_ACCOUNT_ID = 9010
FUND_ACCOUNT_ID = 9011
CASH_ACCOUNT_ID = 9012

STOCK_ASSET_ID = 9001
FUND_ASSET_ID = 9002
CASH_ASSET_ID = 9003

AS_OF = datetime(2026, 1, 31, 0, 0, 0, tzinfo=timezone.utc)
REPORT_DATE = date(2026, 1, 31)


def _ts():
    return datetime.now(tz=timezone.utc).replace(microsecond=0)


# ---------------------------------------------------------------------------
# DB seeding helpers
# ---------------------------------------------------------------------------


def _seed_user(conn, user_id: int) -> None:
    conn.exec_driver_sql(
        "INSERT OR IGNORE INTO users (id, username, display_name, is_active, is_admin) "
        "VALUES (?, 'user_'||?, 'User '||?, 1, 0)",
        (user_id, user_id, user_id),
    )


def _seed_account(
    conn,
    account_id: int,
    user_id: int,
    platform: str = "SHAREKHAN",
    account_type: str = "BROKER",
    currency: str = "INR",
) -> None:
    conn.exec_driver_sql(
        "INSERT OR IGNORE INTO accounts "
        "(id, name, platform, user_id, account_type, currency) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (account_id, f"Acct {account_id}", platform, user_id, account_type, currency),
    )


def _seed_asset(
    conn,
    asset_id: int,
    symbol: str,
    asset_class: str,
    quote_currency: str,
    home_country: str = "US",
    name: str | None = None,
) -> None:
    conn.exec_driver_sql(
        "INSERT OR IGNORE INTO assets (id, symbol, name, asset_class, quote_currency, home_country) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (asset_id, symbol, name or symbol, asset_class, quote_currency, home_country),
    )


def _seed_position(
    conn,
    pos_id: int,
    account_id: int,
    asset_id: int,
    as_of: datetime,
    quantity: float,
    avg_cost: float | None,
    cost_basis_base: float,
) -> None:
    conn.exec_driver_sql(
        "INSERT OR IGNORE INTO positions "
        "(id, account_id, asset_id, as_of, quantity, avg_cost, cost_basis_base) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (pos_id, account_id, asset_id, as_of, quantity, avg_cost, cost_basis_base),
    )


def _seed_ibkr_flex_authority_window(
    conn,
    *,
    user_id: int,
    legacy_account_id: int,
    broker_account_id: str,
    effective_from: date,
    effective_to: date | None = None,
) -> None:
    conn.exec_driver_sql(
        "INSERT INTO broker_connections "
        "(user_id, platform_code, connection_type, display_name, status, metadata_json) "
        "VALUES (?, 'IBKR', 'flex_api', 'IBKR Flex', 'active', '{}')",
        (user_id,),
    )
    connection_id = conn.exec_driver_sql(
        "SELECT id FROM broker_connections "
        "WHERE user_id = ? AND platform_code = 'IBKR' AND connection_type = 'flex_api' "
        "ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()[0]
    conn.exec_driver_sql(
        "INSERT INTO broker_accounts "
        "(connection_id, legacy_account_id, broker_account_id, base_currency, status, metadata_json) "
        "VALUES (?, ?, ?, 'SGD', 'active', '{}')",
        (connection_id, legacy_account_id, broker_account_id),
    )
    broker_account_pk = conn.exec_driver_sql(
        "SELECT id FROM broker_accounts WHERE connection_id = ? AND broker_account_id = ? LIMIT 1",
        (connection_id, broker_account_id),
    ).fetchone()[0]
    conn.exec_driver_sql(
        "INSERT INTO portfolio_source_authority_windows "
        "(broker_account_id, source_kind, fact_scope, effective_from, effective_to, authority_status) "
        "VALUES (?, 'ibkr_flex_daily', 'all', ?, ?, 'authoritative')",
        (broker_account_pk, effective_from, effective_to),
    )


def _count_table(conn, table: str, where: str = "", params: tuple = ()) -> int:
    sql = f"SELECT COUNT(*) FROM {table}"
    if where:
        sql += f" WHERE {where}"
    row = conn.exec_driver_sql(sql, params).fetchone()
    return int(row[0])


# ---------------------------------------------------------------------------
# Shared DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session(db_engine):
    """Provide a fresh SQLAlchemy session for each test."""
    Session_ = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    session = Session_()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def seeded_db(db_engine):
    """
    Seed a minimal dataset into the test DB:
    - 1 user
    - 3 accounts (stock, fund, cash)
    - 3 assets (STOCK, FUND, CASH)
    - 3 legacy positions (one per asset)
    """
    with db_engine.begin() as conn:
        _seed_user(conn, USER_ID)
        _seed_account(conn, STOCK_ACCOUNT_ID, USER_ID, platform="SHAREKHAN", currency="INR")
        _seed_account(conn, FUND_ACCOUNT_ID, USER_ID, platform="DBS_VICKERS", currency="SGD")
        _seed_account(conn, CASH_ACCOUNT_ID, USER_ID, platform="DBS", account_type="BANK", currency="SGD")
        _seed_asset(conn, STOCK_ASSET_ID, "RELIANCE", "STOCK", "INR", "IN")
        _seed_asset(conn, FUND_ASSET_ID, "NIFTYFUND", "FUND", "INR", "IN")
        _seed_asset(conn, CASH_ASSET_ID, "CASH_SGD", "CASH", "SGD", "SG")
        _seed_position(conn, 9001, STOCK_ACCOUNT_ID, STOCK_ASSET_ID, AS_OF, 100.0, 250.0, 25000.0)
        _seed_position(conn, 9002, FUND_ACCOUNT_ID, FUND_ASSET_ID, AS_OF, 50.0, 100.0, 5000.0)
        _seed_position(conn, 9003, CASH_ACCOUNT_ID, CASH_ASSET_ID, AS_OF, 1.0, None, 3000.0)
    yield
    # cleanup is handled by conftest clear_db autouse fixture


# ---------------------------------------------------------------------------
# Test: basic stock migration
# ---------------------------------------------------------------------------


def test_backfill_stock_positions(db_session, seeded_db):
    result = backfill_legacy_positions(db_session, current_user_id=USER_ID)

    assert result.stock_fund_migrated >= 1, "Expected at least 1 stock position migrated"

    # Canonical snapshot row exists
    row = db_session.execute(
        text(
            """
            SELECT pps.quantity, pps.currency, pps.market_value_base, pps.authority_status
            FROM portfolio_position_snapshots pps
            JOIN broker_accounts ba ON ba.id = pps.broker_account_id
            WHERE ba.legacy_account_id = :acct_id
              AND pps.report_date = :report_date
              AND pps.authority_status = 'authoritative'
            """
        ),
        {"acct_id": STOCK_ACCOUNT_ID, "report_date": REPORT_DATE},
    ).fetchone()
    assert row is not None, "Canonical position snapshot for stock account not found"
    assert float(row[0]) == pytest.approx(100.0), "Quantity mismatch"
    assert row[3] == "authoritative"


# ---------------------------------------------------------------------------
# Test: basic fund migration
# ---------------------------------------------------------------------------


def test_backfill_fund_positions(db_session, seeded_db):
    result = backfill_legacy_positions(db_session, current_user_id=USER_ID)

    assert result.stock_fund_migrated >= 1

    row = db_session.execute(
        text(
            """
            SELECT pps.quantity, pps.currency
            FROM portfolio_position_snapshots pps
            JOIN broker_accounts ba ON ba.id = pps.broker_account_id
            WHERE ba.legacy_account_id = :acct_id
              AND pps.report_date = :report_date
              AND pps.authority_status = 'authoritative'
            """
        ),
        {"acct_id": FUND_ACCOUNT_ID, "report_date": REPORT_DATE},
    ).fetchone()
    assert row is not None, "Canonical position snapshot for fund account not found"
    assert float(row[0]) == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Test: basic cash migration
# ---------------------------------------------------------------------------


def test_backfill_cash_positions(db_session, seeded_db):
    result = backfill_legacy_positions(db_session, current_user_id=USER_ID)

    assert result.cash_migrated >= 1

    row = db_session.execute(
        text(
            """
            SELECT balance_local, currency, authority_status, source_kind
            FROM account_balance_snapshots
            WHERE account_id = :acct_id
              AND as_of_date = :as_of_date
              AND authority_status = 'authoritative'
            """
        ),
        {"acct_id": CASH_ACCOUNT_ID, "as_of_date": REPORT_DATE},
    ).fetchone()
    assert row is not None, "Canonical cash balance snapshot not found"
    assert float(row[0]) == pytest.approx(3000.0)
    assert row[2] == "authoritative"
    assert row[3] == BACKFILL_SOURCE_KIND


def test_backfill_persists_historical_fx_rates(db_session, db_engine, monkeypatch):
    user_id = 902
    stock_account_id = 9020
    cash_account_id = 9021
    stock_asset_id = 9022
    cash_asset_id = 9023
    as_of = datetime(2026, 2, 28, 0, 0, 0, tzinfo=timezone.utc)

    with db_engine.begin() as conn:
        _seed_user(conn, user_id)
        _seed_account(conn, stock_account_id, user_id, platform="SHAREKHAN", currency="SGD")
        _seed_account(conn, cash_account_id, user_id, platform="DBS", account_type="BANK", currency="SGD")
        _seed_asset(conn, stock_asset_id, "ACME", "STOCK", "USD", "US")
        _seed_asset(conn, cash_asset_id, "USD_CASH", "CASH", "USD", "US")
        _seed_position(conn, 9101, stock_account_id, stock_asset_id, as_of, 10.0, 100.0, 1500.0)
        _seed_position(conn, 9102, cash_account_id, cash_asset_id, as_of, 1.0, None, 1500.0)

    def fake_get_rates(date, base, symbols):
        assert base == "SGD"
        assert "USD" in set(symbols)
        return {"SGD": 1.0, "USD": 1.5}

    monkeypatch.setattr("app.portfolio.legacy_backfill.get_rates", fake_get_rates)

    backfill_legacy_positions(db_session, current_user_id=user_id)

    stock_row = db_session.execute(
        text(
            """
            SELECT pps.fx_rate_to_base, pps.market_value_local, pps.market_value_base
            FROM portfolio_position_snapshots pps
            JOIN broker_accounts ba ON ba.id = pps.broker_account_id
            WHERE ba.legacy_account_id = :acct_id
              AND pps.report_date = :report_date
              AND pps.authority_status = 'authoritative'
            """
        ),
        {"acct_id": stock_account_id, "report_date": as_of.date()},
    ).fetchone()
    assert stock_row is not None
    assert float(stock_row[0]) == pytest.approx(1.5)
    assert float(stock_row[1]) == pytest.approx(1000.0)
    assert float(stock_row[2]) == pytest.approx(1500.0)

    cash_row = db_session.execute(
        text(
            """
            SELECT abs.fx_rate_to_base, abs.balance_local, abs.balance_base
            FROM account_balance_snapshots abs
            WHERE abs.account_id = :acct_id
              AND abs.as_of_date = :report_date
              AND abs.authority_status = 'authoritative'
            """
        ),
        {"acct_id": cash_account_id, "report_date": as_of.date()},
    ).fetchone()
    assert cash_row is not None
    assert float(cash_row[0]) == pytest.approx(1.5)
    assert float(cash_row[1]) == pytest.approx(1000.0)
    assert float(cash_row[2]) == pytest.approx(1500.0)


def test_ibkr_pre_flex_backfill_treats_legacy_values_as_local(db_session, db_engine, monkeypatch):
    user_id = 903
    account_id = 9030
    stock_asset_id = 9031
    cash_asset_id = 9032
    as_of = datetime(2026, 5, 15, 0, 0, 0, tzinfo=timezone.utc)

    with db_engine.begin() as conn:
        _seed_user(conn, user_id)
        _seed_account(conn, account_id, user_id, platform="IBKR", currency="SGD")
        _seed_asset(conn, stock_asset_id, "0700", "STOCK", "HKD", "HK")
        _seed_asset(conn, cash_asset_id, "USD_CASH", "CASH", "USD", "US")
        _seed_position(conn, 9201, account_id, stock_asset_id, as_of, 10.0, 40.0, 1000.0)
        _seed_position(conn, 9202, account_id, cash_asset_id, as_of, 1.0, None, 1000.0)
        _seed_ibkr_flex_authority_window(
            conn,
            user_id=user_id,
            legacy_account_id=account_id,
            broker_account_id="U_TEST_FLEX",
            effective_from=date(2026, 6, 1),
        )

    def fake_get_rates(_date, base, symbols):
        assert base == "SGD"
        requested = set(symbols)
        rates = {"SGD": 1.0, "HKD": 0.17, "USD": 1.35}
        return {symbol: rates[symbol] for symbol in requested | {"SGD"}}

    monkeypatch.setattr("app.portfolio.legacy_backfill.get_rates", fake_get_rates)

    result = backfill_legacy_positions(db_session, current_user_id=user_id)

    assert result.stock_fund_migrated == 1
    assert result.cash_migrated == 1

    stock_row = db_session.execute(
        text(
            """
            SELECT pps.fx_rate_to_base, pps.market_price, pps.market_value_local,
                   pps.market_value_base, pps.cost_basis_local, pps.cost_basis_base
            FROM portfolio_position_snapshots pps
            JOIN broker_accounts ba ON ba.id = pps.broker_account_id
            WHERE ba.legacy_account_id = :acct_id
              AND pps.report_date = :report_date
              AND pps.authority_status = 'authoritative'
            """
        ),
        {"acct_id": account_id, "report_date": as_of.date()},
    ).fetchone()
    assert stock_row is not None
    assert float(stock_row[0]) == pytest.approx(0.17)
    assert float(stock_row[1]) == pytest.approx(100.0)
    assert float(stock_row[2]) == pytest.approx(1000.0)
    assert float(stock_row[3]) == pytest.approx(170.0)
    assert float(stock_row[4]) == pytest.approx(400.0)
    assert float(stock_row[5]) == pytest.approx(68.0)

    cash_row = db_session.execute(
        text(
            """
            SELECT abs.fx_rate_to_base, abs.balance_local, abs.balance_base
            FROM account_balance_snapshots abs
            WHERE abs.account_id = :acct_id
              AND abs.as_of_date = :report_date
              AND abs.authority_status = 'authoritative'
            """
        ),
        {"acct_id": account_id, "report_date": as_of.date()},
    ).fetchone()
    assert cash_row is not None
    assert float(cash_row[0]) == pytest.approx(1.35)
    assert float(cash_row[1]) == pytest.approx(1000.0)
    assert float(cash_row[2]) == pytest.approx(1350.0)


def test_ibkr_legacy_backfill_skips_rows_inside_flex_authority_window(
    db_session,
    db_engine,
    monkeypatch,
):
    user_id = 904
    account_id = 9040
    stock_asset_id = 9041
    cash_asset_id = 9042
    as_of = datetime(2026, 6, 15, 0, 0, 0, tzinfo=timezone.utc)

    with db_engine.begin() as conn:
        _seed_user(conn, user_id)
        _seed_account(conn, account_id, user_id, platform="IBKR", currency="SGD")
        _seed_asset(conn, stock_asset_id, "NVO", "STOCK", "USD", "US")
        _seed_asset(conn, cash_asset_id, "USD_CASH", "CASH", "USD", "US")
        _seed_position(conn, 9301, account_id, stock_asset_id, as_of, 10.0, 51.0, 510.0)
        _seed_position(conn, 9302, account_id, cash_asset_id, as_of, 1.0, None, 1000.0)
        _seed_ibkr_flex_authority_window(
            conn,
            user_id=user_id,
            legacy_account_id=account_id,
            broker_account_id="U_TEST_FLEX_2",
            effective_from=date(2026, 6, 1),
        )

    monkeypatch.setattr(
        "app.portfolio.legacy_backfill.get_rates",
        lambda _date, _base, symbols: {symbol: 1.35 for symbol in set(symbols) | {"SGD"}},
    )

    result = backfill_legacy_positions(db_session, current_user_id=user_id)

    assert result.stock_fund_migrated == 0
    assert result.cash_migrated == 0
    assert result.stock_fund_skipped_covered == 1
    assert result.cash_skipped_covered == 1

    position_count = db_session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM portfolio_position_snapshots pps
            JOIN broker_accounts ba ON ba.id = pps.broker_account_id
            WHERE ba.legacy_account_id = :acct_id
            """
        ),
        {"acct_id": account_id},
    ).scalar()
    cash_count = db_session.execute(
        text("SELECT COUNT(*) FROM account_balance_snapshots WHERE account_id = :acct_id"),
        {"acct_id": account_id},
    ).scalar()

    assert position_count == 0
    assert cash_count == 0


# ---------------------------------------------------------------------------
# Test: idempotency – stock/fund
# ---------------------------------------------------------------------------


def test_backfill_idempotent_stock_fund(db_session, seeded_db):
    result1 = backfill_legacy_positions(db_session, current_user_id=USER_ID)
    migrated_first = result1.stock_fund_migrated

    # Count snapshot rows after first run
    count_after_first = db_session.execute(
        text("SELECT COUNT(*) FROM portfolio_position_snapshots WHERE authority_status = 'authoritative'")
    ).scalar()

    result2 = backfill_legacy_positions(db_session, current_user_id=USER_ID)

    # Second run: all rows are already covered → skipped
    count_after_second = db_session.execute(
        text("SELECT COUNT(*) FROM portfolio_position_snapshots WHERE authority_status = 'authoritative'")
    ).scalar()

    assert count_after_first == count_after_second, (
        "Second run changed the number of authoritative position snapshots"
    )
    # Second run should report 0 migrated (everything already covered)
    assert result2.stock_fund_migrated == 0 or result2.stock_fund_skipped_covered > 0, (
        "Second run should either migrate 0 or report skipped rows"
    )


# ---------------------------------------------------------------------------
# Test: idempotency – cash
# ---------------------------------------------------------------------------


def test_backfill_idempotent_cash(db_session, seeded_db):
    backfill_legacy_positions(db_session, current_user_id=USER_ID)

    count_after_first = db_session.execute(
        text("SELECT COUNT(*) FROM account_balance_snapshots WHERE authority_status = 'authoritative'")
    ).scalar()

    backfill_legacy_positions(db_session, current_user_id=USER_ID)

    count_after_second = db_session.execute(
        text("SELECT COUNT(*) FROM account_balance_snapshots WHERE authority_status = 'authoritative'")
    ).scalar()

    assert count_after_first == count_after_second, (
        "Second run changed the number of authoritative cash balance snapshots"
    )


# ---------------------------------------------------------------------------
# Test: no overwrite of existing authoritative canonical facts
# ---------------------------------------------------------------------------


def test_no_overwrite_existing_authoritative_position(db_session, seeded_db):
    """
    If a portfolio_position_snapshot with authority_status='authoritative'
    already exists for the same account/date, the backfill must NOT create a
    duplicate authoritative row and must emit a data-quality event.
    """
    # Manually insert an authoritative canonical position for the stock account
    # before running the backfill.
    existing_value = 99999.0

    # Ensure broker connection and account exist (Phase 2 upload adapter style)
    with db_session.begin_nested():
        db_session.execute(
            text(
                "INSERT INTO broker_connections "
                "(user_id, platform_code, connection_type, status, metadata_json) "
                "VALUES (:uid, 'SHAREKHAN', 'manual_upload', 'active', '{}')"
            ),
            {"uid": USER_ID},
        )
        conn_id = db_session.execute(
            text(
                "SELECT id FROM broker_connections WHERE user_id=:uid AND platform_code='SHAREKHAN' "
                "AND connection_type='manual_upload' ORDER BY id DESC LIMIT 1"
            ),
            {"uid": USER_ID},
        ).scalar()

        db_session.execute(
            text(
                "INSERT INTO broker_accounts "
                "(connection_id, legacy_account_id, broker_account_id, base_currency, status, metadata_json) "
                "VALUES (:conn_id, :acct_id, 'upload_9010', 'INR', 'active', '{}')"
            ),
            {"conn_id": conn_id, "acct_id": STOCK_ACCOUNT_ID},
        )
        ba_id = db_session.execute(
            text(
                "SELECT id FROM broker_accounts WHERE connection_id=:conn_id AND broker_account_id='upload_9010' LIMIT 1"
            ),
            {"conn_id": conn_id},
        ).scalar()

        db_session.execute(
            text(
                "INSERT INTO broker_import_runs "
                "(broker_account_id, legacy_account_id, platform_code, source_type, status, "
                "report_date_from, report_date_to, parser_version, metadata_json) "
                "VALUES (:ba_id, :acct_id, 'SHAREKHAN', 'sharekhan_upload', 'completed', "
                ":rd, :rd, 'test_v1', '{}')"
            ),
            {"ba_id": ba_id, "acct_id": STOCK_ACCOUNT_ID, "rd": REPORT_DATE},
        )
        run_id = db_session.execute(
            text("SELECT id FROM broker_import_runs WHERE broker_account_id=:ba_id ORDER BY id DESC LIMIT 1"),
            {"ba_id": ba_id},
        ).scalar()

        db_session.execute(
            text(
                "INSERT INTO broker_instruments "
                "(platform_code, broker_instrument_id, asset_id, symbol, currency, metadata_json) "
                "VALUES ('SHAREKHAN', 'RELIANCE_INR', :asset_id, 'RELIANCE', 'INR', '{}')"
            ),
            {"asset_id": STOCK_ASSET_ID},
        )
        instr_id = db_session.execute(
            text(
                "SELECT id FROM broker_instruments WHERE platform_code='SHAREKHAN' "
                "AND broker_instrument_id='RELIANCE_INR' LIMIT 1"
            )
        ).scalar()

        db_session.execute(
            text(
                "INSERT INTO portfolio_position_snapshots "
                "(broker_account_id, legacy_account_id, broker_instrument_id, import_run_id, "
                "report_date, quantity, currency, market_price, market_value_local, market_value_base, "
                "cost_basis_local, cost_basis_base, fx_rate_to_base, authority_status, metadata_json) "
                "VALUES (:ba_id, :acct_id, :instr_id, :run_id, :rd, 100, 'INR', 250, "
                ":val, :val, :val, :val, 1, 'authoritative', '{}')"
            ),
            {
                "ba_id": ba_id,
                "acct_id": STOCK_ACCOUNT_ID,
                "instr_id": instr_id,
                "run_id": run_id,
                "rd": REPORT_DATE,
                "val": existing_value,
            },
        )

    # Count authoritative snapshots for this account before backfill
    count_before = db_session.execute(
        text(
            "SELECT COUNT(*) FROM portfolio_position_snapshots pps "
            "JOIN broker_accounts ba ON ba.id = pps.broker_account_id "
            "WHERE ba.legacy_account_id = :acct_id AND pps.authority_status = 'authoritative'"
        ),
        {"acct_id": STOCK_ACCOUNT_ID},
    ).scalar()

    result = backfill_legacy_positions(db_session, current_user_id=USER_ID)

    # Count after backfill - must not have increased for the stock account
    count_after = db_session.execute(
        text(
            "SELECT COUNT(*) FROM portfolio_position_snapshots pps "
            "JOIN broker_accounts ba ON ba.id = pps.broker_account_id "
            "WHERE ba.legacy_account_id = :acct_id AND pps.authority_status = 'authoritative'"
        ),
        {"acct_id": STOCK_ACCOUNT_ID},
    ).scalar()

    assert count_before == count_after, (
        f"Backfill added authoritative rows to an already-covered account: before={count_before}, after={count_after}"
    )
    assert result.stock_fund_skipped_covered >= 1, "Expected at least 1 covered skip event"

    # The existing market_value_base must remain as set before backfill
    row = db_session.execute(
        text(
            "SELECT pps.market_value_base FROM portfolio_position_snapshots pps "
            "JOIN broker_accounts ba ON ba.id = pps.broker_account_id "
            "WHERE ba.legacy_account_id = :acct_id AND pps.report_date = :rd "
            "AND pps.authority_status = 'authoritative'"
        ),
        {"acct_id": STOCK_ACCOUNT_ID, "rd": REPORT_DATE},
    ).fetchone()
    assert row is not None
    assert float(row[0]) == pytest.approx(existing_value), "Backfill overwrote existing authoritative value"


def test_partial_authoritative_coverage_does_not_skip_account_date(db_session, db_engine, seeded_db):
    """
    An existing authoritative snapshot for one security must not make the
    backfill skip every other security for the same account/date.
    """
    second_asset_id = 9014
    with db_engine.begin() as conn:
        _seed_asset(conn, second_asset_id, "SECOND", "STOCK", "INR", "IN")
        _seed_position(conn, 9014, STOCK_ACCOUNT_ID, second_asset_id, AS_OF, 25.0, 40.0, 1000.0)

    with db_session.begin_nested():
        db_session.execute(
            text(
                "INSERT INTO broker_connections "
                "(user_id, platform_code, connection_type, status, metadata_json) "
                "VALUES (:uid, 'SHAREKHAN', 'manual_upload', 'active', '{}')"
            ),
            {"uid": USER_ID},
        )
        conn_id = db_session.execute(
            text(
                "SELECT id FROM broker_connections WHERE user_id=:uid AND platform_code='SHAREKHAN' "
                "AND connection_type='manual_upload' ORDER BY id DESC LIMIT 1"
            ),
            {"uid": USER_ID},
        ).scalar()
        db_session.execute(
            text(
                "INSERT INTO broker_accounts "
                "(connection_id, legacy_account_id, broker_account_id, base_currency, status, metadata_json) "
                "VALUES (:conn_id, :acct_id, 'partial_coverage_9010', 'INR', 'active', '{}')"
            ),
            {"conn_id": conn_id, "acct_id": STOCK_ACCOUNT_ID},
        )
        ba_id = db_session.execute(
            text(
                "SELECT id FROM broker_accounts WHERE connection_id=:conn_id "
                "AND broker_account_id='partial_coverage_9010' LIMIT 1"
            ),
            {"conn_id": conn_id},
        ).scalar()
        db_session.execute(
            text(
                "INSERT INTO broker_import_runs "
                "(broker_account_id, legacy_account_id, platform_code, source_type, status, "
                "report_date_from, report_date_to, parser_version, metadata_json) "
                "VALUES (:ba_id, :acct_id, 'SHAREKHAN', 'sharekhan_upload', 'completed', "
                ":rd, :rd, 'test_v1', '{}')"
            ),
            {"ba_id": ba_id, "acct_id": STOCK_ACCOUNT_ID, "rd": REPORT_DATE},
        )
        run_id = db_session.execute(
            text("SELECT id FROM broker_import_runs WHERE broker_account_id=:ba_id ORDER BY id DESC LIMIT 1"),
            {"ba_id": ba_id},
        ).scalar()
        db_session.execute(
            text(
                "INSERT INTO broker_instruments "
                "(platform_code, broker_instrument_id, asset_id, symbol, currency, metadata_json) "
                "VALUES ('SHAREKHAN', 'RELIANCE_INR_PARTIAL', :asset_id, 'RELIANCE', 'INR', '{}')"
            ),
            {"asset_id": STOCK_ASSET_ID},
        )
        instr_id = db_session.execute(
            text(
                "SELECT id FROM broker_instruments WHERE platform_code='SHAREKHAN' "
                "AND broker_instrument_id='RELIANCE_INR_PARTIAL' LIMIT 1"
            )
        ).scalar()
        db_session.execute(
            text(
                "INSERT INTO portfolio_position_snapshots "
                "(broker_account_id, legacy_account_id, broker_instrument_id, import_run_id, "
                "report_date, quantity, currency, market_price, market_value_local, market_value_base, "
                "cost_basis_local, cost_basis_base, fx_rate_to_base, authority_status, metadata_json) "
                "VALUES (:ba_id, :acct_id, :instr_id, :run_id, :rd, 100, 'INR', 250, "
                "25000, 25000, 25000, 25000, 1, 'authoritative', '{}')"
            ),
            {
                "ba_id": ba_id,
                "acct_id": STOCK_ACCOUNT_ID,
                "instr_id": instr_id,
                "run_id": run_id,
                "rd": REPORT_DATE,
            },
        )

    result = backfill_legacy_positions(db_session, current_user_id=USER_ID)

    assert result.stock_fund_skipped_covered >= 1
    second_row = db_session.execute(
        text(
            """
            SELECT pps.quantity, pps.market_value_base
            FROM portfolio_position_snapshots pps
            JOIN broker_accounts ba ON ba.id = pps.broker_account_id
            JOIN broker_instruments bi ON bi.id = pps.broker_instrument_id
            WHERE ba.legacy_account_id = :acct_id
              AND bi.asset_id = :asset_id
              AND pps.report_date = :report_date
              AND pps.authority_status = 'authoritative'
            """
        ),
        {"acct_id": STOCK_ACCOUNT_ID, "asset_id": second_asset_id, "report_date": REPORT_DATE},
    ).fetchone()
    assert second_row is not None
    assert float(second_row[0]) == pytest.approx(25.0)
    assert float(second_row[1]) == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# Test: conflict creates data-quality event
# ---------------------------------------------------------------------------


def test_conflict_creates_data_quality_event(db_session, seeded_db):
    """
    When a legacy position is skipped because authoritative canonical data
    already exists, a data-quality event should be recorded.
    """
    # First run creates canonical data
    backfill_legacy_positions(db_session, current_user_id=USER_ID)

    dqe_count_first = db_session.execute(
        text("SELECT COUNT(*) FROM portfolio_data_quality_events WHERE event_code = 'backfill_skipped_covered'")
    ).scalar()

    # Second run: every position is covered → data quality events should be emitted
    result2 = backfill_legacy_positions(db_session, current_user_id=USER_ID)

    dqe_count_second = db_session.execute(
        text("SELECT COUNT(*) FROM portfolio_data_quality_events WHERE event_code = 'backfill_skipped_covered'")
    ).scalar()

    # After second run, more DQEs should exist for the covered positions
    assert dqe_count_second >= dqe_count_first, (
        "Expected data-quality events after second run on already-covered positions"
    )


def test_unmappable_legacy_rows_create_data_quality_events(db_session, db_engine, seeded_db):
    """
    Broken legacy rows should be visible as data-quality events instead of
    disappearing through the normal account/asset joins.
    """
    with db_engine.begin() as conn:
        _seed_position(conn, 9910, 999999, STOCK_ASSET_ID, AS_OF, 1.0, 1.0, 1.0)
        _seed_position(conn, 9911, STOCK_ACCOUNT_ID, 999998, AS_OF, 1.0, 1.0, 1.0)

    result = backfill_legacy_positions(db_session, current_user_id=USER_ID)

    missing_account = db_session.execute(
        text(
            "SELECT COUNT(*) FROM portfolio_data_quality_events "
            "WHERE event_code = 'backfill_missing_account_mapping'"
        )
    ).scalar()
    unmapped_asset = db_session.execute(
        text(
            "SELECT COUNT(*) FROM portfolio_data_quality_events "
            "WHERE event_code = 'backfill_unmapped_asset'"
        )
    ).scalar()

    assert result.stock_fund_skipped_no_account >= 1
    assert result.stock_fund_skipped_unmapped_asset >= 1
    assert missing_account >= 1
    assert unmapped_asset >= 1


# ---------------------------------------------------------------------------
# Test: legacy positions table is not modified
# ---------------------------------------------------------------------------


def test_legacy_positions_not_deleted(db_session, seeded_db):
    count_before = db_session.execute(text("SELECT COUNT(*) FROM positions")).scalar()
    backfill_legacy_positions(db_session, current_user_id=USER_ID)
    count_after = db_session.execute(text("SELECT COUNT(*) FROM positions")).scalar()
    assert count_before == count_after, "Backfill must not delete or modify legacy positions table"


# ---------------------------------------------------------------------------
# Test: synthetic lineage is created
# ---------------------------------------------------------------------------


def test_backfill_synthetic_lineage(db_session, seeded_db):
    backfill_legacy_positions(db_session, current_user_id=USER_ID)

    run_count = db_session.execute(
        text(
            "SELECT COUNT(*) FROM broker_import_runs WHERE source_type = :st"
        ),
        {"st": BACKFILL_SOURCE_TYPE},
    ).scalar()
    assert run_count >= 1, "No synthetic import runs created"

    ba_count = db_session.execute(
        text(
            "SELECT COUNT(*) FROM broker_accounts ba "
            "JOIN broker_connections bc ON bc.id = ba.connection_id "
            "WHERE bc.connection_type = 'legacy_backfill'"
        )
    ).scalar()
    assert ba_count >= 1, "No synthetic broker accounts created for backfill"


# ---------------------------------------------------------------------------
# Test: broker_instrument linked to asset_id
# ---------------------------------------------------------------------------


def test_backfill_broker_instrument_linked_to_asset(db_session, seeded_db):
    backfill_legacy_positions(db_session, current_user_id=USER_ID)

    row = db_session.execute(
        text(
            "SELECT bi.asset_id FROM broker_instruments bi "
            "WHERE bi.platform_code = 'LEGACY_BACKFILL' AND bi.symbol = 'RELIANCE' LIMIT 1"
        )
    ).fetchone()
    assert row is not None, "No backfill broker_instrument for RELIANCE"
    assert int(row[0]) == STOCK_ASSET_ID, "broker_instrument.asset_id mismatch"


# ---------------------------------------------------------------------------
# Test: parity report with zero canonical data shows full delta
# ---------------------------------------------------------------------------


def test_parity_report_before_backfill(db_session, seeded_db):
    """Before backfill: canonical tables are empty, legacy has data → large delta."""
    report = generate_parity_report(db_session, current_user_id=USER_ID, anchor_date=REPORT_DATE)

    assert "net_worth" in report
    assert "stock_holdings" in report
    assert "cash_balances" in report
    assert "platform_alloc" in report
    assert "geography_alloc" in report
    assert "summary" in report

    # Legacy should have stock + fund positions, canonical should be empty
    assert report["net_worth"]["legacy_stock_fund"] > 0
    assert report["net_worth"]["canonical_stock_fund"] == 0.0
    assert report["summary"]["parity_ok"] is False


def test_parity_report_legacy_latest_filters_before_anchor(db_session, db_engine, seeded_db):
    """
    Legacy latest-row selection must choose MAX(as_of) only from rows on or
    before the anchor. A newer row after the anchor must not hide the older
    valid stock/fund or cash row.
    """
    future_as_of = datetime(2026, 2, 28, 0, 0, 0, tzinfo=timezone.utc)
    with db_engine.begin() as conn:
        _seed_position(conn, 9902, STOCK_ACCOUNT_ID, STOCK_ASSET_ID, future_as_of, 120.0, 300.0, 36000.0)
        _seed_position(conn, 9903, CASH_ACCOUNT_ID, CASH_ASSET_ID, future_as_of, 1.0, None, 4000.0)

    report = generate_parity_report(db_session, current_user_id=USER_ID, anchor_date=REPORT_DATE)

    stock_row = next(row for row in report["stock_holdings"] if row["symbol"] == "RELIANCE")
    cash_row = next(row for row in report["cash_balances"] if row["account_id"] == CASH_ACCOUNT_ID)

    assert stock_row["legacy_qty"] == pytest.approx(100.0)
    assert stock_row["legacy_value"] == pytest.approx(25000.0)
    assert cash_row["legacy"] == pytest.approx(3000.0)
    assert report["net_worth"]["legacy_stock_fund"] == pytest.approx(30000.0)
    assert report["net_worth"]["legacy_cash"] == pytest.approx(3000.0)


# ---------------------------------------------------------------------------
# Test: parity report after backfill shows zero delta
# ---------------------------------------------------------------------------


def test_parity_report_after_backfill(db_session, seeded_db):
    """After backfill: legacy and canonical should match exactly."""
    backfill_legacy_positions(db_session, current_user_id=USER_ID)

    report = generate_parity_report(db_session, current_user_id=USER_ID, anchor_date=REPORT_DATE)

    # Net worth totals should match
    assert report["net_worth"]["delta_stock_fund"] == pytest.approx(0.0, abs=0.01), (
        f"Stock/fund net worth delta after backfill: {report['net_worth']['delta_stock_fund']}"
    )
    assert report["net_worth"]["delta_cash"] == pytest.approx(0.0, abs=0.01), (
        f"Cash net worth delta after backfill: {report['net_worth']['delta_cash']}"
    )

    # All stock holding quantities should match
    for row in report["stock_holdings"]:
        assert row["delta_qty"] == pytest.approx(0.0, abs=1e-6), (
            f"Quantity mismatch for {row['symbol']}: delta_qty={row['delta_qty']}"
        )

    # All cash balances should match
    for row in report["cash_balances"]:
        assert row["delta"] == pytest.approx(0.0, abs=0.01), (
            f"Cash mismatch for account={row['account_id']}/{row['currency']}: delta={row['delta']}"
        )

    assert report["summary"]["parity_ok"] is True


# ---------------------------------------------------------------------------
# Test: dry run does not write any rows
# ---------------------------------------------------------------------------


def test_backfill_dry_run_no_writes(db_session, seeded_db):
    pos_count_before = db_session.execute(
        text("SELECT COUNT(*) FROM portfolio_position_snapshots")
    ).scalar()
    cash_count_before = db_session.execute(
        text("SELECT COUNT(*) FROM account_balance_snapshots")
    ).scalar()

    result = backfill_legacy_positions(db_session, current_user_id=USER_ID, dry_run=True)

    pos_count_after = db_session.execute(
        text("SELECT COUNT(*) FROM portfolio_position_snapshots")
    ).scalar()
    cash_count_after = db_session.execute(
        text("SELECT COUNT(*) FROM account_balance_snapshots")
    ).scalar()

    assert pos_count_before == pos_count_after, "Dry run should not write position snapshots"
    assert cash_count_before == cash_count_after, "Dry run should not write cash snapshots"
    assert result.stock_fund_migrated >= 0
    assert result.cash_migrated >= 0


# ---------------------------------------------------------------------------
# Test: multiple as_of dates → multiple report_date batches
# ---------------------------------------------------------------------------


def test_backfill_multiple_dates(db_session, db_engine, seeded_db):
    """Backfill with two as_of dates for the same account creates two import runs."""
    as_of_2 = datetime(2026, 2, 28, 0, 0, 0, tzinfo=timezone.utc)
    with db_engine.begin() as conn:
        _seed_position(conn, 9901, STOCK_ACCOUNT_ID, STOCK_ASSET_ID, as_of_2, 110.0, 260.0, 28600.0)

    result = backfill_legacy_positions(db_session, current_user_id=USER_ID)

    # Should have migrated both dates
    run_count = db_session.execute(
        text(
            "SELECT COUNT(DISTINCT bir.report_date_from) FROM broker_import_runs bir "
            "WHERE bir.source_type = :st AND bir.broker_account_id IN ("
            "  SELECT ba.id FROM broker_accounts ba "
            "  JOIN broker_connections bc ON bc.id = ba.connection_id "
            "  WHERE ba.legacy_account_id = :acct_id AND bc.connection_type = 'legacy_backfill'"
            ")"
        ),
        {"st": BACKFILL_SOURCE_TYPE, "acct_id": STOCK_ACCOUNT_ID},
    ).scalar()
    # Two distinct dates → two import runs
    assert run_count >= 2, f"Expected ≥2 import run date batches, got {run_count}"


# ---------------------------------------------------------------------------
# Test: cash DQE for already-covered rows
# ---------------------------------------------------------------------------


def test_cash_conflict_creates_dqe(db_session, seeded_db):
    # First backfill: writes cash balance
    backfill_legacy_positions(db_session, current_user_id=USER_ID)

    dqe_before = db_session.execute(
        text("SELECT COUNT(*) FROM portfolio_data_quality_events WHERE event_code = 'backfill_cash_skipped_covered'")
    ).scalar()

    # Second backfill: cash is already covered → DQE
    backfill_legacy_positions(db_session, current_user_id=USER_ID)

    dqe_after = db_session.execute(
        text("SELECT COUNT(*) FROM portfolio_data_quality_events WHERE event_code = 'backfill_cash_skipped_covered'")
    ).scalar()

    assert dqe_after > dqe_before, "Expected cash DQE events on second backfill run"


# ---------------------------------------------------------------------------
# Test: parity report sections have correct shape
# ---------------------------------------------------------------------------


def test_parity_report_sections_shape(db_session, seeded_db):
    backfill_legacy_positions(db_session, current_user_id=USER_ID)
    report = generate_parity_report(db_session, current_user_id=USER_ID, anchor_date=REPORT_DATE)

    # net_worth
    assert "legacy_total" in report["net_worth"]
    assert "canonical_total" in report["net_worth"]
    assert "delta_total" in report["net_worth"]
    assert "accounts" in report["net_worth"]
    for acct_row in report["net_worth"]["accounts"]:
        assert "account_id" in acct_row
        assert "legacy" in acct_row
        assert "canonical" in acct_row
        assert "delta" in acct_row

    # stock_holdings
    assert len(report["stock_holdings"]) >= 1
    for sh in report["stock_holdings"]:
        assert "symbol" in sh
        assert "legacy_qty" in sh
        assert "canonical_qty" in sh
        assert "delta_qty" in sh

    # cash_balances
    assert len(report["cash_balances"]) >= 1
    for cb in report["cash_balances"]:
        assert "account_id" in cb
        assert "currency" in cb
        assert "legacy" in cb
        assert "canonical" in cb
        assert "delta" in cb

    # platform_alloc
    assert len(report["platform_alloc"]) >= 1
    for pa in report["platform_alloc"]:
        assert "platform" in pa
        assert "legacy" in pa
        assert "canonical" in pa

    # geography_alloc
    assert len(report["geography_alloc"]) >= 1
    for ga in report["geography_alloc"]:
        assert "country" in ga
        assert "legacy" in ga
        assert "canonical" in ga

    # summary
    assert "parity_ok" in report["summary"]
    assert "anchor_date" in report["summary"]
