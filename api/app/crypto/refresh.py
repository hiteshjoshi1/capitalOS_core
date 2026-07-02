from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.crypto.ingest import acquire_refresh_lock, ingest_wallet, release_refresh_lock, upsert_snapshot
from app.services.portfolio_realtime import publish_portfolio_refresh

logger = logging.getLogger("capitalos.crypto.refresh")


def refresh_wallet_snapshot(db: Session, wallet_id: str, *, user_id: int | None, automatic: bool) -> bool:
    if not acquire_refresh_lock(db, wallet_id):
        return False

    started = datetime.now(tz=timezone.utc)
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
                "duration_ms": int((datetime.now(tz=timezone.utc) - started).total_seconds() * 1000),
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
        logger.exception("crypto_refresh_failed", extra={"wallet_id": wallet_id, "error": str(exc)})
        return False
    finally:
        release_refresh_lock(db, wallet_id)
        db.commit()
