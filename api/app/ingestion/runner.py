from __future__ import annotations

import hashlib
import os
import shutil
from datetime import datetime, timezone
from typing import Dict, Any, List

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ingestion.signature import compute_format_signature
from app.ingestion.registry import lookup_parser_key
from app.ingestion.validators import validate_transactions
from app.ingestion.report import write_report
from app.ingestion.parsers.ibkr_activity_csv_v1 import parse_ibkr_activity_csv
from app.ingestion.parsers.dbs_transaction_history_csv_v1 import parse_dbs_transaction_history_csv
from app.models.import_job import ImportJob


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


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


def _snapshot_as_of() -> datetime:
    snapshot_day = int(os.getenv("SNAPSHOT_DAY", "6"))
    now = datetime.now(tz=timezone.utc)
    safe_day = min(snapshot_day, 28)
    return now.replace(day=safe_day, hour=0, minute=0, second=0, microsecond=0)


def _get_or_create_asset(db: Session, pos: Dict[str, Any]) -> int | None:
    symbol = pos.get("symbol")
    currency = pos.get("currency")
    if not symbol or not currency:
        return None
    row = db.execute(
        text(
            "SELECT id FROM assets WHERE symbol = :symbol AND quote_currency = :currency LIMIT 1"
        ),
        {"symbol": symbol, "currency": currency},
    ).fetchone()
    if row:
        return int(row[0])

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
            "asset_class": pos.get("asset_class") or "OTHER",
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
    job = db.query(ImportJob).filter(ImportJob.id == job_id).one()
    report_path = os.path.join(data_dir, "reports", f"{job.id}.json")

    def write_and_return(payload: dict) -> dict:
        write_report(report_path, payload)
        job.report_path = report_path
        job.updated_at = _now()
        db.add(job)
        db.commit()
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

        parser_key = lookup_parser_key(db, signature)
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

        job.parser_key = parser_key
        job.status = "PARSED"
        job.updated_at = _now()
        db.add(job)
        db.commit()

        delimiter = signature_debug["delimiter"]
        if parser_key == "ibkr_activity_csv_v1":
            parsed, positions, section_counts = parse_ibkr_activity_csv(job.stored_path, delimiter)
        elif parser_key == "dbs_transaction_history_csv_v1":
            parsed, positions, section_counts = parse_dbs_transaction_history_csv(job.stored_path, delimiter)
        else:
            job.status = "FAILED"
            job.error_message = f"Unsupported parser_key: {parser_key}"
            return write_and_return(_report(job, status="FAILED", error=job.error_message))

        warnings = validate_transactions(parsed)
        job.status = "VALIDATED"
        job.updated_at = _now()
        db.add(job)
        db.commit()

        inserted = 0
        duplicates = 0

        for tx in parsed:
            fp = _fingerprint(job.account_id, tx)
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
                    INSERT INTO transactions (ts, account_id, type, amount, currency, category, merchant_counterparty, source, notes)
                    VALUES (:ts, :account_id, :type, :amount, :currency, :category, :merchant, :source, :notes)
                    """
                ),
                {
                    "ts": tx["ts"],
                    "account_id": job.account_id,
                    "type": tx["type"],
                    "amount": tx["amount"],
                    "currency": tx["currency"],
                    "category": tx.get("category"),
                    "merchant": tx.get("merchant_counterparty"),
                    "source": "IBKR",
                    "notes": f"fp:{fp}",
                },
            )
            inserted += 1

        positions_inserted = 0
        if positions:
            for pos in positions:
                as_of = pos.get("as_of") or _snapshot_as_of()
                asset_id = _get_or_create_asset(db, pos)
                if asset_id is None:
                    continue
                exists_pos = db.execute(
                    text(
                        """
                        SELECT 1 FROM positions
                        WHERE account_id = :account_id
                          AND asset_id = :asset_id
                          AND as_of = :as_of
                        LIMIT 1
                        """
                    ),
                    {
                        "account_id": job.account_id,
                        "asset_id": asset_id,
                        "as_of": as_of,
                    },
                ).fetchone()
                if exists_pos:
                    db.execute(
                        text(
                            """
                            UPDATE positions
                            SET quantity = :quantity,
                                avg_cost = :avg_cost,
                                cost_basis_base = :cost_basis_base
                            WHERE account_id = :account_id
                              AND asset_id = :asset_id
                              AND as_of = :as_of
                            """
                        ),
                        {
                            "account_id": job.account_id,
                            "asset_id": asset_id,
                            "as_of": as_of,
                            "quantity": pos.get("quantity"),
                            "avg_cost": pos.get("avg_cost"),
                            "cost_basis_base": pos.get("cost_basis_base"),
                        },
                    )
                else:
                    db.execute(
                        text(
                            """
                            INSERT INTO positions (account_id, asset_id, as_of, quantity, avg_cost, cost_basis_base)
                            VALUES (:account_id, :asset_id, :as_of, :quantity, :avg_cost, :cost_basis_base)
                            """
                        ),
                        {
                            "account_id": job.account_id,
                            "asset_id": asset_id,
                            "as_of": as_of,
                            "quantity": pos.get("quantity"),
                            "avg_cost": pos.get("avg_cost"),
                            "cost_basis_base": pos.get("cost_basis_base"),
                        },
                    )
                positions_inserted += 1

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
            },
            preview=preview,
        )
        return write_and_return(report)
    except Exception as exc:  # noqa: BLE001
        job.status = "FAILED"
        job.error_message = str(exc)
        return write_and_return(_report(job, status="FAILED", error=str(exc)))


def _report(
    job: ImportJob,
    status: str,
    signature_debug: dict | None = None,
    section_summary: dict | list | None = None,
    warnings: list | None = None,
    counts: dict | None = None,
    preview: List[Dict[str, Any]] | None = None,
    error: str | None = None,
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
        },
        "validation_warnings": warnings or [],
        "preview_transactions": preview or [],
        "signature_debug": signature_debug,
        "error_message": error,
    }


def _serialize_tx(tx: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(tx)
    ts = out.get("ts")
    if hasattr(ts, "isoformat"):
        out["ts"] = ts.isoformat()
    return out
