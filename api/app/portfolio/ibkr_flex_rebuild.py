"""Restore IBKR position and cash snapshots deleted by multi-day Flex imports (#134).

Until #134 an IBKR Flex import deleted positions and cash balances on every date the
report had NAV for, while a multi-day report only carries positions and cash for its
period end. A long backfill therefore wiped the holdings that earlier daily imports
had stored. Those daily reports are still on disk (raw_broker_documents.storage_path),
so the rows can be rebuilt from them.

For each IBKR broker account this reads the retained Flex XML of every completed
import, newest first, and for each date a report carries positions (or cash) for,
restores that report's rows when the database has none for that date. The newest
report speaking for a date decides it, as the import itself would have.

What it never does: create or move authority windows, touch NAV, FX, report metrics,
reconciliations, the cash ledger, trades or corporate actions, or overwrite a date
that already has rows. Restored rows keep the lineage of the report they come from
(its import_run_id and raw_document_id). The only other writes are upgrading a
'nav_only' completeness row to 'complete' once its holdings are back, and marking
History dirty from the earliest restored date (#169), in the same transaction.
Dry run by default; idempotent (a second run finds nothing to restore).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.portfolio.ibkr_flex import (
    ALL_FACT_SCOPE,
    HOLDINGS_FACT_SCOPE,
    NAV_ONLY_STATUS,
    SOURCE_TYPE,
    FlexCashBalance,
    FlexPosition,
    IbkrFlexImportError,
    _fact_scopes,
    _holdings_completeness_status,
    _insert_cash_balance_snapshot,
    _insert_position_snapshot,
    _now,
    parse_flex_statement,
)
from app.wealth_rollup_dirty import mark_rollups_dirty


@dataclass
class RestoredDate:
    report_date: date
    raw_document_id: int
    import_run_id: int
    positions: int = 0
    cash_balances: int = 0
    completeness_upgraded: bool = False


@dataclass
class AccountRebuildResult:
    broker_account_id: int
    documents_read: int = 0
    documents_missing: int = 0
    documents_rejected: int = 0
    dates: list[RestoredDate] = field(default_factory=list)

    @property
    def positions_restored(self) -> int:
        return sum(item.positions for item in self.dates)

    @property
    def cash_balances_restored(self) -> int:
        return sum(item.cash_balances for item in self.dates)


def _ibkr_broker_accounts(db: Session, broker_account_id: int | None) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT ba.id, ba.broker_account_id AS external_account_id, ba.legacy_account_id
            FROM broker_accounts ba
            JOIN broker_connections bc ON bc.id = ba.connection_id
            WHERE bc.platform_code = 'IBKR'
            ORDER BY ba.id
            """
        )
    ).mappings().all()
    accounts = [dict(row) for row in rows]
    if broker_account_id is not None:
        accounts = [row for row in accounts if int(row["id"]) == broker_account_id]
    return accounts


def _completed_documents(db: Session, broker_account_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT rd.id AS raw_document_id, rd.import_run_id, rd.content_hash, rd.storage_path,
                   run.legacy_account_id
            FROM raw_broker_documents rd
            JOIN broker_import_runs run ON run.id = rd.import_run_id
            WHERE rd.broker_account_id = :broker_account_id
              AND rd.source_type = :source_type
              AND run.status = 'completed'
            ORDER BY rd.id DESC
            """
        ),
        {"broker_account_id": broker_account_id, "source_type": SOURCE_TYPE},
    ).mappings().all()
    return [dict(row) for row in rows]


def _has_rows(db: Session, table_name: str, broker_account_id: int, report_date: date) -> bool:
    row = db.execute(
        text(
            f"SELECT 1 FROM {table_name} "
            "WHERE broker_account_id = :broker_account_id AND report_date = :report_date LIMIT 1"
        ),
        {"broker_account_id": broker_account_id, "report_date": report_date},
    ).fetchone()
    return row is not None


def _restored_authority_status(db: Session, broker_account_id: int, report_date: date) -> str:
    """The status the import gave this date: its NAV row's, else the authority windows'."""
    nav_status = db.execute(
        text(
            """
            SELECT authority_status
            FROM portfolio_nav_snapshots
            WHERE broker_account_id = :broker_account_id AND report_date = :report_date
            ORDER BY CASE WHEN authority_status = 'authoritative' THEN 0 ELSE 1 END, id DESC
            LIMIT 1
            """
        ),
        {"broker_account_id": broker_account_id, "report_date": report_date},
    ).fetchone()
    if nav_status is not None:
        return str(nav_status[0])
    window = db.execute(
        text(
            """
            SELECT 1
            FROM portfolio_source_authority_windows
            WHERE broker_account_id = :broker_account_id
              AND source_kind = :source_kind
              AND fact_scope = :fact_scope
              AND authority_status = 'authoritative'
              AND effective_from <= :report_date
              AND (effective_to IS NULL OR effective_to >= :report_date)
            LIMIT 1
            """
        ),
        {
            "broker_account_id": broker_account_id,
            "source_kind": SOURCE_TYPE,
            "fact_scope": ALL_FACT_SCOPE,
            "report_date": report_date,
        },
    ).fetchone()
    return "authoritative" if window is not None else "reference"


def _nav_stock_base(db: Session, broker_account_id: int, report_date: date) -> Decimal | None:
    row = db.execute(
        text(
            """
            SELECT stock_base FROM portfolio_nav_snapshots
            WHERE broker_account_id = :broker_account_id AND report_date = :report_date
            ORDER BY id DESC LIMIT 1
            """
        ),
        {"broker_account_id": broker_account_id, "report_date": report_date},
    ).fetchone()
    return Decimal(str(row[0])) if row is not None and row[0] is not None else None


def _upgrade_nav_only_completeness(db: Session, broker_account_id: int, report_date: date) -> bool:
    row = db.execute(
        text(
            """
            SELECT id, completeness_status FROM portfolio_data_completeness
            WHERE broker_account_id = :broker_account_id AND report_date = :report_date AND fact_scope = :fact_scope
            """
        ),
        {"broker_account_id": broker_account_id, "report_date": report_date, "fact_scope": HOLDINGS_FACT_SCOPE},
    ).fetchone()
    if row is None or row[1] != NAV_ONLY_STATUS:
        return False
    status, reason = _holdings_completeness_status(
        db, broker_account_id, report_date, _nav_stock_base(db, broker_account_id, report_date)
    )
    if status == NAV_ONLY_STATUS:
        return False
    db.execute(
        text(
            """
            UPDATE portfolio_data_completeness
            SET completeness_status = :status, missing_reason = :reason, updated_at = :updated_at
            WHERE id = :id
            """
        ),
        {"status": status, "reason": reason, "updated_at": _now(), "id": int(row[0])},
    )
    return True


def _resolve_path(storage_path: str, raw_dir: str | None) -> Path:
    path = Path(storage_path)
    return Path(raw_dir) / path.name if raw_dir else path


def rebuild_account(
    db: Session,
    account: dict[str, Any],
    *,
    apply: bool,
    raw_dir: str | None = None,
) -> AccountRebuildResult:
    broker_account_id = int(account["id"])
    result = AccountRebuildResult(broker_account_id=broker_account_id)
    claimed_positions: set[date] = set()
    claimed_cash: set[date] = set()
    restored: dict[date, RestoredDate] = {}
    # Earliest restored date per legacy account, for the History dirty mark (#169).
    earliest_by_legacy: dict[int | None, date] = {}

    def _note_restored(legacy_id: Any, report_date: date) -> None:
        key = int(legacy_id) if legacy_id is not None else None
        if key not in earliest_by_legacy or report_date < earliest_by_legacy[key]:
            earliest_by_legacy[key] = report_date

    for document in _completed_documents(db, broker_account_id):
        path = _resolve_path(str(document["storage_path"]), raw_dir)
        if not path.is_file():
            result.documents_missing += 1
            continue
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != document["content_hash"]:
            result.documents_rejected += 1
            continue
        try:
            statement = parse_flex_statement(payload.decode("utf-8"))
        except (IbkrFlexImportError, UnicodeDecodeError):
            result.documents_rejected += 1
            continue
        if statement.data_quality_errors or statement.broker_account_id != account["external_account_id"]:
            result.documents_rejected += 1
            continue
        result.documents_read += 1

        scopes = _fact_scopes(statement)
        positions_by_date: dict[date, list[FlexPosition]] = {}
        for position in statement.positions:
            positions_by_date.setdefault(position.report_date, []).append(position)
        cash_by_date: dict[date, list[FlexCashBalance]] = {}
        for cash in statement.cash_balances:
            cash_by_date.setdefault(cash.report_date, []).append(cash)

        raw_document_id = int(document["raw_document_id"])
        import_run_id = int(document["import_run_id"])
        legacy_account_id = document["legacy_account_id"] or account["legacy_account_id"]

        def _entry(report_date: date) -> RestoredDate:
            if report_date not in restored:
                restored[report_date] = RestoredDate(
                    report_date=report_date, raw_document_id=raw_document_id, import_run_id=import_run_id
                )
            return restored[report_date]

        # A newer report speaking for a date decides it, even with zero rows there.
        for report_date in sorted(scopes.positions - claimed_positions):
            claimed_positions.add(report_date)
            rows = positions_by_date.get(report_date, [])
            if not rows or _has_rows(db, "portfolio_position_snapshots", broker_account_id, report_date):
                continue
            entry = _entry(report_date)
            entry.positions = len(rows)
            _note_restored(legacy_account_id, report_date)
            if apply:
                status = _restored_authority_status(db, broker_account_id, report_date)
                for position in rows:
                    _insert_position_snapshot(
                        db,
                        broker_account_id=broker_account_id,
                        legacy_account_id=legacy_account_id,
                        import_run_id=import_run_id,
                        raw_document_id=raw_document_id,
                        position=position,
                        authority_status=status,
                    )
        for report_date in sorted(scopes.cash - claimed_cash):
            claimed_cash.add(report_date)
            cash_rows = cash_by_date.get(report_date, [])
            if not cash_rows or _has_rows(db, "portfolio_cash_balance_snapshots", broker_account_id, report_date):
                continue
            entry = _entry(report_date)
            entry.cash_balances = len(cash_rows)
            _note_restored(legacy_account_id, report_date)
            if apply:
                status = _restored_authority_status(db, broker_account_id, report_date)
                for cash in cash_rows:
                    _insert_cash_balance_snapshot(
                        db,
                        broker_account_id=broker_account_id,
                        legacy_account_id=legacy_account_id,
                        import_run_id=import_run_id,
                        raw_document_id=raw_document_id,
                        cash=cash,
                        authority_status=status,
                    )

    if apply:
        for report_date, entry in restored.items():
            entry.completeness_upgraded = _upgrade_nav_only_completeness(db, broker_account_id, report_date)
        # Positions and cash came back for past dates: History rows anchored on or
        # after the earliest are recomputed, as after an import (#138, #169).
        for legacy_id, earliest in sorted(earliest_by_legacy.items(), key=lambda item: item[1]):
            mark_rollups_dirty(db, earliest, account_id=legacy_id, reason="ibkr_rebuild")
    result.dates = sorted(restored.values(), key=lambda item: item.report_date)
    return result


def rebuild_ibkr_flex_snapshots(
    db: Session,
    *,
    apply: bool = False,
    broker_account_id: int | None = None,
    raw_dir: str | None = None,
) -> list[AccountRebuildResult]:
    """Rebuild every IBKR account (or one); writes and commits only when ``apply``."""
    results: list[AccountRebuildResult] = []
    for account in _ibkr_broker_accounts(db, broker_account_id):
        try:
            results.append(rebuild_account(db, account, apply=apply, raw_dir=raw_dir))
            if apply:
                db.commit()
            else:
                db.rollback()
        except Exception:
            db.rollback()
            raise
    return results

