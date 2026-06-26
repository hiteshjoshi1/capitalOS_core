"""
Canonical adapter for upload-parser results (Phase 2).

Converts ParseResult positions from upload parsers (Sharekhan, DBS Vickers,
legacy IBKR CSV) into canonical portfolio facts using the same write-path
patterns established in Phase 1 (ibkr_flex.py).

Key design decisions:
- Upload parsers produce positions only; no NAV, cash, FX, or trade detail.
- Completeness records are always written for missing fact scopes.
- Sharekhan/DBS Vickers uploads are authoritative for their platform facts.
- IBKR manual-CSV uploads after flex cutover are written as reference-only.
- Adapter writes are deterministic and idempotent for identical uploads.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ingestion.parsers.base import ParseResult

UPLOAD_ADAPTER_VERSION = "upload_canonical_v1"

# Platforms handled as canonical upload sources (portfolio positions path)
_PLATFORM_SOURCE_KIND: dict[str, str] = {
    "SHAREKHAN": "sharekhan_upload",
    "DBS_VICKERS": "dbs_vickers_upload",
    "IBKR": "ibkr_csv_upload",
}

# Platforms that are always authoritative for their portfolio position facts
_AUTHORITATIVE_PLATFORMS: frozenset[str] = frozenset({"SHAREKHAN", "DBS_VICKERS"})

# Platforms that are reference-only for portfolio positions (authoritative source is elsewhere)
_REFERENCE_ONLY_PLATFORMS: frozenset[str] = frozenset({"IBKR"})

# Fact scopes that are always incomplete for upload-parser uploads
_INCOMPLETE_SCOPES: list[tuple[str, str]] = [
    ("cash_balance", "upload_parser_no_cash_detail"),
    ("nav", "upload_parser_no_nav_detail"),
    ("trades", "upload_parser_no_trade_detail"),
]

# ---------------------------------------------------------------------------
# Canonical adapter registry (Phase 5)
# ---------------------------------------------------------------------------
# Maps each parser_key to the canonical target type:
#   "portfolio_positions" → portfolio_position_snapshots (investment holdings)
#   "account_balance"     → account_balance_snapshots (bank/cash balances)
#   "none"                → parser emits no positions; no canonical adapter needed
#
# Any parser that emits non-empty positions MUST have an explicit entry here.
# Imports from unregistered parsers that produce positions will fail closed.
PARSER_CANONICAL_REGISTRY: dict[str, str] = {
    "sharekhan_holdings_xls_v1": "portfolio_positions",
    "dbs_vickers_holdings_xls_v1": "portfolio_positions",
    "ibkr_activity_csv_v1": "portfolio_positions",
    "uob_account_xls_v1": "account_balance",
    "ocbc_account_csv_v1": "account_balance",
    "dbs_transaction_history_csv_v1": "account_balance",
    "uob_credit_card_xls_v1": "none",
    "citi_credit_card_csv_v1": "none",
}

# Source kind used when writing account balance snapshots from upload parsers
_BALANCE_SOURCE_KIND = "upload_parser"


def _now() -> datetime:
    return datetime.now(tz=timezone.utc).replace(microsecond=0)


def _db_decimal(value: float | Decimal | None) -> str | None:
    if value is None:
        return None
    return str(Decimal(str(value)))


def _platform_json_default(db: Session) -> str:
    dialect_name = getattr(getattr(getattr(db, "bind", None), "dialect", None), "name", "sqlite")
    return "'{}'::jsonb" if dialect_name == "postgresql" else "'{}'"


def _source_kind_for_platform(platform_code: str) -> str | None:
    return _PLATFORM_SOURCE_KIND.get(platform_code.upper())


def is_canonical_upload_platform(platform_code: str) -> bool:
    """Return True if this platform has a canonical portfolio-positions upload adapter.

    Note: bank/cash parsers (UOB, OCBC, DBS) are covered by the balance adapter
    which is looked up via ``parser_canonical_target`` using the parser key, not
    the platform code.  This function only covers the portfolio-positions path.
    """
    return platform_code.upper() in _PLATFORM_SOURCE_KIND


def parser_canonical_target(parser_key: str) -> str | None:
    """Return the canonical adapter target for a parser key.

    Returns:
        "portfolio_positions" – write to portfolio_position_snapshots
        "account_balance"     – write to account_balance_snapshots
        "none"                – parser emits no positions; no adapter needed
        None                  – parser key is not registered (caller must decide whether to fail)
    """
    return PARSER_CANONICAL_REGISTRY.get(parser_key)


def _ensure_broker_account(
    db: Session,
    *,
    current_user_id: int,
    legacy_account_id: int,
    platform_code: str,
    base_currency: str,
) -> int:
    """Ensure broker connection and broker account for an upload platform."""
    connection = db.execute(
        text(
            """
            SELECT id
            FROM broker_connections
            WHERE user_id = :user_id
              AND platform_code = :platform_code
              AND connection_type = 'manual_upload'
              AND status = 'active'
            ORDER BY id
            LIMIT 1
            """
        ),
        {"user_id": current_user_id, "platform_code": platform_code},
    ).fetchone()

    if connection:
        connection_id = int(connection[0])
    else:
        db.execute(
            text(
                f"""
                INSERT INTO broker_connections
                  (user_id, platform_code, connection_type, display_name, status, metadata_json)
                VALUES
                  (:user_id, :platform_code, 'manual_upload', :display_name, 'active', {_platform_json_default(db)})
                """
            ),
            {
                "user_id": current_user_id,
                "platform_code": platform_code,
                "display_name": f"{platform_code} Upload",
            },
        )
        row = db.execute(
            text(
                """
                SELECT id
                FROM broker_connections
                WHERE user_id = :user_id
                  AND platform_code = :platform_code
                  AND connection_type = 'manual_upload'
                ORDER BY id DESC
                LIMIT 1
                """
            ),
            {"user_id": current_user_id, "platform_code": platform_code},
        ).fetchone()
        connection_id = int(row[0])

    # Use legacy_account_id as a stable string key for the broker_account_id
    upload_account_key = f"upload_{legacy_account_id}"
    account = db.execute(
        text(
            """
            SELECT id
            FROM broker_accounts
            WHERE connection_id = :connection_id
              AND broker_account_id = :broker_account_id
            LIMIT 1
            """
        ),
        {"connection_id": connection_id, "broker_account_id": upload_account_key},
    ).fetchone()

    if account:
        broker_account_pk = int(account[0])
        db.execute(
            text(
                """
                UPDATE broker_accounts
                SET legacy_account_id = :legacy_account_id,
                    base_currency = :base_currency,
                    updated_at = :updated_at
                WHERE id = :broker_account_pk
                """
            ),
            {
                "legacy_account_id": legacy_account_id,
                "base_currency": base_currency,
                "updated_at": _now(),
                "broker_account_pk": broker_account_pk,
            },
        )
        return broker_account_pk

    db.execute(
        text(
            f"""
            INSERT INTO broker_accounts
              (connection_id, legacy_account_id, broker_account_id, base_currency, status, metadata_json)
            VALUES
              (:connection_id, :legacy_account_id, :broker_account_id, :base_currency, 'active', {_platform_json_default(db)})
            """
        ),
        {
            "connection_id": connection_id,
            "legacy_account_id": legacy_account_id,
            "broker_account_id": upload_account_key,
            "base_currency": base_currency,
        },
    )
    row = db.execute(
        text(
            """
            SELECT id
            FROM broker_accounts
            WHERE connection_id = :connection_id
              AND broker_account_id = :broker_account_id
            LIMIT 1
            """
        ),
        {"connection_id": connection_id, "broker_account_id": upload_account_key},
    ).fetchone()
    return int(row[0])


def _ensure_upload_authority_window(
    db: Session,
    broker_account_id: int,
    source_kind: str,
    effective_from: date,
) -> None:
    """Idempotently create a source authority window for an upload platform."""
    exists = db.execute(
        text(
            """
            SELECT 1
            FROM portfolio_source_authority_windows
            WHERE broker_account_id = :broker_account_id
              AND source_kind = :source_kind
              AND fact_scope = 'holdings'
              AND effective_from = :effective_from
            LIMIT 1
            """
        ),
        {
            "broker_account_id": broker_account_id,
            "source_kind": source_kind,
            "effective_from": effective_from,
        },
    ).fetchone()
    if exists:
        return
    db.execute(
        text(
            """
            INSERT INTO portfolio_source_authority_windows
              (broker_account_id, source_kind, fact_scope, effective_from, authority_status)
            VALUES
              (:broker_account_id, :source_kind, 'holdings', :effective_from, 'authoritative')
            """
        ),
        {
            "broker_account_id": broker_account_id,
            "source_kind": source_kind,
            "effective_from": effective_from,
        },
    )


def _create_upload_import_run(
    db: Session,
    *,
    broker_account_id: int,
    legacy_account_id: int,
    platform_code: str,
    source_kind: str,
    report_date: date,
) -> int:
    db.execute(
        text(
            f"""
            INSERT INTO broker_import_runs
              (broker_account_id, legacy_account_id, platform_code, source_type, import_scope, status,
               started_at, report_date_from, report_date_to, parser_version, metadata_json)
            VALUES
              (:broker_account_id, :legacy_account_id, :platform_code, :source_type, 'upload', 'started',
               :started_at, :report_date, :report_date, :parser_version, {_platform_json_default(db)})
            """
        ),
        {
            "broker_account_id": broker_account_id,
            "legacy_account_id": legacy_account_id,
            "platform_code": platform_code,
            "source_type": source_kind,
            "started_at": _now(),
            "report_date": report_date,
            "parser_version": UPLOAD_ADAPTER_VERSION,
        },
    )
    row = db.execute(
        text(
            """
            SELECT id
            FROM broker_import_runs
            WHERE broker_account_id = :broker_account_id
              AND source_type = :source_type
              AND status = 'started'
            ORDER BY id DESC
            LIMIT 1
            """
        ),
        {"broker_account_id": broker_account_id, "source_type": source_kind},
    ).fetchone()
    return int(row[0])


def _store_upload_raw_document(
    db: Session,
    *,
    import_run_id: int,
    broker_account_id: int,
    platform_code: str,
    source_kind: str,
    stored_path: str,
    file_sha256: str,
    report_date: date,
) -> int:
    db.execute(
        text(
            f"""
            INSERT INTO raw_broker_documents
              (import_run_id, broker_account_id, source_type, content_hash, storage_path,
               content_type, report_date_from, report_date_to, parser_version, metadata_json)
            VALUES
              (:import_run_id, :broker_account_id, :source_type, :content_hash, :storage_path,
               'application/octet-stream', :report_date, :report_date, :parser_version, {_platform_json_default(db)})
            """
        ),
        {
            "import_run_id": import_run_id,
            "broker_account_id": broker_account_id,
            "source_type": source_kind,
            "content_hash": file_sha256,
            "storage_path": stored_path,
            "report_date": report_date,
            "parser_version": UPLOAD_ADAPTER_VERSION,
        },
    )
    row = db.execute(
        text(
            """
            SELECT id
            FROM raw_broker_documents
            WHERE import_run_id = :import_run_id
            ORDER BY id DESC
            LIMIT 1
            """
        ),
        {"import_run_id": import_run_id},
    ).fetchone()
    raw_document_id = int(row[0])
    db.execute(
        text(
            """
            UPDATE broker_import_runs
            SET raw_document_id = :raw_document_id,
                fetched_at = :fetched_at,
                updated_at = :updated_at
            WHERE id = :import_run_id
            """
        ),
        {
            "raw_document_id": raw_document_id,
            "fetched_at": _now(),
            "updated_at": _now(),
            "import_run_id": import_run_id,
        },
    )
    return raw_document_id


def _ensure_upload_broker_instrument(
    db: Session,
    *,
    platform_code: str,
    symbol: str,
    currency: str,
    description: str | None,
    security_type: str | None,
) -> int:
    """Upsert a broker_instrument record for an upload-parser position.

    Upload parsers do not have broker contract IDs (conids). We synthesise a
    stable broker_instrument_id from symbol and currency so that repeated
    uploads of the same symbol produce the same instrument record.
    """
    synthetic_id = f"{symbol.upper()}_{currency.upper()}"

    row = db.execute(
        text(
            """
            SELECT id
            FROM broker_instruments
            WHERE platform_code = :platform_code
              AND broker_instrument_id = :broker_instrument_id
              AND COALESCE(currency, '') = :currency
            LIMIT 1
            """
        ),
        {
            "platform_code": platform_code,
            "broker_instrument_id": synthetic_id,
            "currency": currency.upper(),
        },
    ).fetchone()

    if row:
        instrument_id = int(row[0])
        db.execute(
            text(
                """
                UPDATE broker_instruments
                SET symbol = COALESCE(:symbol, symbol),
                    description = COALESCE(:description, description),
                    security_type = COALESCE(:security_type, security_type),
                    updated_at = :updated_at
                WHERE id = :instrument_id
                """
            ),
            {
                "symbol": symbol,
                "description": description,
                "security_type": security_type,
                "updated_at": _now(),
                "instrument_id": instrument_id,
            },
        )
        return instrument_id

    db.execute(
        text(
            f"""
            INSERT INTO broker_instruments
              (platform_code, broker_instrument_id, symbol, description, security_type,
               currency, metadata_json)
            VALUES
              (:platform_code, :broker_instrument_id, :symbol, :description, :security_type,
               :currency, {_platform_json_default(db)})
            """
        ),
        {
            "platform_code": platform_code,
            "broker_instrument_id": synthetic_id,
            "symbol": symbol,
            "description": description,
            "security_type": security_type,
            "currency": currency.upper(),
        },
    )
    row = db.execute(
        text(
            """
            SELECT id
            FROM broker_instruments
            WHERE platform_code = :platform_code
              AND broker_instrument_id = :broker_instrument_id
              AND COALESCE(currency, '') = :currency
            LIMIT 1
            """
        ),
        {
            "platform_code": platform_code,
            "broker_instrument_id": synthetic_id,
            "currency": currency.upper(),
        },
    ).fetchone()
    return int(row[0])


def _clear_existing_upload_position_facts(
    db: Session,
    broker_account_id: int,
    report_date: date,
) -> None:
    """Delete existing authoritative position snapshots for this account/date."""
    for table_name in (
        "portfolio_position_snapshots",
        "portfolio_data_completeness",
    ):
        db.execute(
            text(
                f"DELETE FROM {table_name} "
                "WHERE broker_account_id = :broker_account_id AND report_date = :report_date"
            ),
            {"broker_account_id": broker_account_id, "report_date": report_date},
        )


def _insert_upload_position_snapshots(
    db: Session,
    *,
    broker_account_id: int,
    legacy_account_id: int,
    import_run_id: int,
    raw_document_id: int,
    platform_code: str,
    report_date: date,
    positions: list[dict[str, Any]],
    authority_status: str,
) -> int:
    """Write canonical position snapshots for upload-parser positions."""
    inserted = 0
    for pos in positions:
        symbol = pos.get("symbol")
        currency = pos.get("currency") or "XXX"
        if not symbol:
            continue

        quantity = pos.get("quantity")
        if quantity is None:
            continue

        instrument_id = _ensure_upload_broker_instrument(
            db,
            platform_code=platform_code,
            symbol=str(symbol),
            currency=str(currency),
            description=pos.get("name"),
            security_type=pos.get("asset_class"),
        )

        cost_basis_base = pos.get("cost_basis_base")
        market_value_base = cost_basis_base if cost_basis_base is not None else Decimal("0")
        avg_cost = pos.get("avg_cost")

        db.execute(
            text(
                f"""
                INSERT INTO portfolio_position_snapshots
                  (broker_account_id, legacy_account_id, broker_instrument_id, import_run_id, raw_document_id,
                   report_date, quantity, currency, market_price, market_value_local, market_value_base,
                   cost_basis_local, cost_basis_base, fx_rate_to_base, authority_status, metadata_json)
                VALUES
                  (:broker_account_id, :legacy_account_id, :broker_instrument_id, :import_run_id, :raw_document_id,
                   :report_date, :quantity, :currency, :market_price, :market_value_local, :market_value_base,
                   :cost_basis_local, :cost_basis_base, :fx_rate_to_base, :authority_status, {_platform_json_default(db)})
                """
            ),
            {
                "broker_account_id": broker_account_id,
                "legacy_account_id": legacy_account_id,
                "broker_instrument_id": instrument_id,
                "import_run_id": import_run_id,
                "raw_document_id": raw_document_id,
                "report_date": report_date,
                "quantity": _db_decimal(quantity),
                "currency": str(currency).upper(),
                "market_price": _db_decimal(avg_cost),
                "market_value_local": _db_decimal(market_value_base),
                "market_value_base": _db_decimal(market_value_base),
                "cost_basis_local": _db_decimal(cost_basis_base),
                "cost_basis_base": _db_decimal(cost_basis_base),
                "fx_rate_to_base": "1",
                "authority_status": authority_status,
            },
        )
        inserted += 1
    return inserted


def _insert_completeness_records(
    db: Session,
    *,
    broker_account_id: int,
    import_run_id: int,
    raw_document_id: int,
    report_date: date,
    positions_written: int,
) -> None:
    """Record completeness for the fact scopes present/absent in an upload."""
    holdings_status = "complete" if positions_written > 0 else "incomplete"
    holdings_reason = None if positions_written > 0 else "upload_parser_no_positions"

    all_records = [
        ("holdings", holdings_status, holdings_reason),
    ] + [
        (scope, "incomplete", reason) for scope, reason in _INCOMPLETE_SCOPES
    ]

    for fact_scope, completeness_status, missing_reason in all_records:
        db.execute(
            text(
                f"""
                INSERT INTO portfolio_data_completeness
                  (broker_account_id, import_run_id, raw_document_id, report_date, fact_scope,
                   completeness_status, missing_reason, metadata_json)
                VALUES
                  (:broker_account_id, :import_run_id, :raw_document_id, :report_date, :fact_scope,
                   :completeness_status, :missing_reason, {_platform_json_default(db)})
                """
            ),
            {
                "broker_account_id": broker_account_id,
                "import_run_id": import_run_id,
                "raw_document_id": raw_document_id,
                "report_date": report_date,
                "fact_scope": fact_scope,
                "completeness_status": completeness_status,
                "missing_reason": missing_reason,
            },
        )


def _record_data_quality_event(
    db: Session,
    *,
    broker_account_id: int,
    import_run_id: int,
    raw_document_id: int,
    report_date: date,
    severity: str,
    event_code: str,
    message: str,
) -> None:
    db.execute(
        text(
            f"""
            INSERT INTO portfolio_data_quality_events
              (broker_account_id, import_run_id, raw_document_id, report_date, severity, event_code, message, metadata_json)
            VALUES
              (:broker_account_id, :import_run_id, :raw_document_id, :report_date, :severity, :event_code, :message, {_platform_json_default(db)})
            """
        ),
        {
            "broker_account_id": broker_account_id,
            "import_run_id": import_run_id,
            "raw_document_id": raw_document_id,
            "report_date": report_date,
            "severity": severity,
            "event_code": event_code,
            "message": message,
        },
    )


def _mark_import_run_completed(db: Session, import_run_id: int) -> None:
    db.execute(
        text(
            """
            UPDATE broker_import_runs
            SET status = 'completed',
                parsed_at = COALESCE(parsed_at, :parsed_at),
                finished_at = :finished_at,
                updated_at = :updated_at
            WHERE id = :import_run_id
            """
        ),
        {
            "parsed_at": _now(),
            "finished_at": _now(),
            "updated_at": _now(),
            "import_run_id": import_run_id,
        },
    )


def _mark_import_run_failed(db: Session, import_run_id: int, code: str, message: str) -> None:
    db.execute(
        text(
            """
            UPDATE broker_import_runs
            SET status = 'failed',
                error_code = :error_code,
                error_message = :error_message,
                finished_at = :finished_at,
                updated_at = :updated_at
            WHERE id = :import_run_id
            """
        ),
        {
            "error_code": code,
            "error_message": message,
            "finished_at": _now(),
            "updated_at": _now(),
            "import_run_id": import_run_id,
        },
    )


def _resolve_report_date(parse_result: ParseResult) -> date:
    """Derive the canonical report_date from parser metadata or fall back to today."""
    meta = parse_result.parser_meta or {}
    for key in ("statement_period_end", "report_date", "statement_date", "as_of"):
        val = meta.get(key)
        if val is not None:
            if hasattr(val, "date"):
                return val.date()
            if hasattr(val, "year"):
                return val
            try:
                from datetime import datetime as dt
                parsed = dt.fromisoformat(str(val))
                return parsed.date()
            except (ValueError, TypeError):
                continue

    # Fall back to today as the snapshot date
    return date.today()


def run_upload_canonical_adapter(
    db: Session,
    *,
    current_user_id: int,
    legacy_account_id: int,
    platform_code: str,
    parse_result: ParseResult,
    stored_path: str,
    file_sha256: str,
    is_ibkr_flex_cutover_active: bool = False,
) -> dict[str, Any]:
    """Adapt an upload ParseResult into canonical portfolio facts.

    This is the entry point for Phase 2. It writes canonical facts for
    upload-parser results without changing the upstream parser or the
    legacy write path in runner.py.

    Args:
        db: SQLAlchemy session.
        current_user_id: The user performing the upload.
        legacy_account_id: The legacy accounts.id for this upload.
        platform_code: Platform code (SHAREKHAN, DBS_VICKERS, IBKR, etc.).
        parse_result: The ParseResult produced by the upload parser.
        stored_path: Filesystem path to the stored upload file.
        file_sha256: SHA-256 of the upload file (for content-hash dedup).
        is_ibkr_flex_cutover_active: When True, IBKR uploads produce
            reference-only canonical facts instead of authoritative facts.

    Returns:
        Dict with canonical write result metadata.
    """
    upper_platform = platform_code.upper()
    source_kind = _source_kind_for_platform(upper_platform)
    if not source_kind:
        return {"status": "skipped", "reason": f"platform {upper_platform} has no canonical upload adapter"}

    positions = parse_result.positions or []
    report_date = _resolve_report_date(parse_result)

    # Determine authority_status
    if upper_platform in _AUTHORITATIVE_PLATFORMS:
        authority_status = "authoritative"
    elif upper_platform in _REFERENCE_ONLY_PLATFORMS or is_ibkr_flex_cutover_active:
        authority_status = "reference"
    else:
        authority_status = "authoritative"

    # Derive base currency from first position or fallback
    base_currency = "XXX"
    if positions:
        base_currency = (positions[0].get("currency") or "XXX").upper()

    broker_account_id = _ensure_broker_account(
        db,
        current_user_id=current_user_id,
        legacy_account_id=legacy_account_id,
        platform_code=upper_platform,
        base_currency=base_currency,
    )

    # Set up source authority window for authoritative uploads only
    if authority_status == "authoritative":
        _ensure_upload_authority_window(db, broker_account_id, source_kind, report_date)

    import_run_id = _create_upload_import_run(
        db,
        broker_account_id=broker_account_id,
        legacy_account_id=legacy_account_id,
        platform_code=upper_platform,
        source_kind=source_kind,
        report_date=report_date,
    )
    raw_document_id = _store_upload_raw_document(
        db,
        import_run_id=import_run_id,
        broker_account_id=broker_account_id,
        platform_code=upper_platform,
        source_kind=source_kind,
        stored_path=stored_path,
        file_sha256=file_sha256,
        report_date=report_date,
    )

    # Idempotent fact replacement: clear existing canonical facts for this
    # account + date before writing new ones.
    _clear_existing_upload_position_facts(db, broker_account_id, report_date)

    positions_written = 0
    try:
        positions_written = _insert_upload_position_snapshots(
            db,
            broker_account_id=broker_account_id,
            legacy_account_id=legacy_account_id,
            import_run_id=import_run_id,
            raw_document_id=raw_document_id,
            platform_code=upper_platform,
            report_date=report_date,
            positions=positions,
            authority_status=authority_status,
        )

        _insert_completeness_records(
            db,
            broker_account_id=broker_account_id,
            import_run_id=import_run_id,
            raw_document_id=raw_document_id,
            report_date=report_date,
            positions_written=positions_written,
        )

        if positions_written == 0 and positions:
            _record_data_quality_event(
                db,
                broker_account_id=broker_account_id,
                import_run_id=import_run_id,
                raw_document_id=raw_document_id,
                report_date=report_date,
                severity="warning",
                event_code="no_canonical_positions_written",
                message="Parser produced position rows but none were written canonically",
            )

        _mark_import_run_completed(db, import_run_id)

    except Exception as exc:
        _record_data_quality_event(
            db,
            broker_account_id=broker_account_id,
            import_run_id=import_run_id,
            raw_document_id=raw_document_id,
            report_date=report_date,
            severity="error",
            event_code="canonical_write_failed",
            message=str(exc),
        )
        _mark_import_run_failed(db, import_run_id, "canonical_write_failed", str(exc))
        raise

    return {
        "status": "CANONICAL_IMPORTED",
        "platform": upper_platform,
        "source_kind": source_kind,
        "broker_account_id": broker_account_id,
        "import_run_id": import_run_id,
        "raw_document_id": raw_document_id,
        "report_date": report_date.isoformat(),
        "authority_status": authority_status,
        "counts": {
            "positions": positions_written,
        },
    }


# ---------------------------------------------------------------------------
# Canonical balance adapter for bank/account parsers (Phase 5)
# ---------------------------------------------------------------------------

def _resolve_balance_date(parse_result: ParseResult) -> date:
    """Derive the canonical as_of_date for a bank/account balance snapshot.

    Checks parser_meta keys in priority order, then falls back to today.
    """
    meta = parse_result.parser_meta or {}
    for key in ("statement_period_end", "report_date", "statement_date", "as_of"):
        val = meta.get(key)
        if val is None:
            continue
        if hasattr(val, "date"):
            return val.date()
        if hasattr(val, "year"):
            return val
        try:
            from datetime import datetime as _dt
            parsed = _dt.fromisoformat(str(val))
            return parsed.date()
        except (ValueError, TypeError):
            continue

    # Try the positions themselves for an as_of value
    for pos in (parse_result.positions or []):
        pos_as_of = pos.get("as_of")
        if pos_as_of is not None:
            if hasattr(pos_as_of, "date"):
                return pos_as_of.date()
            if hasattr(pos_as_of, "year"):
                return pos_as_of
            try:
                from datetime import datetime as _dt2
                parsed2 = _dt2.fromisoformat(str(pos_as_of))
                return parsed2.date()
            except (ValueError, TypeError):
                pass

    return date.today()


def _source_row_hash_for_balance(account_id: int, as_of_date: date, currency: str, balance: float) -> str:
    """Stable hash for dedup-detection of a bank balance row."""
    raw = f"{account_id}|{as_of_date.isoformat()}|{currency}|{balance}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _write_account_balance_snapshot(
    db: Session,
    *,
    account_id: int,
    import_job_id: int | None,
    as_of_date: date,
    currency: str,
    balance_local: float,
    balance_base: float,
    balance_type: str,
    source_row_hash: str,
) -> None:
    """Upsert a single authoritative account balance snapshot.

    Uses DELETE + INSERT to handle the partial-unique-index constraint
    (SQLite does not support ON CONFLICT on partial indexes).
    """
    dialect_name = getattr(getattr(getattr(db, "bind", None), "dialect", None), "name", "sqlite")
    if dialect_name == "postgresql":
        db.execute(
            text(
                """
                INSERT INTO account_balance_snapshots
                  (account_id, import_job_id, as_of_date, currency, balance_type,
                   balance_local, balance_base, fx_rate_to_base, authority_status,
                   source_kind, source_row_hash)
                VALUES
                  (:account_id, :import_job_id, :as_of_date, :currency, :balance_type,
                   :balance_local, :balance_base, 1, 'authoritative',
                   :source_kind, :source_row_hash)
                ON CONFLICT (account_id, as_of_date, currency, balance_type)
                  WHERE authority_status = 'authoritative'
                DO UPDATE SET
                  balance_local = EXCLUDED.balance_local,
                  balance_base = EXCLUDED.balance_base,
                  import_job_id = EXCLUDED.import_job_id,
                  source_row_hash = EXCLUDED.source_row_hash,
                  updated_at = now()
                """
            ),
            {
                "account_id": account_id,
                "import_job_id": import_job_id,
                "as_of_date": as_of_date,
                "currency": currency.upper(),
                "balance_type": balance_type,
                "balance_local": _db_decimal(balance_local),
                "balance_base": _db_decimal(balance_base),
                "source_kind": _BALANCE_SOURCE_KIND,
                "source_row_hash": source_row_hash,
            },
        )
    else:
        # SQLite: manual delete-then-insert because partial-index ON CONFLICT is unsupported
        db.execute(
            text(
                """
                DELETE FROM account_balance_snapshots
                WHERE account_id = :account_id
                  AND as_of_date = :as_of_date
                  AND currency = :currency
                  AND balance_type = :balance_type
                  AND authority_status = 'authoritative'
                """
            ),
            {
                "account_id": account_id,
                "as_of_date": as_of_date,
                "currency": currency.upper(),
                "balance_type": balance_type,
            },
        )
        db.execute(
            text(
                """
                INSERT INTO account_balance_snapshots
                  (account_id, import_job_id, as_of_date, currency, balance_type,
                   balance_local, balance_base, fx_rate_to_base, authority_status,
                   source_kind, source_row_hash)
                VALUES
                  (:account_id, :import_job_id, :as_of_date, :currency, :balance_type,
                   :balance_local, :balance_base, 1, 'authoritative',
                   :source_kind, :source_row_hash)
                """
            ),
            {
                "account_id": account_id,
                "import_job_id": import_job_id,
                "as_of_date": as_of_date,
                "currency": currency.upper(),
                "balance_type": balance_type,
                "balance_local": _db_decimal(balance_local),
                "balance_base": _db_decimal(balance_base),
                "source_kind": _BALANCE_SOURCE_KIND,
                "source_row_hash": source_row_hash,
            },
        )


def run_upload_balance_canonical_adapter(
    db: Session,
    *,
    account_id: int,
    import_job_id: int | None,
    parse_result: ParseResult,
) -> dict[str, Any]:
    """Adapt bank/account upload ParseResult into canonical account_balance_snapshots.

    This is the canonical path for parsers that produce cash/balance positions:
    - uob_account_xls_v1
    - ocbc_account_csv_v1
    - dbs_transaction_history_csv_v1

    Only CASH asset-class positions are written as account balances.  Any other
    asset class in positions is ignored (should not occur for these parsers but
    the function is defensive).

    Returns:
        Dict with canonical write result metadata.
    """
    positions = [
        p for p in (parse_result.positions or [])
        if (p.get("asset_class") or "").upper() in ("CASH", "") or not p.get("asset_class")
    ]
    as_of_date = _resolve_balance_date(parse_result)
    balances_written = 0

    for pos in positions:
        currency = (pos.get("currency") or "XXX").upper()
        quantity = pos.get("quantity")
        cost_basis_base = pos.get("cost_basis_base")

        if quantity is None:
            continue

        balance_local = float(quantity)
        balance_base = float(cost_basis_base) if cost_basis_base is not None else balance_local
        row_hash = _source_row_hash_for_balance(account_id, as_of_date, currency, balance_local)

        _write_account_balance_snapshot(
            db,
            account_id=account_id,
            import_job_id=import_job_id,
            as_of_date=as_of_date,
            currency=currency,
            balance_local=balance_local,
            balance_base=balance_base,
            balance_type="bank_cash",
            source_row_hash=row_hash,
        )
        balances_written += 1

    return {
        "status": "CANONICAL_IMPORTED",
        "adapter": "account_balance",
        "account_id": account_id,
        "as_of_date": as_of_date.isoformat(),
        "counts": {
            "balances": balances_written,
        },
    }
