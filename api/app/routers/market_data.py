from __future__ import annotations

import os
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, require_admin, require_current_user
from app.core.job_runs import TRIGGER_MANUAL
from app.core.logging import job_context
from app.db.session import get_db
from app.market_data.scheduler import record_exchange_runs
from app.market_data.service import (
    _default_yahoo_symbol,
    apply_yahoo_ticker,
    bse_symbol_for,
    configured_exchanges,
    held_asset_ids,
    latest_status_by_exchange,
    list_runs,
    probe_yahoo_ticker,
    run_all_exchanges,
    scope_exchange_diagnostics,
    unpriced_held_positions,
)
from app.services.portfolio_realtime import publish_portfolio_refresh
from app.schemas.market_data import MarketDataRunsResponse, MarketDataStatusResponse, UnpricedResponse

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


# exclude_unset: an exchange that never ran has no run fields at all, as before #361.
@router.get("/status", response_model=MarketDataStatusResponse, response_model_exclude_unset=True)
def market_data_status(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    return {"status": latest_status_by_exchange(db, asset_ids=_visible_asset_ids(db, current_user))}


@router.get("/runs", response_model=MarketDataRunsResponse)
def market_data_runs(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    return {"runs": list_runs(db, limit=limit)}


class TickerTestIn(BaseModel):
    yahoo_symbol: str = Field(..., min_length=1, max_length=32)
    exchange_code: Optional[str] = Field(None, max_length=16)


class TickerSetIn(BaseModel):
    asset_id: int
    exchange_code: str = Field(..., min_length=1, max_length=16)
    yahoo_symbol: str = Field(..., min_length=1, max_length=32)


@router.get("/unpriced", response_model=UnpricedResponse)
def market_data_unpriced(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """The caller's held stocks and funds the refresh can't price (#320), with the Yahoo
    tickers worth trying, and whether the caller may set one (admins: shared data, #152)."""
    items = []
    for item in unpriced_held_positions(db, user_id=current_user.id):
        exchange = item.get("exchange_code")
        symbol = str(item.get("symbol") or "").strip().upper()
        suggestions: list[str] = []
        if symbol and exchange:
            default = _default_yahoo_symbol(symbol, exchange)
            suggestions.append(default)
            bse = bse_symbol_for(default)
            if bse:
                suggestions.append(bse)
        items.append({**item, "suggested_yahoo_symbols": suggestions})
    return {"items": items, "can_fix": bool(current_user.is_admin)}


@router.post("/ticker-test")
def market_data_ticker_test(
    payload: TickerTestIn,
    x_admin_key: Optional[str] = Header(None),
    current_user: CurrentUser = Depends(require_admin),
):
    """Ask Yahoo for one ticker's latest close before saving it (#320). Admin only."""
    _validate_admin_key(x_admin_key)
    return probe_yahoo_ticker(payload.yahoo_symbol, exchange_code=payload.exchange_code)


@router.post("/ticker")
def market_data_set_ticker(
    payload: TickerSetIn,
    x_admin_key: Optional[str] = Header(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
):
    """Save a tested Yahoo ticker as the holding's override and store its quote (#320).
    Admin only: the symbol map and prices are shared data (#152)."""
    _validate_admin_key(x_admin_key)
    try:
        result = apply_yahoo_ticker(
            db, asset_id=payload.asset_id, exchange_code=payload.exchange_code, yahoo_symbol=payload.yahoo_symbol
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    publish_portfolio_refresh(
        current_user.id,
        event_name="market_data_refresh_completed",
        source="market-data",
        status="completed",
        payload={"exchange_count": 1},
    )
    return result


@router.post("/refresh-now")
def market_data_refresh_now(
    exchange: Optional[str] = Query(None, max_length=16, description="Only this exchange (#320); all when omitted"),
    x_admin_key: Optional[str] = Header(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
):
    _validate_admin_key(x_admin_key)
    if exchange is not None and exchange.strip().upper() not in configured_exchanges():
        raise HTTPException(status_code=422, detail=f"Unknown exchange {exchange}")
    started = time.perf_counter()
    started_at = datetime.now(tz=timezone.utc)
    with job_context():
        try:
            logger.info("quote_refresh_started", extra={"event": "quote_refresh_started", "provider": "market_data"})
            result = run_all_exchanges(db, [exchange.strip().upper()]) if exchange else run_all_exchanges(db)
            exchange_results = result.get("exchanges") or []
            record_exchange_runs(db, exchange_results, trigger=TRIGGER_MANUAL, started_at=started_at)
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
            db.rollback()
            record_exchange_runs(
                db, [], trigger=TRIGGER_MANUAL, started_at=started_at, error=exc, exchanges=configured_exchanges()
            )
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
