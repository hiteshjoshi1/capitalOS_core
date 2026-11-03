"""Dirty marks for the History rollups (#138).

Every write path that changes a valuation input calls ``mark_rollups_dirty``
with the earliest date it changed, inside the same transaction as the write
(so a rolled-back import leaves no mark). The History timeline recomputes the
affected ``wealth_monthly_rollups`` rows on its next read, and the IBKR/crypto
schedulers do the same right after their jobs (``app.routers.dashboard``).

Data dated D is read by every snapshot anchor on or after D (canonical reads are
``report_date <= anchor_date``; card liabilities look back up to two months), so
a row is stale when ``anchor_date >= from_date`` and it was computed from an
older generation. A change dated after the latest completed anchor can't touch
any stored row (only completed months are stored), so it records nothing.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import allow_legacy_null_ownership

logger = logging.getLogger("capitalos.wealth_rollups")

# "Everything": for changes that apply at every date (a wallet switched on or
# off, an account changing owner).
ALL_HISTORY = date(1970, 1, 1)


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _snapshot_day() -> int:
    try:
        day = int(os.getenv("SNAPSHOT_DAY", "1"))
    except ValueError:
        day = 1
    return max(1, min(day, 31))


def latest_completed_anchor_date(now: Optional[datetime] = None) -> date:
    """The newest snapshot anchor (SNAPSHOT_DAY, 00:00 UTC) at or before now.

    Mirrors dashboard._anchor_ts / _latest_completed_month_start, without
    importing the router."""
    today = (now or _utc_now()).astimezone(timezone.utc).date()
    year, month = today.year, today.month
    for _ in range(3):
        next_month = date(year + (month // 12), month % 12 + 1, 1)
        last_day = (next_month - timedelta(days=1)).day
        anchor = date(year, month, min(_snapshot_day(), last_day))
        if anchor <= today:
            return anchor
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return anchor  # pragma: no cover - unreachable: one of three months has passed


def _as_date(value: date | datetime | str | None) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _all_user_ids(db: Session) -> list[int]:
    return [int(row[0]) for row in db.execute(text("SELECT id FROM users")).fetchall()]


def _owner_user_ids(db: Session, table: str, row_id: object) -> list[int]:
    owner = db.execute(text(f"SELECT user_id FROM {table} WHERE id = :id"), {"id": row_id}).fetchone()
    if owner is None:
        return []
    if owner[0] is None:
        # Legacy unowned rows are visible to every user when that is allowed.
        return _all_user_ids(db) if allow_legacy_null_ownership() else []
    return [int(owner[0])]


def mark_rollups_dirty(
    db: Session,
    from_date: date | datetime | str | None,
    *,
    user_ids: Iterable[int] | None = None,
    account_id: int | None = None,
    wallet_id: str | None = None,
    reason: str = "",
) -> bool:
    """Record that valuation inputs changed from ``from_date`` on.

    Whose history: ``user_ids`` if given, else the owner of ``account_id`` /
    ``wallet_id``, else every user. Keeps the earliest pending date. Doesn't
    commit. Returns whether anything was marked.
    """
    changed = _as_date(from_date)
    if changed is None or changed > latest_completed_anchor_date():
        return False
    if user_ids is not None:
        targets = sorted({int(u) for u in user_ids})
    elif account_id is not None:
        targets = _owner_user_ids(db, "accounts", account_id)
    elif wallet_id is not None:
        targets = _owner_user_ids(db, "crypto_wallets", wallet_id)
    else:
        targets = _all_user_ids(db)
    if not targets:
        return False
    now = _utc_now()
    for user_id in targets:
        db.execute(
            text(
                """
                INSERT INTO wealth_rollup_dirty (user_id, from_date, generation, marked_at, reason)
                VALUES (:user_id, :from_date, 1, :now, :reason)
                ON CONFLICT (user_id) DO UPDATE SET
                  from_date = CASE
                    WHEN wealth_rollup_dirty.from_date IS NULL
                      OR EXCLUDED.from_date < wealth_rollup_dirty.from_date
                    THEN EXCLUDED.from_date
                    ELSE wealth_rollup_dirty.from_date
                  END,
                  generation = wealth_rollup_dirty.generation + 1,
                  marked_at = EXCLUDED.marked_at,
                  reason = EXCLUDED.reason
                """
            ),
            {"user_id": user_id, "from_date": changed, "now": now, "reason": reason[:200] or None},
        )
    logger.info(
        "wealth_rollups_marked_dirty",
        extra={"event": "wealth_rollups_marked_dirty", "from_date": changed.isoformat(), "users": targets, "reason": reason},
    )
    return True


def dirty_state(db: Session, user_id: int) -> tuple[Optional[date], int]:
    """(pending from_date or None, generation) for a user."""
    row = db.execute(
        text("SELECT from_date, generation FROM wealth_rollup_dirty WHERE user_id = :user_id"),
        {"user_id": user_id},
    ).fetchone()
    if row is None:
        return None, 0
    return _as_date(row[0]), int(row[1] or 0)


def dirty_user_ids(db: Session) -> list[int]:
    rows = db.execute(text("SELECT user_id FROM wealth_rollup_dirty WHERE from_date IS NOT NULL")).fetchall()
    return [int(row[0]) for row in rows]


def settle_dirty_mark(db: Session, user_id: int, generation: int) -> bool:
    """After a recompute: move the pending date to the earliest row still stale
    (any currency), or clear it. Does nothing if a newer mark arrived meanwhile
    (generation moved) or nothing changes, so a steady-state read never writes.
    Doesn't commit. Returns whether it wrote."""
    from_date, current_generation = dirty_state(db, user_id)
    if from_date is None or current_generation != generation:
        return False
    remaining = db.execute(
        text(
            """
            SELECT MIN(anchor_date) FROM wealth_monthly_rollups
            WHERE user_id = :user_id AND anchor_date >= :from_date AND input_generation < :generation
            """
        ),
        {"user_id": user_id, "from_date": from_date, "generation": generation},
    ).scalar()
    new_from = _as_date(remaining)
    if new_from == from_date:
        return False
    db.execute(
        text(
            "UPDATE wealth_rollup_dirty SET from_date = :new_from "
            "WHERE user_id = :user_id AND generation = :generation"
        ),
        {"new_from": new_from, "user_id": user_id, "generation": generation},
    )
    return True


def refresh_dirty_rollups_after_job(db: Session, job: str) -> int:
    """Scheduler hook: recompute the stale History rows right after an import
    job, so the next History read has nothing to do. Never raises: a failure
    here leaves the marks in place and the next timeline read does the work."""
    if os.getenv("WEALTH_ROLLUP_SCHEDULER_REFRESH", "1").strip().lower() in {"0", "false", "no", "off"}:
        return 0
    try:
        # The rollup computation lives with the dashboard valuation code.
        from app.routers.dashboard import refresh_dirty_wealth_rollups

        written = refresh_dirty_wealth_rollups(db)
        if written:
            logger.info(
                "wealth_rollups_refreshed",
                extra={"event": "wealth_rollups_refreshed", "job": job, "rows": written},
            )
        return written
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception(
            "wealth_rollups_refresh_failed",
            extra={"event": "wealth_rollups_refresh_failed", "job": job, "error_class": exc.__class__.__name__},
        )
        return 0


def mark_wallet_history_dirty(db: Session, wallet_id: object, reason: str) -> bool:
    """A wallet was switched on or changed owner: every snapshot it has now
    counts (or stops counting), so its whole history is affected."""
    earliest = db.execute(
        text("SELECT MIN(as_of_date) FROM crypto_wallet_snapshots WHERE wallet_id = :wallet_id"),
        {"wallet_id": wallet_id},
    ).scalar()
    if earliest is None:
        return False
    return mark_rollups_dirty(db, earliest, wallet_id=str(wallet_id), reason=reason)
