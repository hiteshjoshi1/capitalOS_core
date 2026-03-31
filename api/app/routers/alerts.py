from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, account_scope_sql, require_current_user
from app.db.session import get_db
from app.schemas.alert import UploadReminderAlert, UploadReminderCountResponse

router = APIRouter(prefix="/alerts", tags=["alerts"], dependencies=[Depends(require_current_user)])


def _stale_days() -> int:
    try:
        return int(os.environ.get("UPLOAD_STALE_DAYS", "30"))
    except (ValueError, TypeError):
        return 30


def _to_date_str(val: object) -> str | None:
    if val is None:
        return None
    if isinstance(val, str):
        try:
            val = datetime.fromisoformat(val)
        except ValueError:
            return val
    if isinstance(val, datetime):
        return val.date().isoformat()
    return str(val)


def _days_since(val: object) -> int:
    """Return number of days between val and today (UTC).  Returns 0 if val is None."""
    if val is None:
        return 0
    if isinstance(val, str):
        try:
            val = datetime.fromisoformat(val)
        except ValueError:
            return 0
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        today = datetime.now(tz=timezone.utc).date()
        return (today - val.date()).days
    return 0


def _fetch_stale_accounts(db: Session, stale_days: int, current_user_id: int) -> List[UploadReminderAlert]:
    sql = text(
        """
        SELECT
            a.id            AS account_id,
            a.name          AS account_name,
            COALESCE(p.code, a.platform) AS platform,
            a.account_type,
            MAX(ij.created_at) AS last_upload_date,
            MAX(t.ts)          AS last_transaction_date
        FROM accounts AS a
        LEFT JOIN platforms AS p ON p.id = a.platform_id
        INNER JOIN import_jobs AS ij
            ON ij.account_id = a.id AND ij.status = 'IMPORTED'
        LEFT JOIN transactions AS t ON t.account_id = a.id
        WHERE """
        + account_scope_sql("a")
        + """
        GROUP BY a.id, a.name, a.platform, a.account_type, p.code
        ORDER BY a.name
        """
    )
    rows = db.execute(sql, {"current_user_id": current_user_id}).mappings().fetchall()

    alerts: List[UploadReminderAlert] = []
    for row in rows:
        days = _days_since(row["last_upload_date"])
        if days < stale_days:
            continue

        last_upload_str = _to_date_str(row["last_upload_date"])
        last_tx_str = _to_date_str(row["last_transaction_date"])

        if last_tx_str:
            msg = (
                f"Upload the latest statement for {row['account_name']} "
                f"({row['platform']}). Last upload was {last_upload_str} "
                f"and last transaction tracked was {last_tx_str}."
            )
        else:
            msg = (
                f"Upload the latest statement for {row['account_name']} "
                f"({row['platform']}). Last upload was {last_upload_str}."
            )

        alerts.append(
            UploadReminderAlert(
                account_id=row["account_id"],
                account_name=row["account_name"],
                platform=row["platform"],
                account_type=row["account_type"],
                last_upload_date=last_upload_str,
                last_transaction_date=last_tx_str,
                days_since_upload=days,
                message=msg,
            )
        )

    return alerts


@router.get("/upload-reminders", response_model=List[UploadReminderAlert])
def get_upload_reminders(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
) -> List[UploadReminderAlert]:
    """Return accounts whose last successful import is older than UPLOAD_STALE_DAYS."""
    return _fetch_stale_accounts(db, _stale_days(), current_user.id)


@router.get("/upload-reminders/count", response_model=UploadReminderCountResponse)
def get_upload_reminders_count(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
) -> UploadReminderCountResponse:
    """Return the number of stale-upload alerts (for the nav badge)."""
    alerts = _fetch_stale_accounts(db, _stale_days(), current_user.id)
    return UploadReminderCountResponse(count=len(alerts))
