"""
Phase 4: Canonical account balance snapshot tests.

Verifies:
- account_balance_snapshots table enforces natural-key uniqueness for
  authoritative rows (account_id, as_of_date, currency, balance_type).
- Idempotent upsert: inserting the same row twice raises an integrity error;
  the canonical write pattern should use INSERT OR IGNORE / ON CONFLICT.
- FX and base-value semantics: balance_base = balance_local * fx_rate_to_base.
- source authority: only 'authoritative' rows are returned by
  canonical_account_balance_rows().
- Account scoping: rows for a different user's account are not returned.
- Broker cash promotion: portfolio_cash_balance_snapshots rows ARE surfaced
  through canonical_account_balance_rows() for accounts that have no
  account_balance_snapshots entry; they are NOT surfaced when the account already
  has a canonical account_balance_snapshots row (no double-counting).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.portfolio.canonical_reads import canonical_account_balance_rows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts():
    return datetime.now(tz=timezone.utc).replace(microsecond=0)


def _seed_user(conn, user_id: int) -> None:
    conn.exec_driver_sql(
        "INSERT OR IGNORE INTO users (id, username, display_name, is_active, is_admin) "
        "VALUES (?, 'user_'||?, 'User '||?, 1, 0)",
        (user_id, user_id, user_id),
    )


def _seed_account(conn, account_id: int, name: str, user_id: int, currency: str = "USD") -> None:
    conn.exec_driver_sql(
        "INSERT OR IGNORE INTO accounts (id, name, platform, user_id, account_type, currency) "
        "VALUES (?, ?, 'TEST', ?, 'BANK', ?)",
        (account_id, name, user_id, currency),
    )


def _seed_broker_connection(conn, conn_id: int, user_id: int) -> None:
    conn.exec_driver_sql(
        "INSERT OR IGNORE INTO broker_connections "
        "(id, user_id, platform_code, connection_type, status) "
        "VALUES (?, ?, 'IBKR', 'flex', 'active')",
        (conn_id, user_id),
    )


def _seed_broker_account(conn, ba_id: int, conn_id: int, legacy_account_id: int) -> None:
    conn.exec_driver_sql(
        "INSERT OR IGNORE INTO broker_accounts "
        "(id, connection_id, legacy_account_id, broker_account_id, base_currency) "
        "VALUES (?, ?, ?, 'U12345', 'USD')",
        (ba_id, conn_id, legacy_account_id),
    )


def _seed_import_run(conn, run_id: int, ba_id: int) -> None:
    conn.exec_driver_sql(
        "INSERT OR IGNORE INTO broker_import_runs "
        "(id, broker_account_id, platform_code, source_type, status) "
        "VALUES (?, ?, 'IBKR', 'flex', 'done')",
        (run_id, ba_id),
    )


def _insert_abs(
    conn,
    *,
    account_id: int,
    as_of_date: str,
    currency: str,
    balance_type: str = "cash",
    balance_local: float = 1000.0,
    balance_base: float = 1000.0,
    fx_rate: float = 1.0,
    authority_status: str = "authoritative",
    source_kind: str = "upload_parser",
    broker_account_id: int | None = None,
) -> None:
    conn.exec_driver_sql(
        """
        INSERT INTO account_balance_snapshots
          (account_id, broker_account_id, as_of_date, currency, balance_type,
           balance_local, balance_base, fx_rate_to_base,
           authority_status, source_kind)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            account_id,
            broker_account_id,
            as_of_date,
            currency,
            balance_type,
            str(Decimal(str(balance_local))),
            str(Decimal(str(balance_base))),
            str(Decimal(str(fx_rate))),
            authority_status,
            source_kind,
        ),
    )


def _insert_pcbs(
    conn,
    *,
    broker_account_id: int,
    import_run_id: int,
    report_date: str,
    currency: str,
    cash_balance: float,
    cash_balance_base: float,
    fx_rate: float = 1.0,
    authority_status: str = "authoritative",
) -> None:
    conn.exec_driver_sql(
        """
        INSERT INTO portfolio_cash_balance_snapshots
          (broker_account_id, import_run_id, report_date, currency,
           cash_balance, cash_balance_base, fx_rate_to_base, authority_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            broker_account_id,
            import_run_id,
            report_date,
            currency,
            str(Decimal(str(cash_balance))),
            str(Decimal(str(cash_balance_base))),
            str(Decimal(str(fx_rate))),
            authority_status,
        ),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

USER_A = 9001
USER_B = 9002
ACCT_A1 = 8001   # belongs to USER_A, has account_balance_snapshots
ACCT_A2 = 8002   # belongs to USER_A, only has portfolio_cash_balance_snapshots
ACCT_B1 = 8003   # belongs to USER_B — must never be visible to USER_A
BROKER_CONN = 7001
BROKER_ACCT = 7002
IMPORT_RUN = 7003


@pytest.fixture()
def db_session(db_engine):
    SessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def seeded(db_engine):
    """Seed minimal accounts, broker wiring, and balance rows for all tests."""
    with db_engine.begin() as conn:
        _seed_user(conn, USER_A)
        _seed_user(conn, USER_B)
        _seed_account(conn, ACCT_A1, "Savings A1", USER_A, "USD")
        _seed_account(conn, ACCT_A2, "Brokerage A2", USER_A, "USD")
        _seed_account(conn, ACCT_B1, "Savings B1", USER_B, "USD")
        _seed_broker_connection(conn, BROKER_CONN, USER_A)
        _seed_broker_account(conn, BROKER_ACCT, BROKER_CONN, ACCT_A2)
        _seed_import_run(conn, IMPORT_RUN, BROKER_ACCT)
    yield


# ---------------------------------------------------------------------------
# Tests: uniqueness / idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    """Natural-key uniqueness for authoritative rows."""

    def test_duplicate_authoritative_row_raises(self, db_engine, seeded):
        """Two authoritative rows with the same natural key must fail."""
        import sqlite3

        with db_engine.begin() as conn:
            _insert_abs(
                conn,
                account_id=ACCT_A1,
                as_of_date="2026-01-31",
                currency="USD",
                balance_type="cash",
                balance_local=5000.0,
                balance_base=5000.0,
            )

        with pytest.raises(Exception):
            with db_engine.begin() as conn:
                _insert_abs(
                    conn,
                    account_id=ACCT_A1,
                    as_of_date="2026-01-31",
                    currency="USD",
                    balance_type="cash",
                    balance_local=6000.0,  # different amount — still same natural key
                    balance_base=6000.0,
                )

    def test_second_authoritative_different_type_allowed(self, db_engine, seeded):
        """Two authoritative rows for the same account/date/currency but different
        balance_type (e.g. cash vs stablecoin_cash) must succeed."""
        with db_engine.begin() as conn:
            _insert_abs(
                conn,
                account_id=ACCT_A1,
                as_of_date="2026-01-31",
                currency="USD",
                balance_type="cash",
                balance_local=5000.0,
                balance_base=5000.0,
            )
            _insert_abs(
                conn,
                account_id=ACCT_A1,
                as_of_date="2026-01-31",
                currency="USD",
                balance_type="stablecoin_cash",
                balance_local=200.0,
                balance_base=200.0,
            )

    def test_superseded_allows_multiple_rows(self, db_engine, seeded):
        """Rows with authority_status = 'superseded' do not trigger uniqueness."""
        with db_engine.begin() as conn:
            _insert_abs(
                conn,
                account_id=ACCT_A1,
                as_of_date="2026-01-31",
                currency="USD",
                balance_type="cash",
                balance_local=4000.0,
                balance_base=4000.0,
                authority_status="superseded",
            )
            _insert_abs(
                conn,
                account_id=ACCT_A1,
                as_of_date="2026-01-31",
                currency="USD",
                balance_type="cash",
                balance_local=4500.0,
                balance_base=4500.0,
                authority_status="superseded",
            )


# ---------------------------------------------------------------------------
# Tests: FX and base-value semantics
# ---------------------------------------------------------------------------

class TestFXValues:
    """FX and base-value round-tripping."""

    def test_fx_rate_preserved_in_read(self, db_engine, db_session, seeded):
        """balance_base should reflect the stored fx_rate_to_base."""
        local = 10_000.0
        fx = 0.74
        base = round(local * fx, 2)

        with db_engine.begin() as conn:
            _insert_abs(
                conn,
                account_id=ACCT_A1,
                as_of_date="2026-02-28",
                currency="SGD",
                balance_type="bank_cash",
                balance_local=local,
                balance_base=base,
                fx_rate=fx,
                source_kind="upload_parser",
            )

        rows = canonical_account_balance_rows(
            db_session,
            current_user_id=USER_A,
            anchor_date=date(2026, 2, 28),
        )
        sgd_rows = [r for r in rows if r["currency"] == "SGD"]
        assert len(sgd_rows) == 1
        assert abs(sgd_rows[0]["balance_local"] - local) < 0.01
        assert abs(sgd_rows[0]["balance_base"] - base) < 0.01
        assert abs(sgd_rows[0]["fx_rate"] - fx) < 0.001

    def test_default_fx_rate_one_for_base_currency(self, db_engine, db_session, seeded):
        """When currency == base currency, fx_rate should default to 1."""
        with db_engine.begin() as conn:
            _insert_abs(
                conn,
                account_id=ACCT_A1,
                as_of_date="2026-02-28",
                currency="USD",
                balance_type="cash",
                balance_local=2500.0,
                balance_base=2500.0,
                fx_rate=1.0,
                source_kind="manual_adjustment",
            )

        rows = canonical_account_balance_rows(
            db_session,
            current_user_id=USER_A,
            anchor_date=date(2026, 2, 28),
        )
        usd_rows = [r for r in rows if r["currency"] == "USD" and r["account_id"] == ACCT_A1]
        assert len(usd_rows) == 1
        assert usd_rows[0]["fx_rate"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Tests: source authority
# ---------------------------------------------------------------------------

class TestSourceAuthority:
    """Only 'authoritative' rows surface through the canonical read abstraction."""

    def test_reference_rows_not_returned(self, db_engine, db_session, seeded):
        with db_engine.begin() as conn:
            _insert_abs(
                conn,
                account_id=ACCT_A1,
                as_of_date="2026-01-31",
                currency="USD",
                balance_type="cash",
                balance_local=1000.0,
                balance_base=1000.0,
                authority_status="reference",
            )

        rows = canonical_account_balance_rows(
            db_session,
            current_user_id=USER_A,
            anchor_date=date(2026, 1, 31),
        )
        assert all(r["authority_status"] == "authoritative" for r in rows), (
            "Non-authoritative rows must not appear in canonical balance reads"
        )

    def test_superseded_rows_not_returned(self, db_engine, db_session, seeded):
        with db_engine.begin() as conn:
            # Insert a superseded row then an authoritative one.
            _insert_abs(
                conn,
                account_id=ACCT_A1,
                as_of_date="2026-01-31",
                currency="USD",
                balance_type="cash",
                balance_local=999.0,
                balance_base=999.0,
                authority_status="superseded",
            )
            _insert_abs(
                conn,
                account_id=ACCT_A1,
                as_of_date="2026-01-31",
                currency="USD",
                balance_type="cash",
                balance_local=1100.0,
                balance_base=1100.0,
                authority_status="authoritative",
            )

        rows = canonical_account_balance_rows(
            db_session,
            current_user_id=USER_A,
            anchor_date=date(2026, 1, 31),
        )
        # Only the authoritative row should appear.
        usd_rows = [
            r for r in rows
            if r["account_id"] == ACCT_A1 and r["currency"] == "USD" and r["balance_type"] == "cash"
        ]
        assert len(usd_rows) == 1
        assert abs(usd_rows[0]["balance_local"] - 1100.0) < 0.01


# ---------------------------------------------------------------------------
# Tests: account scoping
# ---------------------------------------------------------------------------

class TestAccountScoping:
    """Rows from other users' accounts must not appear in the response."""

    def test_user_b_balance_not_visible_to_user_a(self, db_engine, db_session, seeded):
        with db_engine.begin() as conn:
            # USER_B's account
            _insert_abs(
                conn,
                account_id=ACCT_B1,
                as_of_date="2026-01-31",
                currency="USD",
                balance_type="cash",
                balance_local=9999.0,
                balance_base=9999.0,
            )
            # USER_A's account
            _insert_abs(
                conn,
                account_id=ACCT_A1,
                as_of_date="2026-01-31",
                currency="USD",
                balance_type="cash",
                balance_local=100.0,
                balance_base=100.0,
            )

        rows = canonical_account_balance_rows(
            db_session,
            current_user_id=USER_A,
            anchor_date=date(2026, 1, 31),
        )
        account_ids = {r["account_id"] for r in rows}
        assert ACCT_B1 not in account_ids, "User B's balance must not be visible to User A"
        assert ACCT_A1 in account_ids, "User A's own balance must be visible"

    def test_user_a_balance_not_visible_to_user_b(self, db_engine, db_session, seeded):
        with db_engine.begin() as conn:
            _insert_abs(
                conn,
                account_id=ACCT_A1,
                as_of_date="2026-01-31",
                currency="USD",
                balance_type="cash",
                balance_local=500.0,
                balance_base=500.0,
            )

        rows = canonical_account_balance_rows(
            db_session,
            current_user_id=USER_B,
            anchor_date=date(2026, 1, 31),
        )
        account_ids = {r["account_id"] for r in rows}
        assert ACCT_A1 not in account_ids


# ---------------------------------------------------------------------------
# Tests: broker cash promotion (anti-double-count)
# ---------------------------------------------------------------------------

class TestBrokerCashPromotion:
    """
    portfolio_cash_balance_snapshots rows must surface through
    canonical_account_balance_rows() for accounts with no
    account_balance_snapshots entry, and must NOT surface when the account
    already has an account_balance_snapshots entry (anti-double-count).
    """

    def test_pcbs_surfaced_when_no_abs(self, db_engine, db_session, seeded):
        """ACCT_A2 has only a portfolio_cash_balance_snapshots row (via broker)."""
        with db_engine.begin() as conn:
            _insert_pcbs(
                conn,
                broker_account_id=BROKER_ACCT,
                import_run_id=IMPORT_RUN,
                report_date="2026-01-31",
                currency="USD",
                cash_balance=3000.0,
                cash_balance_base=3000.0,
            )

        rows = canonical_account_balance_rows(
            db_session,
            current_user_id=USER_A,
            anchor_date=date(2026, 1, 31),
        )
        acct_rows = [r for r in rows if r["account_id"] == ACCT_A2]
        assert len(acct_rows) >= 1, "PCBS row for ACCT_A2 must be surfaced"
        assert acct_rows[0]["source"] == "portfolio_cash_balance_snapshots"
        assert abs(acct_rows[0]["balance_local"] - 3000.0) < 0.01

    def test_pcbs_not_returned_when_abs_exists(self, db_engine, db_session, seeded):
        """ACCT_A2 has both ABS and PCBS — only ABS must appear (no double-count)."""
        with db_engine.begin() as conn:
            # canonical row
            _insert_abs(
                conn,
                account_id=ACCT_A2,
                as_of_date="2026-01-31",
                currency="USD",
                balance_type="broker_cash",
                balance_local=5000.0,
                balance_base=5000.0,
                broker_account_id=BROKER_ACCT,
                source_kind="flex",
            )
            # legacy broker detail — must be suppressed
            _insert_pcbs(
                conn,
                broker_account_id=BROKER_ACCT,
                import_run_id=IMPORT_RUN,
                report_date="2026-01-31",
                currency="USD",
                cash_balance=5000.0,
                cash_balance_base=5000.0,
            )

        rows = canonical_account_balance_rows(
            db_session,
            current_user_id=USER_A,
            anchor_date=date(2026, 1, 31),
        )
        acct_rows = [r for r in rows if r["account_id"] == ACCT_A2]
        sources = {r["source"] for r in acct_rows}
        assert "portfolio_cash_balance_snapshots" not in sources, (
            "PCBS must not appear when account_balance_snapshots row already exists"
        )
        assert "account_balance_snapshots" in sources

    def test_anchor_date_cutoff_respected(self, db_engine, db_session, seeded):
        """Rows after anchor_date must not appear."""
        with db_engine.begin() as conn:
            _insert_abs(
                conn,
                account_id=ACCT_A1,
                as_of_date="2026-03-01",   # future relative to anchor
                currency="USD",
                balance_type="cash",
                balance_local=9999.0,
                balance_base=9999.0,
            )

        rows = canonical_account_balance_rows(
            db_session,
            current_user_id=USER_A,
            anchor_date=date(2026, 2, 28),  # anchor before the row
        )
        assert not any(r["account_id"] == ACCT_A1 for r in rows)

    def test_multiple_currencies_same_account(self, db_engine, db_session, seeded):
        """Multiple currency rows for the same account must all appear."""
        with db_engine.begin() as conn:
            _insert_abs(
                conn,
                account_id=ACCT_A1,
                as_of_date="2026-01-31",
                currency="USD",
                balance_type="cash",
                balance_local=1000.0,
                balance_base=1000.0,
                fx_rate=1.0,
            )
            _insert_abs(
                conn,
                account_id=ACCT_A1,
                as_of_date="2026-01-31",
                currency="SGD",
                balance_type="cash",
                balance_local=2000.0,
                balance_base=1480.0,
                fx_rate=0.74,
            )

        rows = canonical_account_balance_rows(
            db_session,
            current_user_id=USER_A,
            anchor_date=date(2026, 1, 31),
        )
        a1_currencies = {r["currency"] for r in rows if r["account_id"] == ACCT_A1}
        assert "USD" in a1_currencies
        assert "SGD" in a1_currencies
