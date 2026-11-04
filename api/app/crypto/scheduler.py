from __future__ import annotations

import logging
import os
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text

from app.core.catchup import JOB_DEFAULTS, RetryGate, check_interval_minutes, coerce_utc, most_recent_due, run_is_due
from app.core.job_runs import JOB_CRYPTO
from app.core.logging import job_context
from app.crypto.coinbase import coinbase_configured, ensure_coinbase_wallet
from app.crypto.ingest import should_refresh
from app.crypto.refresh import (
    OUTCOME_FAILED,
    OUTCOME_LOCKED,
    OUTCOME_PARTIAL,
    refresh_wallet_snapshot_outcome,
)
from app.db.session import get_db
from app.wealth_rollup_dirty import refresh_dirty_rollups_after_job

logger = logging.getLogger("capitalos.crypto")
_scheduler: BackgroundScheduler | None = None
_retry_gate = RetryGate()


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

    raw = os.getenv("COINBASE_USER_ID", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError as exc:
            raise RuntimeError(f"COINBASE_USER_ID={raw!r} is not a valid integer.") from exc

    # No explicit target configured. Deliberately do NOT fall back to
    # AUTH_BYPASS_USER_ID or a hardcoded default (e.g. user id 1, which is
    # the seeded demo account) — that would silently sync real Coinbase
    # holdings into whichever account happens to be user 1, including the
    # public demo user in an open-source deployment.
    raise RuntimeError(
        "Coinbase is configured (COINBASE_KEY_ID/COINBASE_KEY_SECRET set) but neither "
        "COINBASE_USERNAME nor COINBASE_USER_ID is set — refusing to guess which user "
        "owns this Coinbase account. Set one of them in .env."
    )


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


def _parse_snapshot_timestamp(value) -> datetime | None:
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


def _latest_snapshot_versions(db, wallet_id: str) -> tuple[bool, datetime | None, dict] | None:
    row = db.execute(
        text(
            """
            SELECT fetched_at, source_versions
            FROM crypto_wallet_snapshots
            WHERE wallet_id = :wallet_id
            ORDER BY as_of_date DESC, fetched_at DESC NULLS LAST, id DESC
            LIMIT 1
            """
        ),
        {"wallet_id": wallet_id},
    ).fetchone()
    if row is None:
        return None
    source_versions = {}
    if row[1]:
        try:
            source_versions = json.loads(row[1]) if isinstance(row[1], str) else row[1]
        except (TypeError, json.JSONDecodeError):
            source_versions = {}
    if not isinstance(source_versions, dict):
        source_versions = {}
    return True, _parse_snapshot_timestamp(row[0]), source_versions


def _latest_snapshot_freshness(db, wallet_id: str) -> tuple[datetime | None, datetime | None]:
    latest = _latest_snapshot_versions(db, wallet_id)
    if latest is None:
        return None, None
    _found, fetched_at, source_versions = latest
    holdings_as_of = _parse_snapshot_timestamp(source_versions.get("holdings_as_of")) or fetched_at
    price_as_of = _parse_snapshot_timestamp(source_versions.get("price_as_of")) or fetched_at
    return holdings_as_of, price_as_of


def _latest_snapshot_partial(db, wallet_id: str) -> bool:
    """The newest snapshot came from a refresh where some EVM chains failed (#156)."""
    latest = _latest_snapshot_versions(db, wallet_id)
    return bool(latest and latest[2].get("failed_chain_names"))


# Retries per daily slot for a wallet whose refresh was partial; after that the
# slot counts as done, so a chain that is down all day (or not supported) isn't
# re-fetched every retry interval. The next slot tries again.
PARTIAL_RETRY_ATTEMPTS = 3


def _partial_runs_since(db, wallet_id: str, due: datetime) -> int:
    rows = db.execute(
        text(
            """
            SELECT finished_at
            FROM job_runs
            WHERE job = :job AND scope = :scope AND status = 'partial'
            ORDER BY finished_at DESC, id DESC
            LIMIT 20
            """
        ),
        {"job": JOB_CRYPTO, "scope": f"wallet:{wallet_id}"},
    ).fetchall()
    return sum(1 for row in rows if (coerce_utc(row[0]) or due) >= due)


def _wallet_refresh_due(db, wallet_id: str, due: datetime | None = None) -> bool:
    """With `due`: not refreshed since that scheduled time. Without: older than 24h.

    A wallet whose newest snapshot is partial (some chains failed, carried
    forward) stays due, so the retry fires (#156); the retry gate spaces those
    retries out (SCHEDULER_RETRY_MINUTES), and with `due` they stop after
    PARTIAL_RETRY_ATTEMPTS partial runs since that time."""
    if _latest_snapshot_partial(db, wallet_id):
        if due is None or _partial_runs_since(db, wallet_id, due) < PARTIAL_RETRY_ATTEMPTS:
            return True
    holdings_as_of, price_as_of = _latest_snapshot_freshness(db, wallet_id)
    if due is not None:
        return run_is_due(holdings_as_of, due) or run_is_due(price_as_of, due)
    return should_refresh(holdings_as_of) or should_refresh(price_as_of)


def _refresh_hour() -> int:
    """`CRYPTO_REFRESH_HOUR_LOCAL` (0-23), midnight when unset or invalid: a bad
    value must not raise on every check (#130 4.6)."""
    raw = os.getenv("CRYPTO_REFRESH_HOUR_LOCAL", "").strip()
    try:
        hour = int(raw) if raw else 0
    except ValueError:
        logger.warning("crypto_refresh_hour_invalid", extra={"event": "crypto_refresh_hour_invalid"})
        return 0
    return hour if 0 <= hour <= 23 else 0


def _daily_due(now: datetime) -> datetime:
    tz = ZoneInfo(os.getenv("TZ", "Asia/Singapore"))
    return most_recent_due(now, _refresh_hour(), 0, tz)


def _any_wallet_due(due: datetime) -> bool:
    db = next(get_db())
    try:
        return any(_wallet_refresh_due(db, str(wallet["id"]), due) for wallet in _active_wallets(db))
    finally:
        db.close()


def _refresh_wallets(*, only_stale: bool, coinbase_only: bool = False, due: datetime | None = None) -> None:
    started = datetime.now(tz=timezone.utc)
    with job_context():
        db = next(get_db())
        try:
            try:
                rows = _active_wallets(db, coinbase_only=coinbase_only)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "crypto_refresh_config_error",
                    extra={
                        "event": "crypto_refresh_config_error",
                        "provider": "crypto",
                        "platform": "crypto",
                        "error_class": exc.__class__.__name__,
                    },
                )
                return
            refreshed = 0
            partial = 0
            failed = 0
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
                if only_stale and not _wallet_refresh_due(db, wallet_id, due):
                    skipped += 1
                    continue
                outcome = refresh_wallet_snapshot_outcome(
                    db,
                    wallet_id,
                    user_id=int(wallet["user_id"]) if wallet["user_id"] is not None else None,
                    automatic=True,
                )
                if outcome == OUTCOME_LOCKED:
                    skipped += 1
                elif outcome == OUTCOME_FAILED:
                    failed += 1
                else:
                    refreshed += 1
                    if outcome == OUTCOME_PARTIAL:
                        partial += 1
            if refreshed:
                refresh_dirty_rollups_after_job(db, "crypto_refresh")
            # A run where every attempted wallet failed is a failure, not "succeeded" (#156).
            event_name = "crypto_refresh_failed" if failed and not refreshed else "crypto_refresh_succeeded"
            (logger.warning if failed else logger.info)(
                event_name,
                extra={
                    "event": event_name,
                    "provider": "crypto",
                    "platform": "crypto",
                    "rows": len(rows),
                    "refreshed": refreshed,
                    "partial": partial,
                    "failed": failed,
                    "skipped": skipped,
                    "coinbase_only": coinbase_only,
                    "duration_ms": int((datetime.now(tz=timezone.utc) - started).total_seconds() * 1000),
                },
            )
        finally:
            db.close()


def _refresh_due_wallets():
    _refresh_wallets(only_stale=True)


def _run_if_due() -> None:
    """Every check interval: refresh wallets not refreshed since the most recent
    daily refresh time, so a refresh missed while the Mac slept runs on wake (#112)."""
    now = datetime.now(tz=timezone.utc)
    due = _daily_due(now)
    try:
        if not _any_wallet_due(due):
            return
    except Exception as exc:  # noqa: BLE001
        logger.exception("crypto_due_check_failed", extra={"error_class": exc.__class__.__name__})
        return
    if not _retry_gate.may_attempt(now):
        return
    succeeded = False
    try:
        _refresh_wallets(only_stale=True, due=due)
        succeeded = not _any_wallet_due(due)
    except Exception as exc:  # noqa: BLE001
        logger.exception("crypto_due_check_failed", extra={"error_class": exc.__class__.__name__})
    finally:
        _retry_gate.record(now, succeeded=succeeded)


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if os.getenv("CRYPTO_SCHEDULER_ENABLED", "1") != "1":
        logger.info("crypto_scheduler_disabled")
        return _scheduler
    if _scheduler:
        return _scheduler
    scheduler = BackgroundScheduler(timezone=ZoneInfo("UTC"), job_defaults=JOB_DEFAULTS)
    scheduler.add_job(
        _run_if_due,
        IntervalTrigger(minutes=check_interval_minutes()),
        id="crypto_due_check",
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
