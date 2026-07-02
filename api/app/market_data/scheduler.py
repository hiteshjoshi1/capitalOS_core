from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import text

from app.core.logging import job_context
from app.db.session import SessionLocal
from app.market_data.service import configured_exchanges, run_all_exchanges

logger = logging.getLogger("capitalos.market_data")
_scheduler: BackgroundScheduler | None = None

_DEFAULT_WINDOWS = {
    "asia_close": ("Asia/Singapore", 18, 45, ("NSE", "HKEX", "SGX")),
    "us_close": ("America/New_York", 17, 45, ("US",)),
}


def _window_schedule(window_name: str) -> tuple[str, int, int]:
    tz, hour, minute, _ = _DEFAULT_WINDOWS[window_name]
    raw = os.getenv(f"STOCK_REFRESH_{window_name.upper()}")
    if raw and ":" in raw:
        h, m = raw.split(":", 1)
        try:
            hour = int(h)
            minute = int(m)
        except ValueError:
            pass
    return tz, hour, minute


def _catchup_stale_after() -> timedelta:
    raw = os.getenv("STOCK_REFRESH_STALE_AFTER_HOURS", "24")
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


def _latest_successful_run_finished_at() -> datetime | None:
    db = SessionLocal()
    try:
        row = db.execute(
            text(
                """
                SELECT MAX(finished_at)
                FROM market_data_runs
                WHERE status IN ('success', 'partial')
                  AND finished_at IS NOT NULL
                """
            )
        ).fetchone()
        return _coerce_utc(row[0] if row else None)
    finally:
        db.close()


def _startup_catchup_due() -> bool:
    try:
        latest = _latest_successful_run_finished_at()
    except Exception as exc:  # noqa: BLE001
        logger.exception("stock_refresh_last_run_check_failed", extra={"error": str(exc)})
        return True
    if latest is None:
        return True
    return datetime.now(tz=timezone.utc) - latest > _catchup_stale_after()


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


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if os.getenv("STOCK_PRICE_SCHEDULER_ENABLED", "1") != "1":
        logger.info("stock_scheduler_disabled")
        return _scheduler
    if _scheduler:
        return _scheduler

    scheduler = BackgroundScheduler(timezone=ZoneInfo("UTC"))
    exchanges = configured_exchanges()
    scheduled: set[str] = set()

    if exchanges and _startup_catchup_due():
        scheduler.add_job(
            _run_window,
            DateTrigger(run_date=datetime.now(tz=timezone.utc) + timedelta(seconds=5)),
            kwargs={"window_name": "startup_catchup", "exchanges": exchanges},
            id="stock_refresh_startup_catchup",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    for window_name, (_tz_name, _hour, _minute, members) in _DEFAULT_WINDOWS.items():
        window_exchanges = [exchange for exchange in exchanges if exchange in members]
        if not window_exchanges:
            continue
        tz_name, hour, minute = _window_schedule(window_name)
        scheduler.add_job(
            _run_window,
            CronTrigger(hour=hour, minute=minute, timezone=ZoneInfo(tz_name)),
            kwargs={"window_name": window_name, "exchanges": window_exchanges},
            id=f"stock_refresh_{window_name}",
            replace_existing=True,
        )
        scheduled.update(window_exchanges)

    for exchange in exchanges:
        if exchange in scheduled:
            continue
        tz_name = os.getenv("TZ", "UTC")
        scheduler.add_job(
            _run_window,
            CronTrigger(hour=0, minute=5, timezone=ZoneInfo(tz_name)),
            kwargs={"window_name": f"{exchange.lower()}_fallback", "exchanges": [exchange]},
            id=f"stock_refresh_{exchange.lower()}",
            replace_existing=True,
        )

    scheduler.start()
    _scheduler = scheduler
    return scheduler
