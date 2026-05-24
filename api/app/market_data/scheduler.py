from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db.session import get_db
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


def _run_window(window_name: str, exchanges: list[str]) -> None:
    db = next(get_db())
    try:
        started = datetime.now(tz=timezone.utc)
        result = run_all_exchanges(db, exchanges=exchanges, full_coverage=True)
        logger.info(
            "stock_refresh_success",
            extra={
                "window": window_name,
                "exchanges": exchanges,
                "result": result,
                "duration_ms": int((datetime.now(tz=timezone.utc) - started).total_seconds() * 1000),
            },
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception(
            "stock_refresh_failed",
            extra={"window": window_name, "exchanges": exchanges, "error": str(exc)},
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
