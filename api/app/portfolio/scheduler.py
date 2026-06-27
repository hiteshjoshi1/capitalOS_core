from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import text

from app.db.session import SessionLocal
from app.portfolio.ibkr_flex import SOURCE_TYPE, run_ibkr_flex_import_from_config

logger = logging.getLogger("capitalos.portfolio.ibkr_flex")
_scheduler: BackgroundScheduler | None = None


def _cutover_date() -> date | None:
    raw = os.getenv("IBKR_FLEX_CUTOVER_DATE")
    if raw:
        return date.fromisoformat(raw)
    return None


def _schedule_time() -> tuple[str, int, int]:
    tz_name = os.getenv("IBKR_FLEX_SCHEDULER_TZ", os.getenv("TZ", "Asia/Singapore"))
    raw = os.getenv("IBKR_FLEX_SCHEDULER_TIME", "08:15")
    hour, minute = 8, 15
    if ":" in raw:
        h, m = raw.split(":", 1)
        try:
            hour = int(h)
            minute = int(m)
        except ValueError:
            pass
    return tz_name, hour, minute


def _scheduler_enabled() -> bool:
    raw = os.getenv("IBKR_FLEX_SCHEDULER_ENABLED", "auto").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False

    token = os.getenv("IBKR_FLEX_TOKEN") or os.getenv("IBKR_TOKEN")
    query_id = os.getenv("IBKR_FLEX_QUERY_ID") or os.getenv("IBKR_QUERY_ID")
    return bool(token and query_id)


def _catchup_stale_after() -> timedelta:
    raw = os.getenv("IBKR_FLEX_STALE_AFTER_HOURS", "24")
    try:
        hours = float(raw)
    except ValueError:
        hours = 24.0
    return timedelta(hours=max(hours, 1.0))


def _coerce_utc(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _latest_completed_import_finished_at() -> datetime | None:
    db = SessionLocal()
    try:
        row = db.execute(
            text(
                """
                SELECT MAX(finished_at)
                FROM broker_import_runs
                WHERE platform_code = 'IBKR'
                  AND source_type = :source_type
                  AND status = 'completed'
                  AND finished_at IS NOT NULL
                """
            ),
            {"source_type": SOURCE_TYPE},
        ).fetchone()
        return _coerce_utc(row[0] if row else None)
    finally:
        db.close()


def _startup_catchup_due() -> bool:
    try:
        latest = _latest_completed_import_finished_at()
    except Exception as exc:  # noqa: BLE001
        logger.exception("ibkr_flex_last_run_check_failed", extra={"error": str(exc)})
        return True
    if latest is None:
        return True
    return datetime.now(tz=timezone.utc) - latest > _catchup_stale_after()


def _active_accounts(db) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT
              ba.legacy_account_id,
              bc.user_id
            FROM broker_accounts ba
            JOIN broker_connections bc ON bc.id = ba.connection_id
            WHERE bc.platform_code = 'IBKR'
              AND bc.connection_type = 'flex_api'
              AND bc.status = 'active'
              AND ba.status = 'active'
              AND ba.legacy_account_id IS NOT NULL
              AND bc.user_id IS NOT NULL
            ORDER BY ba.id
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def _run_daily_imports() -> None:
    db = SessionLocal()
    try:
        for account in _active_accounts(db):
            try:
                result = run_ibkr_flex_import_from_config(
                    db,
                    current_user_id=int(account["user_id"]),
                    legacy_account_id=int(account["legacy_account_id"]),
                    cutover_date=_cutover_date(),
                )
                logger.info(
                    "ibkr_flex_import_success",
                    extra={
                        "legacy_account_id": int(account["legacy_account_id"]),
                        "import_run_id": result.get("import_run_id"),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                logger.exception(
                    "ibkr_flex_import_failed",
                    extra={"legacy_account_id": int(account["legacy_account_id"]), "error": str(exc)},
                )
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if not _scheduler_enabled():
        logger.info("ibkr_flex_scheduler_disabled")
        return _scheduler
    if _scheduler:
        return _scheduler

    tz_name, hour, minute = _schedule_time()
    scheduler = BackgroundScheduler(timezone=ZoneInfo("UTC"))
    scheduler.add_job(
        _run_daily_imports,
        CronTrigger(hour=hour, minute=minute, timezone=ZoneInfo(tz_name)),
        id="ibkr_flex_daily_import",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    if _startup_catchup_due():
        scheduler.add_job(
            _run_daily_imports,
            DateTrigger(run_date=datetime.now(tz=timezone.utc) + timedelta(seconds=5)),
            id="ibkr_flex_startup_catchup",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    scheduler.start()
    _scheduler = scheduler
    return scheduler
