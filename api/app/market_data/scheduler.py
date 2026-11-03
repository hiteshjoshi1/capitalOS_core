from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import bindparam, text

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
from app import fx
from app.db.session import SessionLocal
from app.market_data.service import configured_exchanges, run_all_exchanges

logger = logging.getLogger("capitalos.market_data")
_scheduler: BackgroundScheduler | None = None
_retry_gates: dict[str, RetryGate] = {}

_DEFAULT_WINDOWS = {
    "asia_close": ("Asia/Singapore", 18, 45, ("NSE", "HKEX", "SGX")),
    "us_close": ("America/New_York", 17, 45, ("US",)),
}


def _window_schedule(window_name: str) -> tuple[str, int, int]:
    tz, hour, minute, _ = _DEFAULT_WINDOWS[window_name]
    hour, minute = parse_hhmm(os.getenv(f"STOCK_REFRESH_{window_name.upper()}"), (hour, minute))
    return tz, hour, minute


def _latest_success_for_exchanges(exchanges: list[str]) -> datetime | None:
    """The oldest of each exchange's newest successful run: a window has run once
    every one of its exchanges has. None if any exchange never succeeded."""
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT exchange_code, MAX(finished_at) AS finished_at
                FROM market_data_runs
                WHERE status IN ('success', 'partial')
                  AND finished_at IS NOT NULL
                  AND exchange_code IN :exchanges
                GROUP BY exchange_code
                """
            ).bindparams(bindparam("exchanges", expanding=True)),
            {"exchanges": list(exchanges)},
        ).fetchall()
    finally:
        db.close()
    latest = {str(row[0]): coerce_utc(row[1]) for row in rows}
    if any(latest.get(exchange) is None for exchange in exchanges):
        return None
    return min(value for value in latest.values() if value is not None)


def _window_plan(exchanges: list[str]) -> list[tuple[str, str, int, int, list[str]]]:
    """(window name, tz, hour, minute, exchanges) for every configured exchange:
    the grouped close windows, then a 00:05 local fallback for the rest."""
    plan: list[tuple[str, str, int, int, list[str]]] = []
    scheduled: set[str] = set()
    for window_name, (_tz, _hour, _minute, members) in _DEFAULT_WINDOWS.items():
        window_exchanges = [exchange for exchange in exchanges if exchange in members]
        if not window_exchanges:
            continue
        tz_name, hour, minute = _window_schedule(window_name)
        plan.append((window_name, tz_name, hour, minute, window_exchanges))
        scheduled.update(window_exchanges)
    for exchange in exchanges:
        if exchange not in scheduled:
            plan.append((f"{exchange.lower()}_fallback", os.getenv("TZ", "UTC"), 0, 5, [exchange]))
    return plan


def _run_due_windows() -> None:
    """Every check interval: refresh each window whose exchanges haven't all had a
    successful run since the window's most recent scheduled time (#112)."""
    now = datetime.now(tz=timezone.utc)
    for window_name, tz_name, hour, minute, window_exchanges in _window_plan(configured_exchanges()):
        due = most_recent_due(now, hour, minute, ZoneInfo(tz_name))
        try:
            if not run_is_due(_latest_success_for_exchanges(window_exchanges), due):
                continue
        except Exception as exc:  # noqa: BLE001
            logger.exception("stock_refresh_last_run_check_failed", extra={"error_class": exc.__class__.__name__})
            continue
        gate = _retry_gates.setdefault(window_name, RetryGate())
        if not gate.may_attempt(now):
            continue
        succeeded = False
        try:
            _run_window(window_name, window_exchanges)
            succeeded = not run_is_due(_latest_success_for_exchanges(window_exchanges), due)
        except Exception as exc:  # noqa: BLE001
            logger.exception("stock_refresh_due_check_failed", extra={"error_class": exc.__class__.__name__})
        finally:
            gate.record(now, succeeded=succeeded)


def _run_window(window_name: str, exchanges: list[str]) -> None:
    with job_context():
        started = time.perf_counter()
        db = SessionLocal()
        try:
            logger.info(
                "quote_refresh_started",
                extra={"event": "quote_refresh_started", "provider": "market_data", "window": window_name, "rows": len(exchanges)},
            )
            result = run_all_exchanges(db, exchanges=exchanges, full_coverage=True)
            exchange_results = result.get("exchanges") or []
            failed = [item for item in exchange_results if item.get("status") == "failed"]
            event_name = "quote_refresh_failed" if failed else "quote_refresh_succeeded"
            level = logger.warning if failed else logger.info
            level(
                event_name,
                extra={
                    "event": event_name,
                    "provider": "market_data",
                    "window": window_name,
                    "rows": sum(int(item.get("requested_symbols") or 0) for item in exchange_results),
                    "inserted": sum(int(item.get("upserted_rows") or 0) for item in exchange_results),
                    "skipped": sum(int(item.get("missing_symbols") or 0) for item in exchange_results),
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                },
            )
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.exception(
                "quote_refresh_failed",
                extra={
                    "event": "quote_refresh_failed",
                    "provider": "market_data",
                    "window": window_name,
                    "rows": len(exchanges),
                    "error_class": exc.__class__.__name__,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                },
            )
        finally:
            db.close()


_fx_retry_gate = RetryGate()


def _fx_fill_schedule() -> tuple[ZoneInfo, int, int]:
    """Daily FX fill (#139): after the ECB reference rates are published (~16:00
    CET), 16:30 Europe/Berlin by default (`FX_DAILY_FILL`, HH:MM)."""
    hour, minute = parse_hhmm(os.getenv("FX_DAILY_FILL"), (16, 30))
    return ZoneInfo("Europe/Berlin"), hour, minute


def _run_fx_fill_if_due() -> None:
    """Every check interval: fill fx_rates when no provider row arrived since the
    most recent scheduled time (sleep-proof catch-up, D-19 / #112)."""
    if not fx.remote_enabled():
        return
    now = datetime.now(tz=timezone.utc)
    tz, hour, minute = _fx_fill_schedule()
    due = most_recent_due(now, hour, minute, tz)
    try:
        if not run_is_due(fx.last_fill_at(), due):
            return
    except Exception as exc:  # noqa: BLE001
        logger.exception("fx_fill_last_run_check_failed", extra={"error_class": exc.__class__.__name__})
        return
    if not _fx_retry_gate.may_attempt(now):
        return
    succeeded = False
    with job_context():
        started = time.perf_counter()
        try:
            answered = fx.fill_daily()
            succeeded = not run_is_due(fx.last_fill_at(), due)
            (logger.info if succeeded else logger.warning)(
                "fx_fill_succeeded" if succeeded else "fx_fill_failed",
                extra={
                    "event": "fx_fill_succeeded" if succeeded else "fx_fill_failed",
                    "provider": ",".join(name for name, ok in answered.items() if ok) or "none",
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("fx_fill_failed", extra={"event": "fx_fill_failed", "error_class": exc.__class__.__name__})
        finally:
            _fx_retry_gate.record(now, succeeded=succeeded)


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if os.getenv("STOCK_PRICE_SCHEDULER_ENABLED", "1") != "1":
        logger.info("stock_scheduler_disabled")
        return _scheduler
    if _scheduler:
        return _scheduler

    scheduler = BackgroundScheduler(timezone=ZoneInfo("UTC"), job_defaults=JOB_DEFAULTS)
    if configured_exchanges():
        scheduler.add_job(
            _run_due_windows,
            IntervalTrigger(minutes=check_interval_minutes()),
            id="stock_refresh_due_check",
            replace_existing=True,
            next_run_time=datetime.now(tz=timezone.utc) + timedelta(seconds=5),
        )
    scheduler.add_job(
        _run_fx_fill_if_due,
        IntervalTrigger(minutes=check_interval_minutes()),
        id="fx_fill_due_check",
        replace_existing=True,
        next_run_time=datetime.now(tz=timezone.utc) + timedelta(seconds=10),
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
