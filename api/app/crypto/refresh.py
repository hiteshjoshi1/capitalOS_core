from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session

from app.core.logging import get_job_id, job_context
from app.crypto.ingest import acquire_refresh_lock, ingest_wallet, release_refresh_lock, upsert_snapshot
from app.services.portfolio_realtime import publish_portfolio_refresh

logger = logging.getLogger("capitalos.crypto.refresh")


def refresh_wallet_snapshot(db: Session, wallet_id: str, *, user_id: int | None, automatic: bool) -> bool:
    context = job_context() if get_job_id() is None else None
    if context is not None:
        context.__enter__()
    lifecycle_started = time.perf_counter()
    if not acquire_refresh_lock(db, wallet_id):
        if context is not None:
            context.__exit__(None, None, None)
        return False

    try:
        result = ingest_wallet(db, wallet_id)
        snapshot_id = upsert_snapshot(db, wallet_id, result)
        db.commit()
        logger.info(
            "snapshot_created",
            extra={
                "event": "snapshot_created",
                "provider": "crypto",
                "platform": "crypto",
                "wallet_id": wallet_id,
                "snapshot_db_id": snapshot_id,
                "items": len(result.items),
                "rows": len(result.items),
                "total_usd": result.total_usd,
                "duration_ms": int((time.perf_counter() - lifecycle_started) * 1000),
            },
        )
        if user_id is not None:
            publish_portfolio_refresh(
                user_id,
                event_name="crypto_refresh_completed",
                source="crypto",
                payload={
                    "wallet_id": wallet_id,
                    "automatic": automatic,
                    "total_usd": result.total_usd,
                },
            )
        return True
    except Exception as exc:
        db.rollback()
        logger.exception(
            "snapshot_failed",
            extra={
                "event": "snapshot_failed",
                "provider": "crypto",
                "platform": "crypto",
                "wallet_id": wallet_id,
                "error_class": exc.__class__.__name__,
                "duration_ms": int((time.perf_counter() - lifecycle_started) * 1000),
            },
        )
        return False
    finally:
        release_refresh_lock(db, wallet_id)
        db.commit()
        if context is not None:
            context.__exit__(None, None, None)
