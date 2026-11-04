from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.job_runs import (
    JOB_CRYPTO,
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_SUCCESS,
    TRIGGER_MANUAL,
    TRIGGER_SCHEDULED,
    record_job_run,
)
from app.core.logging import get_job_id, job_context
from app.crypto.ingest import acquire_refresh_lock, ingest_wallet, release_refresh_lock, upsert_snapshot
from app.crypto.valuation import refresh_latest_snapshot_prices
from app.services.portfolio_realtime import publish_portfolio_refresh

logger = logging.getLogger("capitalos.crypto.refresh")


OUTCOME_SUCCESS = STATUS_SUCCESS
OUTCOME_PARTIAL = STATUS_PARTIAL
OUTCOME_FAILED = STATUS_FAILED
OUTCOME_LOCKED = "locked"


def refresh_wallet_snapshot(db: Session, wallet_id: str, *, user_id: int | None, automatic: bool) -> bool:
    """Refresh one wallet. True when a snapshot was written (complete or partial)."""
    return refresh_wallet_snapshot_outcome(db, wallet_id, user_id=user_id, automatic=automatic) in (
        OUTCOME_SUCCESS,
        OUTCOME_PARTIAL,
    )


def refresh_wallet_snapshot_outcome(db: Session, wallet_id: str, *, user_id: int | None, automatic: bool) -> str:
    """Refresh one wallet and record the run in job_runs (#156).

    "success": every chain fetched. "partial": some EVM chains failed; their
    previous items were carried forward and the wallet stays due for a retry.
    "failed": nothing written. "locked": another refresh holds the wallet (not a
    run, nothing recorded).
    """
    context = job_context() if get_job_id() is None else None
    if context is not None:
        context.__enter__()
    lifecycle_started = time.perf_counter()
    started_at = datetime.now(tz=timezone.utc)
    if not acquire_refresh_lock(db, wallet_id):
        db.rollback()
        if context is not None:
            context.__exit__(None, None, None)
        return OUTCOME_LOCKED
    # Commit the flag now: it is visible to other refreshes, and the row lock the
    # UPDATE took isn't held through the provider fetch (#130 4.6).
    db.commit()

    outcome = OUTCOME_FAILED
    run_error: BaseException | str | None = None
    data_as_of = None
    try:
        result = ingest_wallet(db, wallet_id)
        snapshot_id = upsert_snapshot(db, wallet_id, result)
        db.commit()
        versions = getattr(result, "source_versions", None) or {}
        outcome = OUTCOME_PARTIAL if versions.get("failed_chain_names") else OUTCOME_SUCCESS
        if outcome == OUTCOME_PARTIAL:
            run_error = "Chains not fetched: " + ", ".join(str(c) for c in versions.get("failed_chain_names") or [])
        data_as_of = versions.get("holdings_as_of")
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
        return outcome
    except Exception as exc:
        run_error = exc
        db.rollback()
        price_overlay_updated = False
        try:
            price_overlay_updated = refresh_latest_snapshot_prices(db, wallet_id)
            db.commit()
        except Exception as price_exc:  # noqa: BLE001
            db.rollback()
            logger.warning(
                "snapshot_price_overlay_failed",
                extra={
                    "event": "snapshot_price_overlay_failed",
                    "provider": "crypto",
                    "platform": "crypto",
                    "wallet_id": wallet_id,
                    "error_class": price_exc.__class__.__name__,
                },
            )
        logger.exception(
            "snapshot_failed",
            extra={
                "event": "snapshot_failed",
                "provider": "crypto",
                "platform": "crypto",
                "wallet_id": wallet_id,
                "error_class": exc.__class__.__name__,
                "price_overlay_updated": price_overlay_updated,
                "duration_ms": int((time.perf_counter() - lifecycle_started) * 1000),
            },
        )
        return OUTCOME_FAILED
    finally:
        release_refresh_lock(db, wallet_id)
        db.commit()
        record_job_run(
            db,
            job=JOB_CRYPTO,
            scope=f"wallet:{wallet_id}",
            trigger=TRIGGER_SCHEDULED if automatic else TRIGGER_MANUAL,
            status=outcome,
            started_at=started_at,
            user_id=user_id,
            data_as_of=data_as_of,
            data_advanced=outcome in (OUTCOME_SUCCESS, OUTCOME_PARTIAL),
            error=run_error,
        )
        if context is not None:
            context.__exit__(None, None, None)
