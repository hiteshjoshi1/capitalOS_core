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
from app.core.job_runs import (
    JOB_IBKR_FLEX,
    STATUS_FAILED,
    STATUS_NO_NEW_DATA,
    STATUS_SUCCESS,
    TRIGGER_SCHEDULED,
    record_job_run,
)
from app.core.logging import job_context
from app.db.session import SessionLocal
from app.portfolio.ibkr_flex import SOURCE_TYPE, IbkrFlexImportInProgress, run_ibkr_flex_import_from_config
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


# IBKR doesn't publish a newer statement on US holidays: after this many
# completed imports since the scheduled time that all returned an older
# statement, the slot counts as done (#156) instead of retrying all day.
STALE_STATEMENT_ATTEMPTS = 3


def expected_report_date(due: datetime) -> date:
    """The statement date a run at `due` should get: the last weekday before
    New York's date at that time (IBKR builds day D's statement a few hours
    after the US close). US holidays aren't known here; see
    STALE_STATEMENT_ATTEMPTS."""
    day = due.astimezone(ZoneInfo("America/New_York")).date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _as_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _completed_runs(db, legacy_account_id: int, limit: int = 20) -> list[tuple[datetime | None, date | None]]:
    """(finished_at, report_date_to) of an account's newest completed Flex imports."""
    rows = db.execute(
        text(
            """
            SELECT finished_at, report_date_to
            FROM broker_import_runs
            WHERE platform_code = 'IBKR'
              AND source_type = :source_type
              AND status = 'completed'
              AND finished_at IS NOT NULL
              AND legacy_account_id = :legacy_account_id
            ORDER BY finished_at DESC, id DESC
            LIMIT :limit
            """
        ),
        {"source_type": SOURCE_TYPE, "legacy_account_id": legacy_account_id, "limit": limit},
    ).fetchall()
    return [(coerce_utc(row[0]), _as_date(row[1])) for row in rows]


def latest_report_date(db, legacy_account_id: int) -> date | None:
    dates = [report_date for _finished, report_date in _completed_runs(db, legacy_account_id) if report_date]
    return max(dates) if dates else None


def account_import_due(db, legacy_account_id: int, due: datetime) -> bool:
    """Per account (#156): due until an import completed since `due` with a
    statement at least as new as expected_report_date(due). An account that
    failed is retried even when another account succeeded."""
    expected = expected_report_date(due)
    since = [
        report_date
        for finished_at, report_date in _completed_runs(db, legacy_account_id)
        if finished_at is not None and finished_at >= due
    ]
    if any(report_date is not None and report_date >= expected for report_date in since):
        return False
    return len(since) < STALE_STATEMENT_ATTEMPTS


def _due_accounts(due: datetime) -> list[dict]:
    db = SessionLocal()
    try:
        return [account for account in _active_accounts(db) if account_import_due(db, int(account["legacy_account_id"]), due)]
    finally:
        db.close()


def _current_due(now: datetime) -> datetime:
    tz_name, hour, minute = _schedule_time()
    return most_recent_due(now, hour, minute, ZoneInfo(tz_name))


def run_import_and_record(
    db,
    *,
    current_user_id: int,
    legacy_account_id: int,
    trigger: str,
    cutover_date: date | None = None,
    due: datetime | None = None,
) -> dict:
    """Run one account's Flex import and record it in job_runs (#156).

    success: the statement is as new as expected for the most recent scheduled
    time; no_new_data: it imported, but IBKR returned an older statement;
    failed: it raised (re-raised to the caller). A run refused because another
    import holds the account's lock isn't recorded.
    """
    started_at = datetime.now(tz=timezone.utc)
    due = due or _current_due(started_at)
    scope = f"account:{legacy_account_id}"
    previous = latest_report_date(db, legacy_account_id)
    try:
        result = run_ibkr_flex_import_from_config(
            db,
            current_user_id=current_user_id,
            legacy_account_id=legacy_account_id,
            cutover_date=cutover_date,
        )
    except IbkrFlexImportInProgress:
        raise
    except Exception as exc:
        db.rollback()
        record_job_run(
            db,
            job=JOB_IBKR_FLEX,
            scope=scope,
            trigger=trigger,
            status=STATUS_FAILED,
            started_at=started_at,
            user_id=current_user_id,
            data_as_of=previous,
            error=exc,
        )
        raise
    report_date = _as_date(result.get("report_date_to"))
    expected = expected_report_date(due)
    current = report_date is not None and report_date >= expected
    record_job_run(
        db,
        job=JOB_IBKR_FLEX,
        scope=scope,
        trigger=trigger,
        status=STATUS_SUCCESS if current else STATUS_NO_NEW_DATA,
        started_at=started_at,
        user_id=current_user_id,
        data_as_of=report_date,
        data_advanced=report_date is not None and (previous is None or report_date > previous),
        error=None if current else f"IBKR returned the statement for {report_date}, expected {expected} or later",
        details={"import_run_id": result.get("import_run_id"), "expected_report_date": expected.isoformat()},
    )
    return result


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


def _run_daily_imports(accounts: list[dict] | None = None, due: datetime | None = None) -> bool:
    """Import the given (default: every active) IBKR Flex account. True when none failed."""
    with job_context():
        started = time.perf_counter()
        successes = 0
        failures = 0
        db = SessionLocal()
        try:
            if accounts is None:
                accounts = _active_accounts(db)
            logger.info(
                "ibkr_flex_refresh_started",
                extra={"event": "ibkr_flex_refresh_started", "provider": "ibkr_flex", "platform": "IBKR", "rows": len(accounts)},
            )
            for account in accounts:
                try:
                    result = run_import_and_record(
                        db,
                        current_user_id=int(account["user_id"]),
                        legacy_account_id=int(account["legacy_account_id"]),
                        trigger=TRIGGER_SCHEDULED,
                        cutover_date=_cutover_date(),
                        due=due,
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


def _run_if_due() -> None:
    """Every check interval: import each active account that hasn't had a current
    statement imported since the most recent scheduled time (so a run missed
    while the Mac slept happens on wake). Checked per account (#156)."""
    now = datetime.now(tz=timezone.utc)
    due = _current_due(now)
    try:
        accounts = _due_accounts(due)
    except Exception as exc:  # noqa: BLE001
        logger.exception("ibkr_flex_last_run_check_failed", extra={"error_class": exc.__class__.__name__})
        return
    if not accounts:
        return
    if not _retry_gate.may_attempt(now):
        return
    succeeded = False
    try:
        succeeded = _run_daily_imports(accounts, due)
        # An import that returned an older statement leaves the account due:
        # wait the retry gap before asking IBKR again.
        succeeded = succeeded and not _due_accounts(due)
    except Exception as exc:  # noqa: BLE001
        logger.exception("ibkr_flex_last_run_check_failed", extra={"error_class": exc.__class__.__name__})
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


def stop_scheduler() -> None:
    """Stop firing jobs on API shutdown or reload (#135).

    ``wait=False`` so a reload isn't held up by a running job; an import or
    refresh cut short this way leaves a lock that the stale-lock rule takes over.
    """
    global _scheduler
    scheduler, _scheduler = _scheduler, None
    if scheduler is None:
        return
    try:
        scheduler.shutdown(wait=False)
    except Exception:  # noqa: BLE001 - shutdown must not block the others
        logger.warning("scheduler_shutdown_failed", exc_info=True)
