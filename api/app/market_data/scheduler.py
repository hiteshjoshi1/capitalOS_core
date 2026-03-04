from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db.session import get_db
from app.market_data.service import configured_exchanges, run_exchange_refresh

logger = logging.getLogger("capitalos.market_data")
_scheduler: BackgroundScheduler | None = None

_DEFAULT_SCHEDULES = {
    "NSE": ("Asia/Kolkata", 18, 0),
    "HKEX": ("Asia/Hong_Kong", 17, 15),
    "SGX": ("Asia/Singapore", 18, 15),
    "US": ("America/New_York", 17, 30),
}


def _schedule_for(exchange_code: str) -> tuple[str, int, int]:
    exchange_code = exchange_code.upper()
    tz, hour, minute = _DEFAULT_SCHEDULES.get(exchange_code, (os.getenv("TZ", "UTC"), 0, 5))
    raw = os.getenv(f"STOCK_REFRESH_{exchange_code}")
    if raw and ":" in raw:
        h, m = raw.split(":", 1)
        try:
            hour = int(h)
            minute = int(m)
        except ValueError:
            pass
    return tz, hour, minute


def _run_exchange(exchange_code: str) -> None:
    db = next(get_db())
    try:
        started = datetime.now(tz=timezone.utc)
        result = run_exchange_refresh(db, exchange_code)
        logger.info(
            "stock_refresh_success",
            extra={
                "exchange": exchange_code,
                "result": result,
                "duration_ms": int((datetime.now(tz=timezone.utc) - started).total_seconds() * 1000),
            },
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("stock_refresh_failed", extra={"exchange": exchange_code, "error": str(exc)})
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
    for exchange in configured_exchanges():
        tz_name, hour, minute = _schedule_for(exchange)
        scheduler.add_job(
            _run_exchange,
            CronTrigger(hour=hour, minute=minute, timezone=ZoneInfo(tz_name)),
            kwargs={"exchange_code": exchange},
            id=f"stock_refresh_{exchange.lower()}",
            replace_existing=True,
        )

    scheduler.start()
    _scheduler = scheduler
    return scheduler
