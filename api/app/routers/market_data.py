from __future__ import annotations

import os
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, require_admin, require_current_user
from app.core.logging import job_context
from app.db.session import get_db
from app.market_data.service import (
    held_asset_ids,
    latest_status_by_exchange,
    list_runs,
    run_all_exchanges,
    scope_exchange_diagnostics,
)
from app.services.portfolio_realtime import publish_portfolio_refresh

router = APIRouter(prefix="/market-data", tags=["market-data"], dependencies=[Depends(require_current_user)])
logger = logging.getLogger("capitalos.market_data")


def _validate_admin_key(x_admin_key: Optional[str]) -> None:
    # On top of the admin account (#152): with a key configured, the header is needed too.
    configured = os.getenv("STOCK_ADMIN_KEY") or os.getenv("CRYPTO_ADMIN_KEY")
    if not configured:
        return
    if not x_admin_key or x_admin_key != configured:
        raise HTTPException(status_code=403, detail="Forbidden")


def _visible_asset_ids(db: Session, current_user: CurrentUser) -> set[int] | None:
    """None (every symbol) for an admin; otherwise the assets the caller holds,
    so per-symbol diagnostics never show another user's tickers (#153)."""
    if current_user.is_admin:
        return None
    return held_asset_ids(db, current_user.id)


@router.get("/status")
def market_data_status(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    return {"status": latest_status_by_exchange(db, asset_ids=_visible_asset_ids(db, current_user))}


@router.get("/runs")
def market_data_runs(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    return {"runs": list_runs(db, limit=limit)}


@router.post("/refresh-now")
def market_data_refresh_now(
    x_admin_key: Optional[str] = Header(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
):
    _validate_admin_key(x_admin_key)
    started = time.perf_counter()
    with job_context():
        try:
            logger.info("quote_refresh_started", extra={"event": "quote_refresh_started", "provider": "market_data"})
            result = run_all_exchanges(db)
            exchange_results = result.get("exchanges") or []
            visible = _visible_asset_ids(db, current_user)
            if visible is not None:
                for item in exchange_results:
                    if isinstance(item.get("diagnostics"), dict):
                        item["diagnostics"] = scope_exchange_diagnostics(item["diagnostics"], visible)
            status = "completed"
            if any(item.get("status") == "failed" for item in exchange_results):
                status = "failed"
            elif any(item.get("status") != "success" for item in exchange_results):
                status = "partial"
            event_name = "quote_refresh_failed" if status == "failed" else "quote_refresh_succeeded"
            level = logger.warning if status == "failed" else logger.info
            level(
                event_name,
                extra={
                    "event": event_name,
                    "provider": "market_data",
                    "rows": sum(int(item.get("requested_symbols") or 0) for item in exchange_results),
                    "inserted": sum(int(item.get("upserted_rows") or 0) for item in exchange_results),
                    "skipped": sum(int(item.get("missing_symbols") or 0) for item in exchange_results),
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                },
            )
            publish_portfolio_refresh(
                current_user.id,
                event_name="market_data_refresh_completed",
                source="market-data",
                status=status,
                payload={"exchange_count": len(exchange_results)},
            )
            return {"status": "ok", **result}
        except Exception as exc:
            logger.exception(
                "quote_refresh_failed",
                extra={
                    "event": "quote_refresh_failed",
                    "provider": "market_data",
                    "error_class": exc.__class__.__name__,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                },
            )
            raise
