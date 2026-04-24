"""Alert-related service utilities including notification retention pruning."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

RETENTION_DAYS = 180  # 6 months


def prune_old_realtime_events(db: Session) -> int:
    """Delete realtime_events older than RETENTION_DAYS (180 days / ~6 months).

    Returns the number of rows deleted.  Safe to call on both SQLite (tests)
    and PostgreSQL (production) because we pass the cutoff as an ISO string.
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=RETENTION_DAYS)
    cutoff_str = cutoff.isoformat()
    result = db.execute(
        text("DELETE FROM realtime_events WHERE created_at < :cutoff"),
        {"cutoff": cutoff_str},
    )
    deleted: int = result.rowcount
    if deleted:
        log.info(
            "Pruned %d expired realtime_events older than %s days (cutoff=%s)",
            deleted,
            RETENTION_DAYS,
            cutoff_str,
        )
    db.commit()
    return deleted
