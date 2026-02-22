from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import text

from app.crypto.ingest import ingest_wallet, upsert_snapshot, acquire_refresh_lock, release_refresh_lock
from app.db.session import get_db

logger = logging.getLogger("capitalos.crypto")
_scheduler: BackgroundScheduler | None = None


def _refresh_all_wallets():
    db = next(get_db())
    try:
        rows = db.execute(
            text("SELECT id FROM crypto_wallets WHERE status = 'active'")
        ).fetchall()
        for (wallet_id,) in rows:
            wallet_id = str(wallet_id)
            if not acquire_refresh_lock(db, wallet_id):
                continue
            started = datetime.utcnow()
            try:
                result = ingest_wallet(db, wallet_id)
                upsert_snapshot(db, wallet_id, result)
                db.commit()
                logger.info(
                    "crypto_refresh_success",
                    extra={
                        "wallet_id": wallet_id,
                        "items": len(result.items),
                        "total_usd": result.total_usd,
                        "duration_ms": int((datetime.utcnow() - started).total_seconds() * 1000),
                    },
                )
            except Exception as exc:
                db.rollback()
                logger.exception(
                    "crypto_refresh_failed",
                    extra={"wallet_id": wallet_id, "error": str(exc)},
                )
            finally:
                release_refresh_lock(db, wallet_id)
                db.commit()
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
