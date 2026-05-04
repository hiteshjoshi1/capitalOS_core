from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, List

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, account_scope_sql, require_current_user
from app.db.session import get_db
from app.models.rag import RealtimeEvent
from app.schemas.alert import (
    SystemNotification,
    UnifiedAlertsResponse,
    UploadReminderAlert,
    UploadReminderCountResponse,
)
from app.services.alerts import prune_old_realtime_events

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


def _to_iso_str(val: object) -> str:
    """Convert a value to a full ISO datetime string."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return val.isoformat()
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


def _parse_month_start(month: str | None) -> datetime | None:
    if not month:
        return None
    try:
        return datetime.strptime(f"{month}-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _fetch_stale_accounts(
    db: Session,
    stale_days: int,
    current_user_id: int,
    month: str | None = None,
) -> List[UploadReminderAlert]:
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

    month_start = _parse_month_start(month)
    alerts: List[UploadReminderAlert] = []
    for row in rows:
        days = _days_since(row["last_upload_date"])
        if month_start is not None:
            last_upload_value = row["last_upload_date"]
            if isinstance(last_upload_value, str):
                try:
                    last_upload_value = datetime.fromisoformat(last_upload_value)
                except ValueError:
                    last_upload_value = None
            if isinstance(last_upload_value, datetime) and last_upload_value.tzinfo is None:
                last_upload_value = last_upload_value.replace(tzinfo=timezone.utc)
            if isinstance(last_upload_value, datetime) and last_upload_value >= month_start:
                continue
        elif days < stale_days:
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


def _format_system_notification_message(event: RealtimeEvent) -> str:
    """Format a human-readable message for a system notification from a realtime event."""
    payload: Any = event.payload or {}
    author = payload.get("author", {}) if isinstance(payload, dict) else {}
    author_name: str = author.get("name") or event.author_id or "Unknown author"
    batch = payload.get("batch", {}) if isinstance(payload, dict) else {}
    source_info = payload.get("source", {}) if isinstance(payload, dict) else {}
    job_info = payload.get("job", {}) if isinstance(payload, dict) else {}
    event_name = event.event_name

    if event_name == "batch_submitted":
        source_count = batch.get("source_count", "?")
        return f"Ingestion batch started for {author_name}: {source_count} sources queued."
    if event_name == "source_queued":
        url = source_info.get("url", "source")
        return f"Source queued for ingestion for {author_name}: {url}"
    if event_name == "source_running":
        url = source_info.get("url", "source")
        return f"Ingestion in progress for {author_name}: {url}"
    if event_name == "source_ingested":
        url = source_info.get("url", "source")
        return f"Successfully ingested source for {author_name}: {url}"
    if event_name == "source_failed":
        url = source_info.get("url", "source")
        failure = (
            payload.get("failure_reason") if isinstance(payload, dict) else None
        ) or job_info.get("error") or "unknown error"
        return f"Ingestion failed for {author_name}: {url}. Reason: {failure}"
    if event_name == "batch_completed":
        completed = batch.get("completed_source_count", "?")
        failed = batch.get("failed_source_count", 0)
        total = batch.get("source_count", "?")
        if failed:
            return (
                f"Ingestion batch completed for {author_name}: "
                f"{completed}/{total} sources ingested, {failed} failed."
            )
        return f"Ingestion batch completed for {author_name}: {completed}/{total} sources ingested."
    return f"Author ingestion event: {event_name} for {author_name} (status: {event.status})"


@router.get("/upload-reminders", response_model=List[UploadReminderAlert])
def get_upload_reminders(
    month: str | None = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
) -> List[UploadReminderAlert]:
    """Return accounts whose last successful import is older than UPLOAD_STALE_DAYS."""
    return _fetch_stale_accounts(db, _stale_days(), current_user.id, month)


@router.get("/upload-reminders/count", response_model=UploadReminderCountResponse)
def get_upload_reminders_count(
    month: str | None = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
) -> UploadReminderCountResponse:
    """Return the number of stale-upload alerts (for the nav badge)."""
    alerts = _fetch_stale_accounts(db, _stale_days(), current_user.id, month)
    return UploadReminderCountResponse(count=len(alerts))


@router.get("/notifications", response_model=UnifiedAlertsResponse)
def get_notifications(
    month: str | None = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
) -> UnifiedAlertsResponse:
    """Return a unified read model: upload-reminder alerts + recent system notifications.

    This is the primary endpoint for the Alerts page and the sidebar badge count.
    Suitable for initial hydration; the frontend should then subscribe to the
    ``author-ingestion`` realtime topic via WebSocket for live updates.
    """
    reminders = _fetch_stale_accounts(db, _stale_days(), current_user.id, month)

    events = (
        db.query(RealtimeEvent)
        .filter(RealtimeEvent.user_id == current_user.id)
        .order_by(RealtimeEvent.created_at.desc())
        .limit(100)
        .all()
    )

    system_notifications: List[SystemNotification] = []
    for event in events:
        payload = event.payload or {}
        # Payload may be a JSON string when using raw SQLite in tests
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (ValueError, TypeError):
                payload = {}

        system_notifications.append(
            SystemNotification(
                id=str(event.id),
                topic=event.topic,
                event_name=event.event_name,
                author_id=event.author_id,
                source_id=str(event.source_id) if event.source_id else None,
                job_id=str(event.job_id) if event.job_id else None,
                batch_id=str(event.batch_id) if event.batch_id else None,
                status=event.status,
                message=_format_system_notification_message(event),
                created_at=_to_iso_str(event.created_at),
                payload=payload,
            )
        )

    return UnifiedAlertsResponse(
        upload_reminders=reminders,
        system_notifications=system_notifications,
        total_count=len(reminders) + len(system_notifications),
    )


@router.post("/prune", status_code=200)
def prune_notifications(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
) -> dict:
    """Prune realtime_events older than 6 months for all users (admin action).

    This can be called by an admin or a scheduled job to enforce the 6-month
    retention policy for user-visible system notifications.
    """
    deleted = prune_old_realtime_events(db)
    return {"deleted": deleted, "retention_days": 180}
