from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import text

from app.core.logging import job_context
from app.crypto.refresh import refresh_wallet_snapshot
from app.db.session import get_db

logger = logging.getLogger("capitalos.crypto")
_scheduler: BackgroundScheduler | None = None


def _refresh_all_wallets():
    with job_context():
        db = next(get_db())
        try:
            rows = db.execute(
                text("SELECT id, user_id FROM crypto_wallets WHERE status = 'active'")
            ).fetchall()
            for wallet_id, user_id in rows:
                wallet_id = str(wallet_id)
                refresh_wallet_snapshot(
                    db,
                    wallet_id,
                    user_id=int(user_id) if user_id is not None else None,
                    automatic=True,
                )
        finally:
            db.close()


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if os.getenv("CRYPTO_SCHEDULER_ENABLED", "1") != "1":
        logger.info("crypto_scheduler_disabled")
        return _scheduler
    if _scheduler:
        return _scheduler
    tz = ZoneInfo(os.getenv("TZ", "Asia/Singapore"))
    hour = int(os.getenv("CRYPTO_REFRESH_HOUR_LOCAL", "0"))
    scheduler = BackgroundScheduler(timezone=tz)
    scheduler.add_job(
        _refresh_all_wallets,
        CronTrigger(hour=hour, minute=0),
        id="crypto_daily_refresh",
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    return scheduler
