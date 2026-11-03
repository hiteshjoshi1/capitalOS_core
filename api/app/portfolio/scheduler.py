from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text

from app.core.catchup import (
    JOB_DEFAULTS,
    RetryGate,
    check_interval_minutes,
    coerce_utc,
    most_recent_due,
    parse_hhmm,
    run_is_due,
)
from app.core.logging import job_context
from app.db.session import SessionLocal
from app.portfolio.ibkr_flex import SOURCE_TYPE, run_ibkr_flex_import_from_config
from app.wealth_rollup_dirty import refresh_dirty_rollups_after_job

logger = logging.getLogger("capitalos.portfolio.ibkr_flex")
_scheduler: BackgroundScheduler | None = None
_retry_gate = RetryGate()

# IBKR builds day D's Flex statement a few hours after the US close, so a run at
# 08:15 SGT (evening of D in New York) still gets D-1. 18:30 SGT (early morning
# of D+1 in New York, EST or EDT) gets the latest completed trading day (#112).
DEFAULT_SCHEDULE_TIME = (18, 30)


def _cutover_date() -> date | None:
    raw = os.getenv("IBKR_FLEX_CUTOVER_DATE")
    if raw:
        return date.fromisoformat(raw)
    return None


def _schedule_time() -> tuple[str, int, int]:
    tz_name = os.getenv("IBKR_FLEX_SCHEDULER_TZ", os.getenv("TZ", "Asia/Singapore"))
    hour, minute = parse_hhmm(os.getenv("IBKR_FLEX_SCHEDULER_TIME"), DEFAULT_SCHEDULE_TIME)
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
        return coerce_utc(row[0] if row else None)
    finally:
        db.close()


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


def _run_daily_imports() -> bool:
    """Import every active IBKR Flex account. True when none failed."""
    with job_context():
        started = time.perf_counter()
        successes = 0
        failures = 0
        db = SessionLocal()
        try:
            accounts = _active_accounts(db)
            logger.info(
                "ibkr_flex_refresh_started",
                extra={"event": "ibkr_flex_refresh_started", "provider": "ibkr_flex", "platform": "IBKR", "rows": len(accounts)},
            )
            for account in accounts:
                try:
                    result = run_ibkr_flex_import_from_config(
                        db,
                        current_user_id=int(account["user_id"]),
                        legacy_account_id=int(account["legacy_account_id"]),
                        cutover_date=_cutover_date(),
                    )
                    successes += 1
                    logger.info(
                        "ibkr_flex_refresh_succeeded",
                        extra={
                            "event": "ibkr_flex_refresh_succeeded",
                            "provider": "ibkr_flex",
                            "platform": "IBKR",
                            "legacy_account_id": int(account["legacy_account_id"]),
                            "import_run_id": result.get("import_run_id"),
                            "duration_ms": int((time.perf_counter() - started) * 1000),
                            **(result.get("counts") or {}),
                        },
                    )
                except Exception as exc:  # noqa: BLE001
                    failures += 1
                    db.rollback()
                    logger.exception(
                        "ibkr_flex_refresh_failed",
                        extra={
                            "event": "ibkr_flex_refresh_failed",
                            "provider": "ibkr_flex",
                            "platform": "IBKR",
                            "legacy_account_id": int(account["legacy_account_id"]),
                            "error_class": exc.__class__.__name__,
                            "duration_ms": int((time.perf_counter() - started) * 1000),
                        },
                    )
            if failures:
                logger.warning(
                    "ibkr_flex_refresh_failed",
                    extra={
                        "event": "ibkr_flex_refresh_failed",
                        "provider": "ibkr_flex",
                        "platform": "IBKR",
                        "rows": len(accounts),
                        "inserted": successes,
                        "skipped": failures,
                        "duration_ms": int((time.perf_counter() - started) * 1000),
                    },
                )
            else:
                logger.info(
                    "ibkr_flex_refresh_succeeded",
                    extra={
                        "event": "ibkr_flex_refresh_succeeded",
                        "provider": "ibkr_flex",
                        "platform": "IBKR",
                        "rows": len(accounts),
                        "inserted": successes,
                        "duration_ms": int((time.perf_counter() - started) * 1000),
                    },
                )
            if successes:
                refresh_dirty_rollups_after_job(db, "ibkr_flex")
            return failures == 0
        finally:
            db.close()


def _has_active_accounts() -> bool:
    db = SessionLocal()
    try:
        return bool(_active_accounts(db))
    finally:
        db.close()


def _run_if_due() -> None:
    """Every check interval: import when no import has completed since the most
    recent scheduled time (so a run missed while the Mac slept happens on wake)."""
    now = datetime.now(tz=timezone.utc)
    tz_name, hour, minute = _schedule_time()
    due = most_recent_due(now, hour, minute, ZoneInfo(tz_name))
    try:
        if not run_is_due(_latest_completed_import_finished_at(), due):
            return
        if not _has_active_accounts():
            return
    except Exception as exc:  # noqa: BLE001
        logger.exception("ibkr_flex_last_run_check_failed", extra={"error_class": exc.__class__.__name__})
        return
    if not _retry_gate.may_attempt(now):
        return
    succeeded = False
    try:
        succeeded = _run_daily_imports()
    finally:
        _retry_gate.record(now, succeeded=succeeded)


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if not _scheduler_enabled():
        logger.info("ibkr_flex_scheduler_disabled")
        return _scheduler
    if _scheduler:
        return _scheduler

    scheduler = BackgroundScheduler(timezone=ZoneInfo("UTC"), job_defaults=JOB_DEFAULTS)
    scheduler.add_job(
        _run_if_due,
        IntervalTrigger(minutes=check_interval_minutes()),
        id="ibkr_flex_due_check",
        replace_existing=True,
        next_run_time=datetime.now(tz=timezone.utc) + timedelta(seconds=5),
    )
    scheduler.start()
    _scheduler = scheduler
    return scheduler
