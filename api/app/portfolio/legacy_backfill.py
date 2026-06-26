"""
Legacy position backfill service (Phase 6).

Migrates existing legacy ``positions`` rows into canonical portfolio tables
without deleting the legacy table.

Design rules:
- ``positions`` rows with asset_class IN ('STOCK', 'FUND') → ``portfolio_position_snapshots``.
- ``positions`` rows with asset_class = 'CASH' → ``account_balance_snapshots``.
- All migrated facts carry source_kind = 'legacy_positions_backfill'.
- If an authoritative canonical fact already exists for the same
  account/date/security, the backfill writes a data-quality event and
  skips (does NOT overwrite).
- The backfill is idempotent: running it twice produces the same rows and
  does not change totals.
- Synthetic lineage is created as broker_connection / broker_account /
  broker_import_run per (account, as_of_date) batch so migrated facts are
  auditable.

Usage (as a module script)::

    python -m app.portfolio.legacy_backfill [--dry-run] [--user-id N]

Usage from Python::

    from app.portfolio.legacy_backfill import backfill_legacy_positions
    result = backfill_legacy_positions(db, current_user_id=1)
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import account_scope_sql
from app.fx import get_rates

logger = logging.getLogger(__name__)

BACKFILL_VERSION = "legacy_backfill_v1"
BACKFILL_PLATFORM_CODE = "LEGACY_BACKFILL"
BACKFILL_SOURCE_TYPE = "legacy_positions_backfill"
BACKFILL_CONNECTION_TYPE = "legacy_backfill"
BACKFILL_SOURCE_KIND = "legacy_positions_backfill"

# Asset classes that map to portfolio_position_snapshots
_POSITION_ASSET_CLASSES = ("STOCK", "FUND")
# Asset class that maps to account_balance_snapshots
_CASH_ASSET_CLASS = "CASH"


@dataclass
class BackfillResult:
    stock_fund_migrated: int = 0
    stock_fund_skipped_covered: int = 0
    stock_fund_skipped_no_account: int = 0
    stock_fund_skipped_unmapped_asset: int = 0
    cash_migrated: int = 0
    cash_skipped_covered: int = 0
    cash_skipped_no_account: int = 0
    cash_skipped_unmapped_asset: int = 0
    data_quality_events_written: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_migrated(self) -> int:
        return self.stock_fund_migrated + self.cash_migrated

    @property
    def total_skipped(self) -> int:
        return (
            self.stock_fund_skipped_covered
            + self.stock_fund_skipped_no_account
            + self.stock_fund_skipped_unmapped_asset
            + self.cash_skipped_covered
            + self.cash_skipped_no_account
            + self.cash_skipped_unmapped_asset
        )


def _now() -> datetime:
    return datetime.now(tz=timezone.utc).replace(microsecond=0)


def _db_decimal(value: float | Decimal | None) -> str | None:
    if value is None:
        return None
    return str(Decimal(str(value)))


def _json_default(db: Session) -> str:
    dialect = getattr(getattr(getattr(db, "bind", None), "dialect", None), "name", "sqlite")
    return "'{}'::jsonb" if dialect == "postgresql" else "'{}'"


def _historical_fx_rate(*, report_date: date, base_currency: str, quote_currency: str) -> float:
    base = str(base_currency).upper()
    quote = str(quote_currency).upper()
    if not quote or quote == base:
        return 1.0
    rates = get_rates(datetime(report_date.year, report_date.month, report_date.day, tzinfo=timezone.utc), base, {quote})
    return float(rates.get(quote, 1.0))


# ---------------------------------------------------------------------------
# Lineage helpers
# ---------------------------------------------------------------------------


def _ensure_backfill_broker_connection(db: Session, *, user_id: int, platform_code: str) -> int:
    """Ensure a 'legacy_backfill' broker connection for this user/platform."""
    row = db.execute(
        text(
            """
            SELECT id FROM broker_connections
            WHERE user_id = :user_id
              AND platform_code = :platform_code
              AND connection_type = :connection_type
              AND status = 'active'
            ORDER BY id LIMIT 1
            """
        ),
        {"user_id": user_id, "platform_code": platform_code, "connection_type": BACKFILL_CONNECTION_TYPE},
    ).fetchone()
    if row:
        return int(row[0])

    db.execute(
        text(
            f"""
            INSERT INTO broker_connections
              (user_id, platform_code, connection_type, display_name, status, metadata_json)
            VALUES
              (:user_id, :platform_code, :connection_type, :display_name, 'active', {_json_default(db)})
            """
        ),
        {
            "user_id": user_id,
            "platform_code": platform_code,
            "connection_type": BACKFILL_CONNECTION_TYPE,
            "display_name": f"{platform_code} Legacy Backfill",
        },
    )
    row = db.execute(
        text(
            """
            SELECT id FROM broker_connections
            WHERE user_id = :user_id
              AND platform_code = :platform_code
              AND connection_type = :connection_type
            ORDER BY id DESC LIMIT 1
            """
        ),
        {"user_id": user_id, "platform_code": platform_code, "connection_type": BACKFILL_CONNECTION_TYPE},
    ).fetchone()
    return int(row[0])


def _ensure_backfill_broker_account(
    db: Session,
    *,
    connection_id: int,
    legacy_account_id: int,
    base_currency: str,
) -> int:
    """Ensure a synthetic broker_account for the backfill connection."""
    backfill_account_key = f"backfill_{legacy_account_id}"
    row = db.execute(
        text(
            """
            SELECT id FROM broker_accounts
            WHERE connection_id = :connection_id
              AND broker_account_id = :broker_account_id
            LIMIT 1
            """
        ),
        {"connection_id": connection_id, "broker_account_id": backfill_account_key},
    ).fetchone()
    if row:
        return int(row[0])

    db.execute(
        text(
            f"""
            INSERT INTO broker_accounts
              (connection_id, legacy_account_id, broker_account_id, base_currency, status, metadata_json)
            VALUES
              (:connection_id, :legacy_account_id, :broker_account_id, :base_currency, 'active', {_json_default(db)})
            """
        ),
        {
            "connection_id": connection_id,
            "legacy_account_id": legacy_account_id,
            "broker_account_id": backfill_account_key,
            "base_currency": base_currency,
        },
    )
    row = db.execute(
        text(
            """
            SELECT id FROM broker_accounts
            WHERE connection_id = :connection_id
              AND broker_account_id = :broker_account_id
            LIMIT 1
            """
        ),
        {"connection_id": connection_id, "broker_account_id": backfill_account_key},
    ).fetchone()
    return int(row[0])


def _ensure_backfill_import_run(
    db: Session,
    *,
    broker_account_id: int,
    legacy_account_id: int,
    platform_code: str,
    report_date: date,
) -> int:
    """Return an existing or new synthetic import run for this account/date batch."""
    row = db.execute(
        text(
            """
            SELECT id FROM broker_import_runs
            WHERE broker_account_id = :broker_account_id
              AND source_type = :source_type
              AND report_date_from = :report_date
            ORDER BY id DESC LIMIT 1
            """
        ),
        {
            "broker_account_id": broker_account_id,
            "source_type": BACKFILL_SOURCE_TYPE,
            "report_date": report_date,
        },
    ).fetchone()
    if row:
        return int(row[0])

    db.execute(
        text(
            f"""
            INSERT INTO broker_import_runs
              (broker_account_id, legacy_account_id, platform_code, source_type, import_scope,
               status, started_at, report_date_from, report_date_to, parser_version, metadata_json)
            VALUES
              (:broker_account_id, :legacy_account_id, :platform_code, :source_type, 'backfill',
               'completed', :started_at, :report_date, :report_date, :parser_version, {_json_default(db)})
            """
        ),
        {
            "broker_account_id": broker_account_id,
            "legacy_account_id": legacy_account_id,
            "platform_code": platform_code,
            "source_type": BACKFILL_SOURCE_TYPE,
            "started_at": _now(),
            "report_date": report_date,
            "parser_version": BACKFILL_VERSION,
        },
    )
    row = db.execute(
        text(
            """
            SELECT id FROM broker_import_runs
            WHERE broker_account_id = :broker_account_id
              AND source_type = :source_type
              AND report_date_from = :report_date
            ORDER BY id DESC LIMIT 1
            """
        ),
        {
            "broker_account_id": broker_account_id,
            "source_type": BACKFILL_SOURCE_TYPE,
            "report_date": report_date,
        },
    ).fetchone()
    return int(row[0])


def _ensure_backfill_broker_instrument(
    db: Session,
    *,
    asset_id: int,
    symbol: str,
    currency: str,
    description: str | None,
    security_type: str | None,
) -> int:
    """Upsert a broker_instrument linked to an existing asset for backfill."""
    # Prefer finding an existing instrument linked to this asset_id.
    row = db.execute(
        text(
            """
            SELECT id FROM broker_instruments
            WHERE platform_code = :platform_code
              AND asset_id = :asset_id
              AND COALESCE(currency, '') = :currency
            LIMIT 1
            """
        ),
        {
            "platform_code": BACKFILL_PLATFORM_CODE,
            "asset_id": asset_id,
            "currency": currency.upper(),
        },
    ).fetchone()
    if row:
        return int(row[0])

    synthetic_id = f"backfill_{symbol.upper()}_{currency.upper()}"
    db.execute(
        text(
            f"""
            INSERT INTO broker_instruments
              (platform_code, broker_instrument_id, asset_id, symbol, description,
               security_type, currency, metadata_json)
            VALUES
              (:platform_code, :broker_instrument_id, :asset_id, :symbol, :description,
               :security_type, :currency, {_json_default(db)})
            """
        ),
        {
            "platform_code": BACKFILL_PLATFORM_CODE,
            "broker_instrument_id": synthetic_id,
            "asset_id": asset_id,
            "symbol": symbol,
            "description": description,
            "security_type": security_type,
            "currency": currency.upper(),
        },
    )
    row = db.execute(
        text(
            """
            SELECT id FROM broker_instruments
            WHERE platform_code = :platform_code
              AND asset_id = :asset_id
              AND COALESCE(currency, '') = :currency
            LIMIT 1
            """
        ),
        {
            "platform_code": BACKFILL_PLATFORM_CODE,
            "asset_id": asset_id,
            "currency": currency.upper(),
        },
    ).fetchone()
    return int(row[0])


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


def _position_has_authoritative_snapshot(
    db: Session,
    *,
    legacy_account_id: int,
    report_date: date,
    asset_id: int,
    symbol: str,
    currency: str,
) -> bool:
    """
    Return True if this exact account/date/security already has an
    authoritative canonical position snapshot.

    Backfill must not treat one covered security as account-wide coverage;
    partial canonical coverage is expected during migration.
    """
    row = db.execute(
        text(
            """
            SELECT 1 FROM portfolio_position_snapshots pps
            JOIN broker_accounts ba ON ba.id = pps.broker_account_id
            JOIN broker_instruments bi ON bi.id = pps.broker_instrument_id
            WHERE ba.legacy_account_id = :legacy_account_id
              AND pps.report_date = :report_date
              AND pps.authority_status = 'authoritative'
              AND UPPER(pps.currency) = :currency
              AND (
                bi.asset_id = :asset_id
                OR (
                  bi.asset_id IS NULL
                  AND UPPER(bi.symbol) = :symbol
                  AND UPPER(COALESCE(bi.currency, '')) = :currency
                )
              )
            LIMIT 1
            """
        ),
        {
            "legacy_account_id": legacy_account_id,
            "report_date": report_date,
            "asset_id": asset_id,
            "symbol": symbol.upper(),
            "currency": currency.upper(),
        },
    ).fetchone()
    return row is not None


def _account_date_has_authoritative_cash(
    db: Session,
    *,
    legacy_account_id: int,
    as_of_date: date,
    currency: str,
) -> bool:
    """
    Return True if any authoritative cash balance row already exists for
    this account/date/currency in account_balance_snapshots.
    """
    row = db.execute(
        text(
            """
            SELECT 1 FROM account_balance_snapshots
            WHERE account_id = :account_id
              AND as_of_date = :as_of_date
              AND currency = :currency
              AND authority_status = 'authoritative'
            LIMIT 1
            """
        ),
        {"account_id": legacy_account_id, "as_of_date": as_of_date, "currency": currency},
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Data quality events
# ---------------------------------------------------------------------------


def _record_dqe(
    db: Session,
    *,
    broker_account_id: int | None,
    import_run_id: int | None,
    report_date: date | None,
    severity: str,
    event_code: str,
    message: str,
) -> None:
    db.execute(
        text(
            f"""
            INSERT INTO portfolio_data_quality_events
              (broker_account_id, import_run_id, report_date, severity, event_code, message, metadata_json)
            VALUES
              (:broker_account_id, :import_run_id, :report_date, :severity, :event_code, :message, {_json_default(db)})
            """
        ),
        {
            "broker_account_id": broker_account_id,
            "import_run_id": import_run_id,
            "report_date": report_date,
            "severity": severity,
            "event_code": event_code,
            "message": message,
        },
    )


def _record_unmappable_legacy_positions(
    db: Session,
    *,
    current_user_id: int,
    dry_run: bool,
) -> tuple[int, int, int, int, int]:
    """
    Record data-quality events for legacy rows that cannot enter the canonical
    backfill because the account or asset identity is missing.

    Returns (stock_fund_no_account, cash_no_account, stock_fund_unmapped_asset,
    cash_unmapped_asset, dqe_written).
    """
    stock_fund_no_account = 0
    cash_no_account = 0
    stock_fund_unmapped_asset = 0
    cash_unmapped_asset = 0

    rows = db.execute(
        text(
            """
            SELECT
              p.id AS pos_id,
              p.account_id,
              p.asset_id,
              p.as_of,
              a.id AS resolved_asset_id,
              a.asset_class,
              acc.id AS resolved_account_id
            FROM positions p
            LEFT JOIN assets a ON a.id = p.asset_id
            LEFT JOIN accounts acc ON acc.id = p.account_id
            WHERE acc.id IS NULL
               OR (a.id IS NULL AND ("""
            + account_scope_sql("acc")
            + """))
            ORDER BY p.id
            """
        ),
        {"current_user_id": current_user_id},
    ).mappings().all()

    dqe_written = 0
    for row in rows:
        as_of_date: date = (
            row["as_of"].date() if hasattr(row["as_of"], "date") else date.fromisoformat(str(row["as_of"])[:10])
        )
        asset_class = str(row["asset_class"] or "UNKNOWN").upper()
        is_cash = asset_class == _CASH_ASSET_CLASS
        if row["resolved_account_id"] is None:
            if is_cash:
                cash_no_account += 1
            else:
                stock_fund_no_account += 1
            if not dry_run:
                _record_dqe(
                    db,
                    broker_account_id=None,
                    import_run_id=None,
                    report_date=as_of_date,
                    severity="error",
                    event_code="backfill_missing_account_mapping",
                    message=(
                        f"Legacy position id={row['pos_id']} account={row['account_id']} "
                        "has no matching accounts row; skipped."
                    ),
                )
                dqe_written += 1
            continue

        if row["resolved_asset_id"] is None:
            if is_cash:
                cash_unmapped_asset += 1
            else:
                stock_fund_unmapped_asset += 1
            if not dry_run:
                _record_dqe(
                    db,
                    broker_account_id=None,
                    import_run_id=None,
                    report_date=as_of_date,
                    severity="error",
                    event_code="backfill_unmapped_asset",
                    message=(
                        f"Legacy position id={row['pos_id']} asset={row['asset_id']} "
                        "has no matching assets row; skipped."
                    ),
                )
                dqe_written += 1

    return stock_fund_no_account, cash_no_account, stock_fund_unmapped_asset, cash_unmapped_asset, dqe_written


# ---------------------------------------------------------------------------
# Stock/fund backfill
# ---------------------------------------------------------------------------


def _backfill_stock_fund_positions(
    db: Session,
    *,
    current_user_id: int,
    dry_run: bool = False,
) -> tuple[int, int, int, int, int]:
    """
    Migrate legacy stock/fund positions to portfolio_position_snapshots.

    Returns (migrated, skipped_covered, skipped_no_account, dqe_written).
    """
    migrated = 0
    skipped_covered = 0
    skipped_no_account = 0
    dqe_written = 0

    rows = db.execute(
        text(
            """
            SELECT
              p.id           AS pos_id,
              p.account_id,
              p.asset_id,
              p.as_of,
              p.quantity,
              p.avg_cost,
              p.cost_basis_base,
              a.symbol,
              a.name         AS asset_name,
              a.asset_class,
              a.quote_currency,
              a.home_country,
              acc.platform,
              acc.currency   AS account_currency,
              acc.user_id
            FROM positions p
            JOIN assets a ON a.id = p.asset_id
            JOIN accounts acc ON acc.id = p.account_id
            WHERE a.asset_class IN ('STOCK', 'FUND')
              AND ("""
            + account_scope_sql("acc")
            + """)
            ORDER BY p.account_id, p.as_of
            """
        ),
        {"current_user_id": current_user_id},
    ).mappings().all()

    # Process each row
    for row in rows:
        pos_id = row["pos_id"]
        account_id = int(row["account_id"])
        asset_id = int(row["asset_id"])
        report_date: date = (
            row["as_of"].date() if hasattr(row["as_of"], "date") else date.fromisoformat(str(row["as_of"])[:10])
        )
        symbol = str(row["symbol"])
        currency = str(row["quote_currency"] or "XXX").upper()
        platform = str(row["platform"] or BACKFILL_PLATFORM_CODE).upper()
        account_currency = str(row["account_currency"] or currency).upper()
        user_id = current_user_id
        fx_rate_to_base = _historical_fx_rate(
            report_date=report_date,
            base_currency=account_currency,
            quote_currency=currency,
        )

        # Check for pre-existing authoritative coverage for this exact security.
        if _position_has_authoritative_snapshot(
            db,
            legacy_account_id=account_id,
            report_date=report_date,
            asset_id=asset_id,
            symbol=symbol,
            currency=currency,
        ):
            skipped_covered += 1
            if not dry_run:
                _record_dqe(
                    db,
                    broker_account_id=None,
                    import_run_id=None,
                    report_date=report_date,
                    severity="info",
                    event_code="backfill_skipped_covered",
                    message=(
                        f"Legacy position id={pos_id} account={account_id} symbol={symbol} "
                        f"report_date={report_date} already covered by authoritative canonical snapshot; skipped."
                    ),
                )
                dqe_written += 1
            continue

        if dry_run:
            migrated += 1
            continue

        # Ensure lineage objects
        conn_id = _ensure_backfill_broker_connection(db, user_id=user_id, platform_code=platform)
        ba_id = _ensure_backfill_broker_account(
            db, connection_id=conn_id, legacy_account_id=account_id, base_currency=account_currency
        )
        run_id = _ensure_backfill_import_run(
            db,
            broker_account_id=ba_id,
            legacy_account_id=account_id,
            platform_code=platform,
            report_date=report_date,
        )
        instr_id = _ensure_backfill_broker_instrument(
            db,
            asset_id=asset_id,
            symbol=symbol,
            currency=currency,
            description=row["asset_name"],
            security_type=str(row["asset_class"]),
        )

        cost_basis_base = row["cost_basis_base"]
        quantity = row["quantity"]
        avg_cost = row["avg_cost"]
        market_value_local = float(cost_basis_base) / fx_rate_to_base if fx_rate_to_base else float(cost_basis_base)
        market_price = market_value_local / float(quantity) if quantity else avg_cost

        db.execute(
            text(
                f"""
                INSERT INTO portfolio_position_snapshots
                  (broker_account_id, legacy_account_id, broker_instrument_id, import_run_id,
                   report_date, quantity, currency, market_price,
                   market_value_local, market_value_base,
                   cost_basis_local, cost_basis_base,
                   fx_rate_to_base, authority_status, metadata_json)
                VALUES
                  (:broker_account_id, :legacy_account_id, :broker_instrument_id, :import_run_id,
                   :report_date, :quantity, :currency, :market_price,
                   :market_value_local, :market_value_base,
                   :cost_basis_local, :cost_basis_base,
                   :fx_rate_to_base, 'authoritative', {_json_default(db)})
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "broker_account_id": ba_id,
                "legacy_account_id": account_id,
                "broker_instrument_id": instr_id,
                "import_run_id": run_id,
                "report_date": report_date,
                "quantity": _db_decimal(quantity),
                "currency": currency,
                "market_price": _db_decimal(market_price),
                "market_value_local": _db_decimal(market_value_local),
                "market_value_base": _db_decimal(cost_basis_base),
                "cost_basis_local": _db_decimal(market_value_local),
                "cost_basis_base": _db_decimal(cost_basis_base),
                "fx_rate_to_base": _db_decimal(fx_rate_to_base),
            },
        )
        migrated += 1

    return migrated, skipped_covered, skipped_no_account, dqe_written


# ---------------------------------------------------------------------------
# Cash backfill
# ---------------------------------------------------------------------------


def _backfill_cash_positions(
    db: Session,
    *,
    current_user_id: int,
    dry_run: bool = False,
) -> tuple[int, int, int, int]:
    """
    Migrate legacy CASH positions to account_balance_snapshots.

    Returns (migrated, skipped_covered, skipped_no_account, dqe_written).
    """
    migrated = 0
    skipped_covered = 0
    skipped_no_account = 0
    dqe_written = 0

    rows = db.execute(
        text(
            """
            SELECT
              p.id           AS pos_id,
              p.account_id,
              p.asset_id,
              p.as_of,
              p.cost_basis_base,
              a.quote_currency,
                            acc.currency   AS account_currency,
              acc.user_id
            FROM positions p
            JOIN assets a ON a.id = p.asset_id
            JOIN accounts acc ON acc.id = p.account_id
            WHERE a.asset_class = 'CASH'
              AND ("""
            + account_scope_sql("acc")
            + """)
            ORDER BY p.account_id, p.as_of
            """
        ),
        {"current_user_id": current_user_id},
    ).mappings().all()

    for row in rows:
        pos_id = row["pos_id"]
        account_id = int(row["account_id"])
        as_of_date: date = (
            row["as_of"].date() if hasattr(row["as_of"], "date") else date.fromisoformat(str(row["as_of"])[:10])
        )
        currency = str(row["quote_currency"] or "XXX").upper()
        balance = row["cost_basis_base"]
        account_currency = str(row["account_currency"] or currency).upper()
        fx_rate_to_base = _historical_fx_rate(
            report_date=as_of_date,
            base_currency=account_currency,
            quote_currency=currency,
        )
        balance_local = float(balance) / fx_rate_to_base if fx_rate_to_base else float(balance)

        # Check for pre-existing authoritative cash row
        if _account_date_has_authoritative_cash(
            db, legacy_account_id=account_id, as_of_date=as_of_date, currency=currency
        ):
            skipped_covered += 1
            if not dry_run:
                _record_dqe(
                    db,
                    broker_account_id=None,
                    import_run_id=None,
                    report_date=as_of_date,
                    severity="info",
                    event_code="backfill_cash_skipped_covered",
                    message=(
                        f"Legacy cash position id={pos_id} account={account_id} currency={currency} "
                        f"as_of={as_of_date} already covered by authoritative canonical balance; skipped."
                    ),
                )
                dqe_written += 1
            continue

        if dry_run:
            migrated += 1
            continue

        db.execute(
            text(
                f"""
                INSERT INTO account_balance_snapshots
                  (account_id, as_of_date, currency, balance_type,
                   balance_local, balance_base, fx_rate_to_base,
                   authority_status, source_kind, metadata_json)
                VALUES
                  (:account_id, :as_of_date, :currency, 'cash',
                         :balance_local, :balance_base, :fx_rate_to_base,
                   'authoritative', :source_kind, {_json_default(db)})
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "account_id": account_id,
                "as_of_date": as_of_date,
                "currency": currency,
                "balance_local": _db_decimal(balance_local),
                "balance_base": _db_decimal(balance),
                "fx_rate_to_base": _db_decimal(fx_rate_to_base),
                "source_kind": BACKFILL_SOURCE_KIND,
            },
        )
        migrated += 1

    return migrated, skipped_covered, skipped_no_account, dqe_written


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def backfill_legacy_positions(
    db: Session,
    *,
    current_user_id: int,
    dry_run: bool = False,
) -> BackfillResult:
    """
    Migrate eligible legacy ``positions`` rows into canonical tables.

    Parameters
    ----------
    db:
        Active SQLAlchemy session.
    current_user_id:
        User whose accounts are in scope.  Pass 0 with AUTH_ALLOW_LEGACY_NULL_OWNERSHIP=1
        to cover accounts with no user_id.
    dry_run:
        If True, count eligible rows without writing any rows.

    Returns
    -------
    BackfillResult
        Counts of rows migrated, skipped, and data-quality events written.
    """
    result = BackfillResult()

    sf_missing_acc, cash_missing_acc, sf_missing_asset, cash_missing_asset, preflight_dqe = (
        _record_unmappable_legacy_positions(db, current_user_id=current_user_id, dry_run=dry_run)
    )
    result.stock_fund_skipped_no_account += sf_missing_acc
    result.cash_skipped_no_account += cash_missing_acc
    result.stock_fund_skipped_unmapped_asset += sf_missing_asset
    result.cash_skipped_unmapped_asset += cash_missing_asset
    result.data_quality_events_written += preflight_dqe

    sf_migrated, sf_skipped_cov, sf_skipped_acc, sf_dqe = _backfill_stock_fund_positions(
        db, current_user_id=current_user_id, dry_run=dry_run
    )
    result.stock_fund_migrated = sf_migrated
    result.stock_fund_skipped_covered = sf_skipped_cov
    result.stock_fund_skipped_no_account += sf_skipped_acc
    result.data_quality_events_written += sf_dqe

    c_migrated, c_skipped_cov, c_skipped_acc, c_dqe = _backfill_cash_positions(
        db, current_user_id=current_user_id, dry_run=dry_run
    )
    result.cash_migrated = c_migrated
    result.cash_skipped_covered = c_skipped_cov
    result.cash_skipped_no_account += c_skipped_acc
    result.data_quality_events_written += c_dqe

    if not dry_run:
        db.commit()

    logger.info(
        "Legacy backfill complete: migrated=%d skipped=%d dqe=%d dry_run=%s",
        result.total_migrated,
        result.total_skipped,
        result.data_quality_events_written,
        dry_run,
    )
    return result


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def _cli() -> None:  # pragma: no cover
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    parser = argparse.ArgumentParser(description="Backfill legacy positions into canonical tables.")
    parser.add_argument("--dry-run", action="store_true", help="Count eligible rows without writing.")
    parser.add_argument("--user-id", type=int, default=1, help="User ID to backfill (default: 1).")
    args = parser.parse_args()

    from app.db.session import SessionLocal

    with SessionLocal() as session:
        result = backfill_legacy_positions(session, current_user_id=args.user_id, dry_run=args.dry_run)
        print(f"stock_fund_migrated={result.stock_fund_migrated}")
        print(f"stock_fund_skipped_covered={result.stock_fund_skipped_covered}")
        print(f"cash_migrated={result.cash_migrated}")
        print(f"cash_skipped_covered={result.cash_skipped_covered}")
        print(f"data_quality_events_written={result.data_quality_events_written}")
        print(f"dry_run={args.dry_run}")


if __name__ == "__main__":
    _cli()
