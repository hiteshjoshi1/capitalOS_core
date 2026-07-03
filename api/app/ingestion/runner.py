from __future__ import annotations

import hashlib
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logging import get_job_id, job_context
from app.ingestion.parsers import ParseResult
from app.ingestion.parsers.citi_credit_card_csv_v1 import parse_citi_credit_card_csv
from app.ingestion.signature import compute_format_signature
from app.ingestion.registry import lookup_parser_key
from app.ingestion.validators import validate_transactions
from app.ingestion.report import write_report
from app.ingestion.parsers.ibkr_activity_csv_v1 import parse_ibkr_activity_csv
from app.ingestion.parsers.dbs_transaction_history_csv_v1 import parse_dbs_transaction_history_csv
from app.ingestion.parsers.ocbc_account_csv_v1 import parse_ocbc_account_csv
from app.ingestion.parsers.sharekhan_holdings_xls_v1 import parse_sharekhan_holdings_xls
from app.ingestion.parsers.dbs_vickers_holdings_xls_v1 import parse_dbs_vickers_holdings_xls
from app.ingestion.parsers.uob_account_xls_v1 import parse_uob_account_xls
from app.ingestion.parsers.uob_credit_card_xls_v1 import parse_uob_credit_card_xls
from app.models.import_job import ImportJob
from app.portfolio.upload_canonical import (
    is_canonical_upload_platform,
    parser_canonical_target,
    run_upload_canonical_adapter,
    run_upload_balance_canonical_adapter,
)

logger = logging.getLogger("capitalos.ingestion")

PARSER_REGISTRY: dict[str, tuple[str, Callable[..., ParseResult]]] = {
    "ibkr_activity_csv_v1": ("csv", parse_ibkr_activity_csv),
    "dbs_transaction_history_csv_v1": ("csv", parse_dbs_transaction_history_csv),
    "ocbc_account_csv_v1": ("csv", parse_ocbc_account_csv),
    "sharekhan_holdings_xls_v1": ("excel", parse_sharekhan_holdings_xls),
    "dbs_vickers_holdings_xls_v1": ("excel", parse_dbs_vickers_holdings_xls),
    "uob_account_xls_v1": ("excel", parse_uob_account_xls),
    "uob_credit_card_xls_v1": ("excel", parse_uob_credit_card_xls),
    "citi_credit_card_csv_v1": ("csv", parse_citi_credit_card_csv),
}

CSV_PARSERS = {
    parser_key for parser_key, (kind, _) in PARSER_REGISTRY.items() if kind == "csv"
}


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _reason_category(payload: dict) -> str | None:
    if payload.get("error_class"):
        return str(payload["error_class"])
    error = str(payload.get("error_message") or "").strip()
    if not error:
        return None
    return error.split(":", 1)[0].strip().lower().replace(" ", "_")[:80]


def _log_ingestion_result(payload: dict, duration_ms: int) -> None:
    status = str(payload.get("status") or "")
    if status == "IMPORTED":
        event = "upload_ingest_succeeded"
        level = logger.info
    elif status == "NEEDS_MAPPING":
        event = "upload_ingest_needs_mapping"
        level = logger.warning
    elif status == "FAILED":
        event = "upload_ingest_failed"
        level = logger.warning
    else:
        return

    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    extra = {
        "event": event,
        "status": status,
        "job_db_id": payload.get("job_id"),
        "platform": payload.get("platform"),
        "parser_key": payload.get("parser_key"),
        "format_signature": payload.get("format_signature"),
        "rows": counts.get("rows_total"),
        "inserted": counts.get("transactions_inserted") or counts.get("canonical_positions_written") or counts.get("canonical_balances_written"),
        "skipped": counts.get("duplicates_skipped"),
        "duration_ms": duration_ms,
        "error_class": payload.get("error_class"),
        "reason": _reason_category(payload),
    }
    level(event, extra={key: value for key, value in extra.items() if value is not None})


def _sha256_file(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _fingerprint(account_id: int, tx: Dict[str, Any]) -> str:
    parts = [
        str(account_id),
        tx["ts"].isoformat(),
        tx["type"],
        f"{tx['amount']}",
        tx["currency"],
        tx.get("merchant_counterparty", "") or "",
        tx.get("category", "") or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compose_notes(fp: str, parser_notes: Any) -> str:
    if parser_notes is None or str(parser_notes).strip() == "":
        return f"fp:{fp}"
    return f"{parser_notes} | fp:{fp}"


def _snapshot_as_of() -> datetime:
    snapshot_day = int(os.getenv("SNAPSHOT_DAY", "1"))
    now = datetime.now(tz=timezone.utc)
    safe_day = min(snapshot_day, 28)
    return now.replace(day=safe_day, hour=0, minute=0, second=0, microsecond=0)


def _normalize_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return None


def _latest_transaction_ts(parsed: list[dict[str, Any]]) -> datetime | None:
    candidates = [_normalize_datetime(tx.get("ts")) for tx in parsed]
    normalized = [candidate for candidate in candidates if candidate is not None]
    return max(normalized) if normalized else None


def _resolve_position_as_of(pos: Dict[str, Any], parser_meta: Dict[str, Any], parsed: list[dict[str, Any]]) -> datetime:
    explicit = _normalize_datetime(pos.get("as_of"))
    if explicit is not None:
        return explicit

    for key in ("statement_period_end", "report_date", "statement_date", "as_of", "latest_transaction_at"):
        candidate = _normalize_datetime(parser_meta.get(key))
        if candidate is not None:
            return candidate

    latest_tx = _latest_transaction_ts(parsed)
    if latest_tx is not None:
        return latest_tx.replace(hour=0, minute=0, second=0, microsecond=0)

    return _snapshot_as_of()


def _get_or_create_asset(db: Session, pos: Dict[str, Any]) -> int | None:
    symbol = pos.get("symbol")
    currency = pos.get("currency")
    if not symbol or not currency:
        return None
    asset_class = (pos.get("asset_class") or "OTHER").upper()
    if asset_class == "CASH":
        # Normalize cash assets to use currency symbol (avoid duplicate CASH assets).
        if symbol.upper() == "CASH":
            symbol = currency.upper()
        if not pos.get("name"):
            pos["name"] = f"{symbol} Cash"
    row = db.execute(
        text(
            "SELECT id FROM assets WHERE symbol = :symbol AND quote_currency = :currency LIMIT 1"
        ),
        {"symbol": symbol, "currency": currency},
    ).fetchone()
    if row:
        return int(row[0])

    dialect = getattr(getattr(db, "bind", None), "dialect", None)
    is_sqlite = getattr(dialect, "name", "") == "sqlite"
    if is_sqlite:
        db.execute(
            text(
                """
                INSERT OR IGNORE INTO assets (symbol, name, asset_class, quote_currency, home_country)
                VALUES (:symbol, :name, :asset_class, :currency, :home_country)
                """
            ),
            {
                "symbol": symbol,
                "name": pos.get("name"),
                "asset_class": asset_class,
                "currency": currency,
                "home_country": pos.get("home_country"),
            },
        )
    else:
        db.execute(
            text(
                """
                INSERT INTO assets (symbol, name, asset_class, quote_currency, home_country)
                VALUES (:symbol, :name, :asset_class, :currency, :home_country)
                ON CONFLICT (symbol, quote_currency) DO NOTHING
                """
            ),
            {
                "symbol": symbol,
                "name": pos.get("name"),
                "asset_class": asset_class,
                "currency": currency,
                "home_country": pos.get("home_country"),
            },
        )
    row = db.execute(
        text(
            "SELECT id FROM assets WHERE symbol = :symbol AND quote_currency = :currency LIMIT 1"
        ),
        {"symbol": symbol, "currency": currency},
    ).fetchone()
    return int(row[0]) if row else None


def create_import_job(db: Session, account_id: int, platform: str, original_filename: str, upload_path: str, data_dir: str) -> ImportJob:
    job = ImportJob(
        account_id=account_id,
        platform=platform,
        original_filename=original_filename,
        stored_path="",
        file_sha256="",
        status="UPLOADED",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    raw_dir = os.path.join(data_dir, "raw", str(job.id))
    os.makedirs(raw_dir, exist_ok=True)
    stored_path = os.path.join(raw_dir, original_filename)
    shutil.copyfile(upload_path, stored_path)
    file_sha = _sha256_file(stored_path)

    job.stored_path = stored_path
    job.file_sha256 = file_sha
    job.updated_at = _now()
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def run_ingestion(db: Session, job_id: int, data_dir: str) -> dict:
    context = job_context() if get_job_id() is None else None
    if context is not None:
        context.__enter__()
    started = time.perf_counter()
    try:
        return _run_ingestion_with_context(db, job_id, data_dir, started)
    finally:
        if context is not None:
            context.__exit__(None, None, None)


def _run_ingestion_with_context(db: Session, job_id: int, data_dir: str, started: float) -> dict:
    job = db.query(ImportJob).filter(ImportJob.id == job_id).one()
    report_path = os.path.join(data_dir, "reports", f"{job.id}.json")
    logger.info(
        "upload_ingest_started",
        extra={
            "event": "upload_ingest_started",
            "job_db_id": job.id,
            "platform": job.platform,
            "status": job.status,
        },
    )

    def write_and_return(payload: dict) -> dict:
        write_report(report_path, payload)
        job.report_path = report_path
        job.updated_at = _now()
        db.add(job)
        db.commit()
        _log_ingestion_result(payload, int((time.perf_counter() - started) * 1000))
        return payload

    try:
        if not os.path.exists(job.stored_path):
            job.status = "FAILED"
            job.error_message = "Stored file not found"
            return write_and_return(_report(job, status="FAILED", error="Stored file not found"))

        signature, signature_debug = compute_format_signature(job.stored_path, platform_hint=job.platform)
        job.format_signature = signature
        job.status = "IDENTIFIED"
        job.updated_at = _now()
        db.add(job)
        db.commit()

        parser_key = lookup_parser_key(
            db,
            signature,
            signature_debug=signature_debug,
            platform_hint=job.platform,
        )
        if not parser_key:
            job.status = "NEEDS_MAPPING"
            job.updated_at = _now()
            db.add(job)
            db.commit()
            return write_and_return(
                _report(
                    job,
                    status="NEEDS_MAPPING",
                    signature_debug=signature_debug,
                    section_summary=[],
                )
            )

        delimiter = signature_debug.get("delimiter") if isinstance(signature_debug, dict) else None
        file_kind = signature_debug.get("file_kind") if isinstance(signature_debug, dict) else None
        # Defensive override: if a persisted signature mapping points to a CSV parser
        # but this upload was fingerprinted as excel/html, recover with heuristic inference.
        if parser_key in CSV_PARSERS and not delimiter and file_kind in {"excel", "html_table"}:
            inferred = lookup_parser_key(
                None,
                signature,
                signature_debug=signature_debug,
                platform_hint=job.platform,
            )
            if inferred and inferred != parser_key:
                parser_key = inferred

        job.parser_key = parser_key
        job.status = "PARSED"
        job.updated_at = _now()
        db.add(job)
        db.commit()

        parser_entry = PARSER_REGISTRY.get(parser_key)
        if parser_entry is None:
            job.status = "FAILED"
            job.error_message = f"Unsupported parser_key: {parser_key}"
            return write_and_return(_report(job, status="FAILED", error=job.error_message))

        kind, parser_fn = parser_entry
        if kind == "csv":
            if parser_key in CSV_PARSERS and not delimiter:
                raise ValueError(f"Missing delimiter for parser {parser_key}")
            result = parser_fn(job.stored_path, delimiter)
        elif kind == "excel":
            result = parser_fn(job.stored_path)
        else:
            job.status = "FAILED"
            job.error_message = f"Unsupported parser kind for {parser_key}: {kind}"
            return write_and_return(_report(job, status="FAILED", error=job.error_message))

        parsed = result.transactions
        positions = result.positions
        section_counts = result.section_counts
        parser_meta = result.parser_meta

        warnings = validate_transactions(parsed)
        job.status = "VALIDATED"
        job.updated_at = _now()
        db.add(job)
        db.commit()

        inserted = 0
        duplicates = 0

        for tx in parsed:
            fp = _fingerprint(job.account_id, tx)
            tx_asset_id: int | None = None
            tx_quantity: float | None = None
            if tx.get("type") in {"BUY", "SELL"} and tx.get("symbol") and tx.get("currency"):
                tx_asset_id = _get_or_create_asset(
                    db,
                    {
                        "symbol": tx.get("symbol"),
                        "name": tx.get("symbol"),
                        "asset_class": tx.get("asset_class") or "STOCK",
                        "currency": tx.get("currency"),
                        "home_country": tx.get("home_country"),
                    },
                )
                raw_quantity = tx.get("quantity")
                if raw_quantity is not None and str(raw_quantity).strip() != "":
                    try:
                        tx_quantity = abs(float(raw_quantity))
                    except (TypeError, ValueError):
                        tx_quantity = None

            exists = db.execute(
                text(
                    """
                    SELECT 1 FROM transactions
                    WHERE account_id = :account_id
                      AND ts = :ts
                      AND type = :type
                      AND amount = :amount
                      AND currency = :currency
                      AND COALESCE(merchant_counterparty, '') = :merchant
                      AND COALESCE(category, '') = :category
                    LIMIT 1
                    """
                ),
                {
                    "account_id": job.account_id,
                    "ts": tx["ts"],
                    "type": tx["type"],
                    "amount": tx["amount"],
                    "currency": tx["currency"],
                    "merchant": tx.get("merchant_counterparty", "") or "",
                    "category": tx.get("category", "") or "",
                },
            ).fetchone()
            if exists:
                duplicates += 1
                continue

            db.execute(
                text(
                    """
                    INSERT INTO transactions (
                      ts,
                      account_id,
                      type,
                      amount,
                      currency,
                      asset_id,
                      quantity,
                      category,
                      merchant_counterparty,
                      source,
                      notes
                    )
                    VALUES (
                      :ts,
                      :account_id,
                      :type,
                      :amount,
                      :currency,
                      :asset_id,
                      :quantity,
                      :category,
                      :merchant,
                      :source,
                      :notes
                    )
                    """
                ),
                {
                    "ts": tx["ts"],
                    "account_id": job.account_id,
                    "type": tx["type"],
                    "amount": tx["amount"],
                    "currency": tx["currency"],
                    "asset_id": tx_asset_id,
                    "quantity": tx_quantity,
                    "category": tx.get("category"),
                    "merchant": tx.get("merchant_counterparty"),
                    "source": job.platform,
                    "notes": _compose_notes(fp, tx.get("notes")),
                },
            )
            inserted += 1

        # --- Canonical adapter (Phase 5) ---
        # For every parser that emits positions, canonical write is now the
        # authoritative blocking path.  Legacy positions are no longer written
        # for canonical-covered parsers.
        #
        # Decision tree by parser_key:
        #   "portfolio_positions"  → run_upload_canonical_adapter (blocking)
        #   "account_balance"      → run_upload_balance_canonical_adapter (blocking)
        #   "none"                 → parser confirmed no positions; skip
        #   None (unregistered)    → fail if positions present; no silent fallback
        canonical_target = parser_canonical_target(parser_key)

        # Guard: unregistered parser that emits positions must fail closed.
        if canonical_target is None and positions:
            job.status = "FAILED"
            job.error_message = (
                f"canonical_adapter_missing: parser '{parser_key}' emits "
                f"{len(positions)} position(s) but has no canonical adapter registered. "
                "Register the parser in PARSER_CANONICAL_REGISTRY before merging."
            )
            return write_and_return(_report(job, status="FAILED", error=job.error_message))

        # Legacy positions are retired as authoritative storage.  Any parser
        # that emits positions must either route to a canonical adapter or fail
        # closed above; there is intentionally no legacy fallback write here.
        positions_inserted = 0

        # Canonical write (blocking for position-producing parsers).
        # Must succeed before the job is marked IMPORTED.
        canonical_result: dict | None = None
        canonical_warning: str | None = None
        canonical_positions_written = 0
        canonical_balances_written = 0

        if canonical_target == "portfolio_positions":
            from app.portfolio.ibkr_flex import is_ibkr_flex_cutover_active
            flex_cutover = is_ibkr_flex_cutover_active(db, int(job.account_id))
            canonical_result = run_upload_canonical_adapter(
                db,
                current_user_id=_get_account_user_id(db, int(job.account_id)),
                legacy_account_id=int(job.account_id),
                platform_code=job.platform,
                parse_result=result,
                stored_path=job.stored_path,
                file_sha256=job.file_sha256,
                is_ibkr_flex_cutover_active=flex_cutover,
            )
            canonical_positions_written = (canonical_result or {}).get("counts", {}).get("positions", 0)

        elif canonical_target == "account_balance":
            canonical_result = run_upload_balance_canonical_adapter(
                db,
                account_id=int(job.account_id),
                import_job_id=int(job.id),
                parse_result=result,
            )
            canonical_balances_written = (canonical_result or {}).get("counts", {}).get("balances", 0)

        db.commit()
        job.status = "IMPORTED"
        job.updated_at = _now()
        db.add(job)
        db.commit()

        preview = [_serialize_tx(tx) for tx in parsed[:10]]
        report = _report(
            job,
            status="IMPORTED",
            signature_debug=signature_debug,
            section_summary=[{"section": k, "rows": v} for k, v in section_counts.items()],
            warnings=warnings,
            counts={
                "rows_total": sum(section_counts.values()),
                "transactions_parsed": len(parsed),
                "transactions_inserted": inserted,
                "duplicates_skipped": duplicates,
                "positions_parsed": len(positions),
                "positions_inserted": positions_inserted,
                "canonical_positions_written": canonical_positions_written,
                "canonical_balances_written": canonical_balances_written,
            },
            preview=preview,
            parser_meta=parser_meta,
            canonical_result=canonical_result,
            canonical_warning=canonical_warning,
        )
        return write_and_return(report)
    except Exception as exc:  # noqa: BLE001
        job.status = "FAILED"
        job.error_message = str(exc)
        return write_and_return(_report(job, status="FAILED", error=str(exc), error_class=exc.__class__.__name__))


def _get_account_user_id(db: Session, account_id: int) -> int:
    """Return the user_id for an account, falling back to 1 for legacy null-ownership."""
    row = db.execute(
        text("SELECT user_id FROM accounts WHERE id = :account_id LIMIT 1"),
        {"account_id": account_id},
    ).fetchone()
    if row and row[0] is not None:
        return int(row[0])
    return 1


def _report(
    job: ImportJob,
    status: str,
    signature_debug: dict | None = None,
    section_summary: dict | list | None = None,
    warnings: list | None = None,
    counts: dict | None = None,
    preview: List[Dict[str, Any]] | None = None,
    parser_meta: dict | None = None,
    error: str | None = None,
    error_class: str | None = None,
    canonical_result: dict | None = None,
    canonical_warning: str | None = None,
) -> dict:
    return {
        "job_id": job.id,
        "status": status,
        "platform": job.platform,
        "account_id": job.account_id,
        "original_filename": job.original_filename,
        "stored_path": job.stored_path,
        "file_sha256": job.file_sha256,
        "format_signature": job.format_signature,
        "parser_key": job.parser_key,
        "section_summary": section_summary or [],
        "counts": counts or {
            "rows_total": 0,
            "transactions_parsed": 0,
            "transactions_inserted": 0,
            "duplicates_skipped": 0,
            "positions_parsed": 0,
            "positions_inserted": 0,
            "canonical_positions_written": 0,
            "canonical_balances_written": 0,
        },
        "validation_warnings": warnings or [],
        "preview_transactions": preview or [],
        "parser_meta": parser_meta or {},
        "signature_debug": signature_debug,
        "error_message": error,
        "error_class": error_class,
        "canonical_result": canonical_result,
        "canonical_warning": canonical_warning,
    }


def _serialize_tx(tx: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(tx)
    ts = out.get("ts")
    if hasattr(ts, "isoformat"):
        out["ts"] = ts.isoformat()
    return out
