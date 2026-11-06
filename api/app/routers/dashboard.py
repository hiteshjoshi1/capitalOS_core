"""Dashboard endpoints: parsing and response models only. What they show is
computed in app.valuation (#143); the Data Hub card in app.services.data_hub."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, require_current_user
from app.db.session import get_db
from app.schemas.dashboard import (
    BootstrapResponse,
    CashDepositsOut,
    DashboardSummaryResponse,
    DataHubSummaryResponse,
    GeographyExposureOut,
    NetWorthChangeResponse,
    NetWorthSinceUpdateResponse,
    PlatformAllocationOut,
    RiskSummaryResponse,
    StockExposureOut,
    StockHoldingsResponse,
    TopMovers,
    WealthTimelineBackfillResponse,
    WealthTimelineResponse,
)
from app.services import data_hub
from app.valuation import pages
from app.valuation.clock import _parse_month
from app.valuation.history import _backfill_wealth_rollups

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_current_user)])


@router.get("/bootstrap", response_model=BootstrapResponse)
def dashboard_bootstrap(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """Lean first-paint payload: net worth + exposure totals only.

    Skips geography, top_holdings, cashflow, and comparisons so the hero card
    and stock/crypto/cash exposure cards render on first paint.
    """
    return pages.bootstrap(db, current_user.id, month, _parse_month(month), base_currency)


@router.get("/net-worth-change", response_model=NetWorthChangeResponse)
def dashboard_net_worth_change(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    compare: str = Query("prev_month,prev_year", description="Comma-separated: prev_month,prev_year"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    return pages.net_worth_change(db, current_user.id, month, _parse_month(month), base_currency, compare)


@router.post("/net-worth-timeline/backfill", response_model=WealthTimelineBackfillResponse)
def net_worth_timeline_backfill(
    months: int = Query(36, ge=1, le=120, description="How many trailing months to (re)compute"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """(Re)compute and upsert wealth_monthly_rollups for the trailing N months.

    Idempotent — safe to call repeatedly (e.g. after a new statement upload,
    or from a "Refresh history" action) since every row is an upsert keyed on
    (user, month, base_currency).
    """
    written = _backfill_wealth_rollups(db, current_user.id, base_currency, months)
    return {"months_written": written, "base_currency": base_currency}


@router.get("/net-worth-timeline", response_model=WealthTimelineResponse)
def net_worth_timeline(
    months: int = Query(24, ge=1, le=120),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """Read-mostly: serves wealth_monthly_rollups (one indexed scan).

    Before reading, rows in the range that are stale are recomputed inline
    (#138): rows a dirty mark covers (an import changed data on or before their
    anchor), rows stored at another anchor than their own, the newest completed
    month(s) once they finish, and any provisional row of a month that hasn't
    completed yet (deleted: the live "now" point covers the open month). With
    nothing stale this is a pure read, with no writes.
    """
    return pages.net_worth_timeline(db, current_user.id, months, base_currency)


@router.get("/net-worth-timeline/{month}/movers", response_model=TopMovers)
def net_worth_timeline_movers(
    month: str,
    base_currency: str = Query("SGD"),
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """Top movers within holdings for one rollup month vs. the prior month —
    the drill-down's "what specifically moved" answer. Reuses the same
    holdings-diff logic /summary already uses for the current month, just
    parameterized by an arbitrary historical month; on-demand only (not
    stored), so it stays out of the timeline read path's hot loop.
    """
    return pages.timeline_movers(db, current_user.id, _parse_month(month), base_currency, limit)


@router.get("/summary", response_model=DashboardSummaryResponse)
def dashboard_summary(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    compare: str = Query("", description="Comma-separated: prev_month,prev_year"),
    skip_networth: bool = Query(False, description="When True, skip net-worth computation and omit net_worth/net_worth_as_of/net_worth_change from response"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    month_start = _parse_month(month)
    if skip_networth:
        return JSONResponse(content=pages.summary_without_net_worth(db, current_user.id, month, month_start, base_currency))
    return pages.summary(db, current_user.id, month, month_start, base_currency, compare)


@router.get("/risk-summary", response_model=RiskSummaryResponse)
def dashboard_risk_summary(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """Lean twin of /summary for the Risk page (#149): net_worth, and top_holdings cut to
    symbol / class / value, the same values as /summary for the same month and currency."""
    return pages.risk_summary(db, current_user.id, month, _parse_month(month), base_currency)


@router.get("/stock-holdings", response_model=StockHoldingsResponse)
def stock_holdings_summary(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    return pages.stock_holdings(db, current_user.id, month, _parse_month(month), base_currency)


@router.get("/net-worth-since-update", response_model=NetWorthSinceUpdateResponse)
def net_worth_since_update(
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """Since-last-update net-worth delta: current live state vs. the last
    available prior data point (not a fixed calendar day — if prices haven't
    refreshed in days, both anchors resolve to the same data and the delta is 0).
    """
    return pages.net_worth_since_update(db, current_user.id, base_currency)


@router.get("/platform-allocation", response_model=PlatformAllocationOut)
def platform_allocation(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    return PlatformAllocationOut(**pages.platform_allocation(db, current_user.id, month, _parse_month(month), base_currency))


@router.get("/cash-deposits", response_model=CashDepositsOut)
def cash_deposits(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    return CashDepositsOut(**pages.cash_deposits(db, current_user.id, month, _parse_month(month), base_currency))


@router.get("/stock-exposure", response_model=StockExposureOut)
def stock_exposure(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    return StockExposureOut(**pages.stock_exposure(db, current_user.id, _parse_month(month), base_currency))


@router.get("/geography-exposure", response_model=GeographyExposureOut)
def geography_exposure(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    return GeographyExposureOut(**pages.geography_exposure(db, current_user.id, _parse_month(month), base_currency))


@router.get("/data-hub-summary", response_model=DataHubSummaryResponse)
def data_hub_summary(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    return data_hub.data_hub_summary(db, current_user)
