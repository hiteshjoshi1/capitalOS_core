from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import text

from app.core.logging import job_context
from app.crypto.coinbase import coinbase_configured, ensure_coinbase_wallet
from app.crypto.ingest import should_refresh
from app.crypto.refresh import refresh_wallet_snapshot
from app.db.session import get_db

logger = logging.getLogger("capitalos.crypto")
_scheduler: BackgroundScheduler | None = None


def _coinbase_enabled() -> bool:
    raw = os.getenv("COINBASE_SCHEDULER_ENABLED", "auto").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return coinbase_configured()


def _coinbase_user_id(db) -> int:
    username = os.getenv("COINBASE_USERNAME", "").strip()
    if username:
        row = db.execute(
            text(
                """
                SELECT id
                FROM users
                WHERE LOWER(username) = LOWER(:username)
                  AND COALESCE(is_active, TRUE) = TRUE
                LIMIT 1
                """
            ),
            {"username": username},
        ).fetchone()
        if row is None:
            raise RuntimeError(f"COINBASE_USERNAME={username!r} does not match an active user.")
        return int(row[0])

    raw = os.getenv("COINBASE_USER_ID", os.getenv("AUTH_BYPASS_USER_ID", "1"))
    try:
        return int(raw)
    except ValueError:
        return 1


def _ensure_configured_exchange_sources(db) -> None:
    if _coinbase_enabled():
        ensure_coinbase_wallet(db, _coinbase_user_id(db))


def _active_wallets(db, *, coinbase_only: bool = False) -> list[dict]:
    _ensure_configured_exchange_sources(db)
    where = "status = 'active'"
    if coinbase_only:
        where += " AND chain_type = 'exchange' AND chain = 'coinbase'"
    rows = db.execute(
        text(f"SELECT id, user_id FROM crypto_wallets WHERE {where}")
    ).mappings().all()
    return [dict(row) for row in rows]


def _latest_snapshot_fetched_at(db, wallet_id: str) -> datetime | None:
    row = db.execute(
        text(
            """
            SELECT fetched_at
            FROM crypto_wallet_snapshots
            WHERE wallet_id = :wallet_id
            ORDER BY as_of_date DESC, fetched_at DESC NULLS LAST, id DESC
            LIMIT 1
            """
        ),
        {"wallet_id": wallet_id},
    ).fetchone()
    value = row[0] if row else None
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _startup_catchup_due() -> bool:
    db = next(get_db())
    try:
        wallets = _active_wallets(db, coinbase_only=True)
        if not wallets:
            return False
        return any(should_refresh(_latest_snapshot_fetched_at(db, str(wallet["id"]))) for wallet in wallets)
    except Exception as exc:  # noqa: BLE001
        logger.exception("crypto_startup_catchup_check_failed", extra={"error_class": exc.__class__.__name__})
        return True
    finally:
        db.close()


def _refresh_wallets(*, only_stale: bool, coinbase_only: bool = False) -> None:
    started = datetime.now(tz=timezone.utc)
    with job_context():
        db = next(get_db())
        try:
            rows = _active_wallets(db, coinbase_only=coinbase_only)
            refreshed = 0
            skipped = 0
            logger.info(
                "crypto_refresh_started",
                extra={
                    "event": "crypto_refresh_started",
                    "provider": "crypto",
                    "platform": "crypto",
                    "rows": len(rows),
                    "only_stale": only_stale,
                    "coinbase_only": coinbase_only,
                },
            )
            for wallet in rows:
                wallet_id = str(wallet["id"])
                if only_stale and not should_refresh(_latest_snapshot_fetched_at(db, wallet_id)):
                    skipped += 1
                    continue
                if refresh_wallet_snapshot(
                    db,
                    wallet_id,
                    user_id=int(wallet["user_id"]) if wallet["user_id"] is not None else None,
                    automatic=True,
                ):
                    refreshed += 1
            logger.info(
                "crypto_refresh_succeeded",
                extra={
                    "event": "crypto_refresh_succeeded",
                    "provider": "crypto",
                    "platform": "crypto",
                    "rows": len(rows),
                    "refreshed": refreshed,
                    "skipped": skipped,
                    "coinbase_only": coinbase_only,
                    "duration_ms": int((datetime.now(tz=timezone.utc) - started).total_seconds() * 1000),
                },
            )
        finally:
            db.close()


def _refresh_all_wallets():
    _refresh_wallets(only_stale=False)


def _refresh_due_wallets():
    _refresh_wallets(only_stale=True, coinbase_only=True)


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
        max_instances=1,
        coalesce=True,
    )
    if _startup_catchup_due():
        scheduler.add_job(
            _refresh_due_wallets,
            DateTrigger(run_date=datetime.now(tz=timezone.utc) + timedelta(seconds=5)),
            id="crypto_startup_catchup",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    scheduler.start()
    _scheduler = scheduler
    return scheduler
