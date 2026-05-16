from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, require_current_user
from app.db.session import get_db
from app.market_data.service import latest_status_by_exchange, list_runs, run_all_exchanges
from app.services.portfolio_realtime import publish_portfolio_refresh

router = APIRouter(prefix="/market-data", tags=["market-data"], dependencies=[Depends(require_current_user)])


def _validate_admin_key(x_admin_key: Optional[str]) -> None:
    configured = os.getenv("STOCK_ADMIN_KEY") or os.getenv("CRYPTO_ADMIN_KEY")
    if not configured:
        return
    if not x_admin_key or x_admin_key != configured:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.get("/status")
def market_data_status(db: Session = Depends(get_db)):
    return {"status": latest_status_by_exchange(db)}


@router.get("/runs")
def market_data_runs(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    return {"runs": list_runs(db, limit=limit)}


@router.post("/refresh-now")
def market_data_refresh_now(
    x_admin_key: Optional[str] = Header(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    _validate_admin_key(x_admin_key)
    result = run_all_exchanges(db)
    exchange_results = result.get("exchanges") or []
    status = "completed"
    if any(item.get("status") == "failed" for item in exchange_results):
        status = "failed"
    elif any(item.get("status") != "success" for item in exchange_results):
        status = "partial"
    publish_portfolio_refresh(
        current_user.id,
        event_name="market_data_refresh_completed",
        source="market-data",
        status=status,
        payload={"exchange_count": len(exchange_results)},
    )
    return {"status": "ok", **result}
