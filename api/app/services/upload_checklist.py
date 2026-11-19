"""This month's uploads (#449, V23 from #432): one checklist of the statements to upload.

The sources are the caller's upload kinds from source freshness (#252): broker, bank, card
and other account statements; Flex, wallets and quote/FX feeds refresh themselves, and a
source set to ``off`` isn't expected. A source is **done** for the calendar month (app
timezone) once either:

- a statement for it was imported this month (an IMPORTED, not removed, import job created
  this month): uploading October's statement in November ticks November's box, although
  its data is dated October; or
- it already has data dated this month (e.g. a mid-month export).

Read-only; the Inbox's "This month's uploads: N of M" item and the Upload page's checklist
both come from here, so they can't disagree.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import account_scope_sql
from app.core.clock import app_timezone, app_today
from app.services.source_freshness import (
    KIND_ACCOUNT_STATEMENT,
    KIND_BANK_STATEMENT,
    KIND_BROKER_STATEMENT,
    KIND_CARD_STATEMENT,
    source_freshness,
)
from app.valuation.clock import _normalize_ts

UPLOAD_KINDS = (KIND_BROKER_STATEMENT, KIND_BANK_STATEMENT, KIND_CARD_STATEMENT, KIND_ACCOUNT_STATEMENT)


def _last_imports(db: Session, user_id: int) -> dict[int, Any]:
    """Each of the caller's accounts' newest successful, not removed, import (its created_at)."""
    rows = db.execute(
        text(
            "SELECT ij.account_id, MAX(ij.created_at) FROM import_jobs ij JOIN accounts a ON a.id = ij.account_id "
            "WHERE ij.status = 'IMPORTED' AND ij.removed_at IS NULL AND "
            + account_scope_sql("a")
            + " GROUP BY ij.account_id"
        ),
        {"current_user_id": user_id},
    ).fetchall()
    return {int(account_id): newest for account_id, newest in rows}


def _local_date(value: Any) -> Optional[date]:
    ts = _normalize_ts(value)
    return ts.astimezone(app_timezone()).date() if ts is not None else None


def monthly_upload_checklist(
    db: Session, user_id: int, today: Optional[date] = None, freshness: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """``{"month", "done", "total", "sources": [...]}``; sources not done first, then by label.
    ``freshness``: an already computed ``source_freshness`` result (the Inbox has one)."""
    today = today or app_today()
    first = today.replace(day=1)
    freshness = freshness if freshness is not None else source_freshness(db, user_id, today)
    imports = _last_imports(db, user_id)
    sources = []
    for row in freshness["sources"]:
        if row["kind"] not in UPLOAD_KINDS or row["cadence"] == "off":
            continue
        account_id = int(str(row["source_key"]).split(":", 1)[1])
        imported_on = _local_date(imports.get(account_id))
        last_data = date.fromisoformat(row["last_data_date"]) if row.get("last_data_date") else None
        done = (imported_on is not None and imported_on >= first) or (last_data is not None and last_data >= first)
        sources.append({
            "source_key": row["source_key"],
            "account_id": account_id,
            "label": row["label"],
            "platform": row.get("platform"),
            "kind": row["kind"],
            "done": done,
            "last_import_date": imported_on.isoformat() if imported_on else None,
            "last_data_date": row.get("last_data_date"),
            "overdue": bool(row.get("overdue")),
        })
    sources.sort(key=lambda s: (s["done"], s["label"].lower(), s["source_key"]))
    return {
        "month": first.strftime("%Y-%m"),
        "done": sum(1 for s in sources if s["done"]),
        "total": len(sources),
        "sources": sources,
    }
