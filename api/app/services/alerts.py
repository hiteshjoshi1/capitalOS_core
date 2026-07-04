"""Alert-related service utilities including notification retention pruning."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 180  # 6 months for non-alert realtime events.
AUTHOR_INGESTION_TOPIC = "author-ingestion"
AUTHOR_INGESTION_RETENTION_DAYS = 1


def prune_old_realtime_events(db: Session) -> int:
    """Delete expired realtime_events.

    Author-ingestion events back the user-visible system notifications on the
    Alerts page, so they are intentionally short-lived. Other realtime event
    topics retain the older default retention window.

    Returns the number of rows deleted.  Safe to call on both SQLite (tests)
    and PostgreSQL (production) because SQLAlchemy binds datetime cutoffs.
    """
    now = datetime.now(tz=timezone.utc)
    author_ingestion_cutoff = now - timedelta(days=AUTHOR_INGESTION_RETENTION_DAYS)
    default_cutoff = now - timedelta(days=DEFAULT_RETENTION_DAYS)
    result = db.execute(
        text(
            """
            DELETE FROM realtime_events
            WHERE (
                topic = :author_ingestion_topic
                AND created_at < :author_ingestion_cutoff
            )
            OR (
                topic <> :author_ingestion_topic
                AND created_at < :default_cutoff
            )
            """
        ),
        {
            "author_ingestion_topic": AUTHOR_INGESTION_TOPIC,
            "author_ingestion_cutoff": author_ingestion_cutoff,
            "default_cutoff": default_cutoff,
        },
    )
    deleted: int = result.rowcount or 0
    if deleted:
        log.info(
            "Pruned %d expired realtime_events "
            "(author_ingestion_retention_days=%s, default_retention_days=%s)",
            deleted,
            AUTHOR_INGESTION_RETENTION_DAYS,
            DEFAULT_RETENTION_DAYS,
        )
    db.commit()
    return deleted
