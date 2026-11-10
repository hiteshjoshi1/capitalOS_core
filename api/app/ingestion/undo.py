"""Remove an upload: delete exactly the rows it wrote and put back what it replaced (#180).

Every upload since migration 074 keeps an undo log in ``import_jobs.undo_json``,
written in the same transaction as its rows:

- its transactions carry ``transactions.import_job_id``;
- its balance snapshots carry ``account_balance_snapshots.import_job_id``;
- its holdings import runs carry ``broker_import_runs.import_job_id`` (their
  position and completeness rows carry the run id);
- ``replaced_rows``: rows its writes overwrote or deleted (an earlier balance for
  the same date, earlier holdings for the same date), as they were;
- ``created_authority_window_ids``: holdings authority windows it created;
- ``card_limits``: the card's limits before and after it (DBS card statements);
- ``statement_identity_linked``: it linked the account to the file's account number
  (an override replacing an earlier link keeps that link in ``replaced_rows``);
- ``affected_dates``: the dates of the facts it wrote.

Removing the job reverses each of these, marks History dirty from the earliest
affected date, and keeps the job row with status REMOVED. A job whose rows a
later upload replaced is refused until that later upload is removed (undo is a
stack per date). A job imported before 074 has no log and is refused: its
transactions can't be told apart from other uploads'.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.models.import_job import ImportJob
from app.portfolio.authority import remove_window_created_by_upload
from app.wealth_rollup_dirty import mark_rollups_dirty

UNDO_LOG_VERSION = 1

# Tables whose replaced rows an undo log may hold (restore allow-list: the table
# name is interpolated into SQL).
RESTORABLE_TABLES = frozenset(
    {
        "account_balance_snapshots",
        "portfolio_position_snapshots",
        "portfolio_data_completeness",
        "account_statement_identities",
    }
)


class RemovalRefused(Exception):
    """The upload can't be removed; nothing was changed."""

    def __init__(self, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def new_undo_log() -> dict[str, Any]:
    return {"version": UNDO_LOG_VERSION}


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    return value


def jsonable_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """A DB row as a JSON-safe dict (dates as ISO text, decimals as text)."""
    return {str(key): _jsonable(value) for key, value in dict(row).items()}


def _dialect(db: Session) -> str:
    return getattr(getattr(getattr(db, "bind", None), "dialect", None), "name", "sqlite")


def _restore_row(db: Session, table_name: str, row: dict[str, Any]) -> None:
    if table_name not in RESTORABLE_TABLES:
        raise ValueError(f"Not a restorable table: {table_name}")
    columns = [column for column in row if column.isidentifier()]
    params: dict[str, Any] = {}
    for column in columns:
        value = row[column]
        # JSON columns come back as dicts/lists on Postgres; bind them as text
        # (Postgres casts the literal to jsonb), as the writers do.
        params[column] = json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value
    db.execute(
        text(
            f"INSERT INTO {table_name} ({', '.join(columns)}) "
            f"VALUES ({', '.join(':' + column for column in columns)})"
        ),
        params,
    )


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None


def _same_value(a: Any, b: Any) -> bool:
    """Equal as numbers, or as timestamps to the second (drivers format them differently)."""
    if a is None or b is None:
        return a is None and b is None
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a)[:19].replace("T", " ") == str(b)[:19].replace("T", " ")


def card_limits_row(db: Session, account_id: int) -> dict[str, Any] | None:
    row = db.execute(
        text(
            "SELECT credit_limit, available_limit, available_limit_as_of "
            "FROM credit_card_accounts WHERE account_id = :account_id"
        ),
        {"account_id": account_id},
    ).mappings().one_or_none()
    return jsonable_row(row) if row else None


def _refuse_if_replaced_later(db: Session, job: ImportJob, run_ids: set[int]) -> None:
    later = (
        db.query(ImportJob)
        .filter(
            ImportJob.account_id == job.account_id,
            ImportJob.id > job.id,
            ImportJob.status == "IMPORTED",
        )
        .order_by(ImportJob.id)
        .all()
    )
    for other in later:
        replaced = (other.undo_json or {}).get("replaced_rows") or {}
        for rows in replaced.values():
            for row in rows:
                if row.get("import_job_id") == job.id or (
                    row.get("import_run_id") is not None and int(row["import_run_id"]) in run_ids
                ):
                    raise RemovalRefused(
                        f"Upload #{other.id} ({other.original_filename}) replaced data this upload wrote "
                        f"for the same date. Remove upload #{other.id} first. Nothing was removed."
                    )


def _delete_transactions(db: Session, job_id: int) -> tuple[int, date | None]:
    stats = db.execute(
        text("SELECT COUNT(*), MIN(ts) FROM transactions WHERE import_job_id = :job_id"),
        {"job_id": job_id},
    ).fetchone()
    count = int(stats[0] or 0) if stats else 0
    if not count:
        return 0, None
    earliest = _as_date(stats[1])
    tx_ids = "SELECT id FROM transactions WHERE import_job_id = :job_id"
    # Postgres cascades these; SQLite (tests) doesn't enforce foreign keys.
    existing = set(inspect(db.get_bind()).get_table_names())
    if "category_overrides" in existing:
        db.execute(text(f"DELETE FROM category_overrides WHERE transaction_id IN ({tx_ids})"), {"job_id": job_id})
    if "transfer_links" in existing:
        db.execute(
            text(
                f"DELETE FROM transfer_links WHERE from_transaction_id IN ({tx_ids}) "
                f"OR to_transaction_id IN ({tx_ids})"
            ),
            {"job_id": job_id},
        )
    db.execute(text("DELETE FROM transactions WHERE import_job_id = :job_id"), {"job_id": job_id})
    return count, earliest


def _in_clause(prefix: str, values: list[int]) -> tuple[str, dict[str, int]]:
    params = {f"{prefix}{i}": int(v) for i, v in enumerate(values)}
    return ", ".join(f":{name}" for name in params), params


def remove_import_job(db: Session, job: ImportJob) -> dict[str, Any]:
    """Remove ``job``'s rows and mark it REMOVED. Raises RemovalRefused (nothing changed).

    The caller has checked that the current user owns the job's account.
    """
    if job.status == "REMOVED":
        raise RemovalRefused("This upload was already removed.")
    if job.status != "IMPORTED":
        raise RemovalRefused(
            f"Only an imported upload can be removed; this one is {job.status}, so it wrote nothing."
        )
    undo = job.undo_json
    if isinstance(undo, str):
        undo = json.loads(undo)
    if not isinstance(undo, dict):
        raise RemovalRefused(
            "This upload was imported before uploads could be removed, so its transactions can't be "
            "told apart from other uploads' rows. Nothing was removed."
        )

    account_id = int(job.account_id)
    run_ids = [int(r) for r in undo.get("import_run_ids") or []]
    _refuse_if_replaced_later(db, job, set(run_ids))

    affected: list[date] = []
    counts = {
        "transactions": 0,
        "balance_snapshots": 0,
        "position_snapshots": 0,
        "restored_rows": 0,
    }

    counts["transactions"], tx_earliest = _delete_transactions(db, int(job.id))
    if tx_earliest:
        affected.append(tx_earliest)

    balance_dates = db.execute(
        text("SELECT as_of_date FROM account_balance_snapshots WHERE import_job_id = :job_id"),
        {"job_id": job.id},
    ).fetchall()
    affected.extend(d for d in (_as_date(r[0]) for r in balance_dates) if d)
    counts["balance_snapshots"] = len(balance_dates)
    db.execute(text("DELETE FROM account_balance_snapshots WHERE import_job_id = :job_id"), {"job_id": job.id})
    # A due date the upload's statement stated goes with it (#352).
    db.execute(
        text("DELETE FROM card_statement_dues WHERE import_job_id = :job_id AND source = 'statement'"),
        {"job_id": job.id},
    )

    if run_ids:
        placeholders, params = _in_clause("run", run_ids)
        position_rows = db.execute(
            text(f"SELECT COUNT(*) FROM portfolio_position_snapshots WHERE import_run_id IN ({placeholders})"),
            params,
        ).fetchone()
        counts["position_snapshots"] = int(position_rows[0] or 0) if position_rows else 0
        for table_name in ("portfolio_position_snapshots", "portfolio_data_completeness"):
            db.execute(text(f"DELETE FROM {table_name} WHERE import_run_id IN ({placeholders})"), params)
        db.execute(
            text(f"UPDATE broker_import_runs SET status = 'removed' WHERE id IN ({placeholders})"),
            params,
        )

    window_ids = [int(w) for w in undo.get("created_authority_window_ids") or []]
    for window_id in window_ids:
        remove_window_created_by_upload(db, window_id, reason=f"upload job {job.id} removed")

    if undo.get("statement_identity_linked"):
        db.execute(
            text("DELETE FROM account_statement_identities WHERE account_id = :account_id AND import_job_id = :job_id"),
            {"account_id": account_id, "job_id": job.id},
        )

    for table_name, rows in (undo.get("replaced_rows") or {}).items():
        for row in rows:
            _restore_row(db, table_name, row)
            counts["restored_rows"] += 1
            for key in ("as_of_date", "report_date"):
                restored_date = _as_date(row.get(key))
                if restored_date:
                    affected.append(restored_date)

    limits = undo.get("card_limits")
    if isinstance(limits, dict):
        before, after = limits.get("before"), limits.get("after")
        current = card_limits_row(db, account_id)
        # Put the earlier limits back only if no later statement changed them since.
        if before and after and current and all(_same_value(current.get(k), after.get(k)) for k in after):
            db.execute(
                text(
                    """
                    UPDATE credit_card_accounts
                    SET credit_limit = :credit_limit,
                        available_limit = :available_limit,
                        available_limit_as_of = :available_limit_as_of
                    WHERE account_id = :account_id
                    """
                ),
                {
                    "account_id": account_id,
                    "credit_limit": before.get("credit_limit"),
                    "available_limit": before.get("available_limit"),
                    "available_limit_as_of": before.get("available_limit_as_of"),
                },
            )
            affected.extend(d for d in (_as_date(before.get("available_limit_as_of")), _as_date(after.get("available_limit_as_of"))) if d)

    affected.extend(d for d in (_as_date(v) for v in undo.get("affected_dates") or []) if d)
    earliest = min(affected) if affected else None
    if earliest is not None:
        mark_rollups_dirty(db, earliest, account_id=account_id, reason="import_removed")

    now = datetime.now(tz=timezone.utc)
    job.status = "REMOVED"
    job.removed_at = now
    job.updated_at = now
    db.add(job)
    db.commit()
    return {
        "job_id": int(job.id),
        "status": "REMOVED",
        "account_id": account_id,
        "removed": counts,
        "history_dirty_from": earliest.isoformat() if earliest else None,
    }
