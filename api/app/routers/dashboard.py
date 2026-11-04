"""Dashboard endpoints. The valuation itself is in app.valuation (#143)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, require_current_user
from app.db.session import get_db
from app.schemas.dashboard import (
    BootstrapResponse,
    CashDepositsItem,
    CashCurrencyBreakdownItem,
    CashDepositsOut,
    DashboardSummaryResponse,
    DataHubSummaryResponse,
    MiniTrendPoint,
    NetWorthChangeResponse,
    NetWorthSinceUpdateResponse,
    GeographyExposureItem,
    GeographyExposureOut,
    PlatformAllocationItem,
    PlatformAllocationOut,
    StockHoldingsResponse,
    StockExposureItem,
    StockExposureOut,
    TopMovers,
    WealthTimelineBackfillResponse,
    WealthTimelineResponse,
)
from app.portfolio.canonical_reads import get_data_completeness_status
from app.services import data_hub
from app.valuation import clock
from app.valuation.clock import (
    _add_months,
    _anchor_ts,
    _completed_snapshot_anchor_ts,
    _completed_snapshot_month_start,
    _configured_snapshot_day,
    _effective_anchor_for_month,
    _iso_value,
    _parse_month,
    _previous_update_anchor_ts,
)
from app.valuation.exposure import _geography, _geography_exposure, _platform_allocation
from app.valuation.facts import (
    _cash_balances,
    _cash_currency_breakdown,
    _cash_deposits,
    _cash_trend,
    _cashflow,
    _current_networth_state,
    _networth_components,
    _serialize_net_worth,
    _stablecoin_cash_balances,
    _sum_balances,
)
from app.valuation.fx import fx_status
from app.valuation.history import (
    _backfill_wealth_rollups,
    _cached_networth_components,
    _compute_component_changes,
    _compute_net_worth_changes,
    _live_compare_months,
    _refresh_wealth_rollups,
    _snapshot_compare_months,
    _timeline_upload_markers,
    _trailing_month_keys,
)
from app.valuation.holdings import (
    _quote_freshness_summary,
    _stock_exposure,
    _stock_geography_breakdown,
    _stock_platform_breakdown,
    _stock_trend,
    _top_holdings,
    _top_movers_from_holdings,
)
from app.valuation.pages import _summary_top_holdings_limit
from app.valuation.state import _effective_as_of, _positions_coverage_as_of, _snapshot_freshness

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
    month_start = _parse_month(month)
    anchor = _completed_snapshot_anchor_ts(month_start)
    current_state = _current_networth_state(db, base_currency, current_user.id)
    current_stock_data = _stock_exposure(
        db,
        current_state["anchor"],
        base_currency,
        current_user.id,
        price_overlay=True,
    )
    as_of, boundary_exact, freshness_status = _snapshot_freshness(db, anchor, current_user.id)
    reporting_as_of = anchor if freshness_status in {"exact", "synthetic"} else as_of

    nw = _networth_components(db, anchor, base_currency, current_user.id)
    stock_data = _stock_exposure(db, anchor, base_currency, current_user.id)

    cash_percent = round((nw["cash"] / nw["total"]) * 100, 2) if nw["total"] > 0 else 0.0
    snapshot_day = _configured_snapshot_day()

    return {
        "as_of_month": month,
        "base_currency": base_currency,
        "snapshot_day": snapshot_day,
        "current_net_worth_as_of": current_state["anchor"].isoformat(),
        "current_net_worth": current_state["net_worth"],
        "current_net_worth_freshness": current_state["freshness"],
        "net_worth_as_of": reporting_as_of.isoformat() if reporting_as_of else None,
        "net_worth_snapshot_as_of": as_of.isoformat() if as_of else None,
        "net_worth_boundary_at": anchor.isoformat(),
        "net_worth_boundary_exact": boundary_exact,
        "net_worth_freshness_status": freshness_status,
        "net_worth": _serialize_net_worth(nw),
        "current_stock_exposure_total": current_stock_data["total"],
        "current_crypto_exposure_total": current_state["net_worth"]["crypto"],
        "current_cash_percent": current_state["cash_percent"],
        "stock_exposure_total": stock_data["total"],
        "crypto_exposure_total": nw["crypto"],
        "cash_percent": cash_percent,
        **fx_status(),
    }


@router.get("/net-worth-change", response_model=NetWorthChangeResponse)
def dashboard_net_worth_change(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    compare: str = Query("prev_month,prev_year", description="Comma-separated: prev_month,prev_year"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    month_start = _parse_month(month)
    anchor = _completed_snapshot_anchor_ts(month_start)
    as_of, boundary_exact, freshness_status = _snapshot_freshness(db, anchor, current_user.id)
    reporting_as_of = anchor if freshness_status in {"exact", "synthetic"} else as_of
    nw = _networth_components(db, anchor, base_currency, current_user.id)
    compare_set = {c.strip() for c in compare.split(",") if c.strip()}
    changes = _compute_net_worth_changes(
        db=db,
        compare_months=_snapshot_compare_months(_completed_snapshot_month_start(month_start), compare_set),
        as_of=as_of,
        current_value=nw["total"],
        base_currency=base_currency,
        current_user_id=current_user.id,
    )
    return {
        "as_of_month": month,
        "base_currency": base_currency,
        "net_worth_as_of": reporting_as_of.isoformat() if reporting_as_of else None,
        "net_worth_snapshot_as_of": as_of.isoformat() if as_of else None,
        "net_worth_boundary_at": anchor.isoformat(),
        "net_worth_boundary_exact": boundary_exact,
        "net_worth_freshness_status": freshness_status,
        "net_worth_change": changes if changes else None,
    }


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
    current_month_start = _parse_month(clock._current_anchor_ts().strftime("%Y-%m"))
    range_start = _add_months(current_month_start, -(months - 1))
    current_month_key = current_month_start.strftime("%Y-%m")

    _refresh_wealth_rollups(db, current_user.id, base_currency, months=_trailing_month_keys(months))

    rollup_rows = db.execute(
        text(
            """
            SELECT month, anchor_date, total, cash, stocks_funds, crypto, liabilities,
                   source_freshness, freshness_status, computed_at
            FROM wealth_monthly_rollups
            WHERE user_id = :user_id AND base_currency = :base_currency AND month >= :from_month
            ORDER BY month ASC
            """
        ),
        {
            "user_id": current_user.id,
            "base_currency": base_currency,
            "from_month": range_start.strftime("%Y-%m"),
        },
    ).mappings().all()

    upload_markers = _timeline_upload_markers(db, current_user.id, range_start)

    points = []
    for row in rollup_rows:
        source_freshness = row["source_freshness"]
        if isinstance(source_freshness, str):
            source_freshness = json.loads(source_freshness)
        anchor_date = row["anchor_date"]
        points.append({
            "month": row["month"],
            "anchor_date": anchor_date if isinstance(anchor_date, str) else anchor_date.isoformat(),
            "total": float(row["total"]),
            "cash": float(row["cash"]),
            "stocks_funds": float(row["stocks_funds"]),
            "crypto": float(row["crypto"]),
            "liabilities": float(row["liabilities"]),
            "source_freshness": source_freshness,
            "freshness_status": row["freshness_status"],
            "computed_at": _iso_value(row["computed_at"]),
            "uploads": upload_markers.get(row["month"], []),
        })

    current_state = _current_networth_state(db, base_currency, current_user.id)

    return {
        "base_currency": base_currency,
        "points": points,
        "now": {
            **current_state["net_worth"],
            "as_of": current_state["anchor"].isoformat(),
            # The open month has no stored point; its upload ticks go on "now".
            "uploads": upload_markers.get(current_month_key, []),
        },
    }


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
    month_start = _parse_month(month)
    # Like for like (#133): the anchor actually used vs the completed anchor one
    # month before it. For the open month both used to resolve to the same date.
    snapshot_month_start = _completed_snapshot_month_start(month_start)
    anchor = _anchor_ts(snapshot_month_start)
    prev_month_start = _add_months(snapshot_month_start, -1)
    prev_anchor = _anchor_ts(prev_month_start)

    nw = _networth_components(db, anchor, base_currency, current_user.id)
    prev_nw = _networth_components(db, prev_anchor, base_currency, current_user.id)
    current_holdings = _top_holdings(db, anchor, nw["total"], base_currency, current_user.id, limit=250)
    prior_holdings = _top_holdings(db, prev_anchor, prev_nw["total"], base_currency, current_user.id, limit=250)
    return _top_movers_from_holdings(
        current_holdings, prior_holdings, prev_month_start.strftime("%Y-%m"), limit=limit
    )


@router.get("/summary", response_model=DashboardSummaryResponse)
def dashboard_summary(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    compare: str = Query("", description="Comma-separated: prev_month,prev_year"),
    skip_networth: bool = Query(False, description="When True, skip net-worth computation and omit net_worth/net_worth_as_of/net_worth_change from response"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    # Calendar month window for cashflow
    month_start = _parse_month(month)
    month_end = _add_months(month_start, 1)

    # Snapshot anchor + effective snapshot timestamp. Comparisons are taken
    # relative to the month whose anchor is actually used (#133).
    snapshot_month_start = _completed_snapshot_month_start(month_start)
    anchor = _anchor_ts(snapshot_month_start)
    snapshot_day = _configured_snapshot_day()
    top_holdings_limit = _summary_top_holdings_limit()

    if skip_networth:
        current_anchor = clock._current_anchor_ts()
        current_nw = _networth_components(db, current_anchor, base_currency, current_user.id, price_overlay=True)
        geo = _geography(
            db,
            current_anchor,
            current_nw["total"],
            base_currency,
            current_user.id,
            price_overlay=True,
        )
        top = _top_holdings(
            db,
            current_anchor,
            current_nw["total"],
            base_currency,
            current_user.id,
            limit=top_holdings_limit,
            price_overlay=True,
        )
        cash_balances = _cash_balances(db, current_anchor, base_currency, current_user.id)
        cf = _cashflow(db, month_start, month_end, base_currency, current_user.id)
        cash_percent = round((current_nw["cash"] / current_nw["total"]) * 100, 2) if current_nw["total"] > 0 else 0.0
        return JSONResponse(content={
            "as_of_month": month,
            "base_currency": base_currency,
            "snapshot_day": snapshot_day,
            "geography": geo,
            "cash_flow": cf,
            "top_holdings": top,
            "cash_balances": cash_balances,
            "cash_percent": cash_percent,
            **fx_status(),
        })

    as_of, boundary_exact, freshness_status = _snapshot_freshness(db, anchor, current_user.id)
    current_state = _current_networth_state(db, base_currency, current_user.id)
    current_anchor = current_state["anchor"]
    current_nw = current_state["net_worth"]
    reporting_as_of = anchor if freshness_status in {"exact", "synthetic"} else as_of

    nw = _networth_components(db, anchor, base_currency, current_user.id)
    geo = _geography(
        db,
        current_anchor,
        current_nw["total"],
        base_currency,
        current_user.id,
        price_overlay=True,
    )
    top = _top_holdings(
        db,
        current_anchor,
        current_nw["total"],
        base_currency,
        current_user.id,
        limit=top_holdings_limit,
        price_overlay=True,
    )
    cash_balances = _cash_balances(db, current_anchor, base_currency, current_user.id)
    cf = _cashflow(db, month_start, month_end, base_currency, current_user.id)

    compare_set = {c.strip() for c in compare.split(",") if c.strip()}
    nw_cache: Dict[datetime, Dict[str, float]] = {anchor: nw}
    changes = _compute_net_worth_changes(
        db=db,
        compare_months=_snapshot_compare_months(snapshot_month_start, compare_set),
        as_of=as_of,
        current_value=nw["total"],
        base_currency=base_currency,
        current_user_id=current_user.id,
        nw_cache=nw_cache,
    )
    # The live headline (current_net_worth) vs the latest completed month-end
    # anchor (vs_prev_month) and the one twelve months before it (vs_prev_year),
    # independent of the selected month, like the headline itself (#133).
    current_changes = _compute_net_worth_changes(
        db=db,
        compare_months=_live_compare_months(current_anchor, compare_set),
        as_of=current_anchor,
        current_value=current_nw["total"],
        base_currency=base_currency,
        current_user_id=current_user.id,
        nw_cache=nw_cache,
    )
    component_changes = (
        _compute_component_changes(
            db=db,
            month_start=snapshot_month_start,
            as_of=as_of,
            current_components=nw,
            base_currency=base_currency,
            current_user_id=current_user.id,
            nw_cache=nw_cache,
        )
        if "prev_month" in compare_set
        else None
    )
    top_movers = None
    if "prev_month" in compare_set:
        prev_month_start = _add_months(snapshot_month_start, -1)
        prev_anchor = _anchor_ts(prev_month_start)
        snapshot_top = _top_holdings(
            db,
            anchor,
            nw["total"],
            base_currency,
            current_user.id,
            limit=max(top_holdings_limit, 250),
        )
        prev_components = _cached_networth_components(db, prev_anchor, base_currency, current_user.id, nw_cache)
        prev_top = _top_holdings(
            db,
            prev_anchor,
            prev_components["total"],
            base_currency,
            current_user.id,
            limit=max(top_holdings_limit, 250),
        )
        top_movers = _top_movers_from_holdings(snapshot_top, prev_top, prev_month_start.strftime("%Y-%m"))

    # Compute cash_percent
    cash_percent = round((nw["cash"] / nw["total"]) * 100, 2) if nw["total"] > 0 else 0.0

    # Data completeness indicators from canonical portfolio sources
    completeness_indicators = get_data_completeness_status(
        db, current_user_id=current_user.id, anchor_date=anchor.date()
    )

    return {
        "as_of_month": month,
        "base_currency": base_currency,
        "snapshot_day": snapshot_day,
        "current_net_worth_as_of": current_state["anchor"].isoformat(),
        "current_net_worth": current_state["net_worth"],
        "current_net_worth_freshness": current_state["freshness"],
        "net_worth_as_of": reporting_as_of.isoformat() if reporting_as_of else None,
        "net_worth_snapshot_as_of": as_of.isoformat() if as_of else None,
        "net_worth_boundary_at": anchor.isoformat(),
        "net_worth_boundary_exact": boundary_exact,
        "net_worth_freshness_status": freshness_status,
        "net_worth": _serialize_net_worth(nw),
        "geography": geo,
        "cash_flow": cf,
        "top_holdings": top,
        "cash_balances": cash_balances,
        "net_worth_change": changes if changes else None,
        "current_net_worth_change": current_changes if current_changes else None,
        "net_worth_component_change": component_changes,
        "top_movers": top_movers,
        "cash_percent": cash_percent,
        "data_completeness_indicators": completeness_indicators if completeness_indicators else None,
        **fx_status(),
    }


@router.get("/stock-holdings", response_model=StockHoldingsResponse)
def stock_holdings_summary(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    # "browse holdings as of {month}" — effective_anchor/is_live decide whether this
    # is live "now" data (current/future month) or a completed historical boundary.
    # stock_current_total/top_holdings/geography_breakdown/platform_breakdown are all
    # anchored to that same point; stock_snapshot_total is the PRIOR month, for a
    # stable "vs last month" comparison (not "vs whatever month happens to be picked").
    month_start = _parse_month(month)
    effective_anchor, is_live = _effective_anchor_for_month(month_start)
    compare_anchor = _anchor_ts(_add_months(month_start, -1))
    snapshot_day = _configured_snapshot_day()
    top_holdings_limit = _summary_top_holdings_limit()
    as_of = _effective_as_of(db, effective_anchor, current_user.id)
    holdings_as_of = _positions_coverage_as_of(db, effective_anchor, current_user.id)
    reporting_as_of = effective_anchor if as_of is not None else None
    boundary_exact = as_of.date() == effective_anchor.date() if as_of is not None else False
    freshness_status = "exact" if boundary_exact else ("synthetic" if as_of is not None else "missing")
    nw = _networth_components(db, effective_anchor, base_currency, current_user.id, price_overlay=is_live)
    top = [
        row
        for row in _top_holdings(
            db,
            effective_anchor,
            nw["total"],
            base_currency,
            current_user.id,
            limit=top_holdings_limit,
            price_overlay=is_live,
        )
        if str(row.get("asset_class") or "").upper() in {"STOCK", "FUND"}
    ]
    stock_exposure = _stock_exposure(
        db,
        effective_anchor,
        base_currency,
        current_user.id,
        price_overlay=is_live,
    )
    compare_stock_exposure = _stock_exposure(db, compare_anchor, base_currency, current_user.id)
    geography_breakdown = _stock_geography_breakdown(stock_exposure, compare_stock_exposure)
    platform_breakdown = _stock_platform_breakdown(stock_exposure, compare_stock_exposure)
    quote_freshness_summary = _quote_freshness_summary(top)
    trend = [MiniTrendPoint(**point) for point in _stock_trend(db, month_start, base_currency, current_user.id)]

    geography_performance: list[dict[str, Any]] = []
    geography_performance_as_of: Optional[str] = None
    if is_live:
        # Unlike the monthly compare_stock_exposure above (which relies on a distinct
        # historical position/NAV snapshot per month boundary), a 1-day delta needs
        # price_overlay=True on *both* sides so the movement reflects the anchor-scoped
        # `prices` table (trade_date <= anchor) rather than a frozen snapshot value —
        # otherwise accounts without a same-day re-import would always show a 0 delta.
        day_compare_anchor = _previous_update_anchor_ts(effective_anchor)
        day_compare_stock_exposure = _stock_exposure(
            db, day_compare_anchor, base_currency, current_user.id, price_overlay=True
        )
        geography_performance = _stock_geography_breakdown(stock_exposure, day_compare_stock_exposure)
        geography_performance_as_of = _iso_value(_effective_as_of(db, day_compare_anchor, current_user.id))

    return {
        "as_of_month": month,
        "base_currency": base_currency,
        "snapshot_day": snapshot_day,
        "is_live": is_live,
        "compare_month": _add_months(month_start, -1).strftime("%Y-%m"),
        "current_holdings_as_of": holdings_as_of.isoformat() if holdings_as_of else None,
        "net_worth_as_of": reporting_as_of.isoformat() if reporting_as_of else None,
        "net_worth_snapshot_as_of": _iso_value(_effective_as_of(db, compare_anchor, current_user.id)),
        "net_worth_boundary_at": effective_anchor.isoformat(),
        "net_worth_boundary_exact": boundary_exact,
        "net_worth_freshness_status": freshness_status,
        "top_holdings": top,
        "geography_breakdown": geography_breakdown,
        "geography_performance": geography_performance,
        "geography_performance_as_of": geography_performance_as_of,
        "platform_breakdown": platform_breakdown,
        "stock_current_total": stock_exposure["total"],
        "stock_snapshot_total": compare_stock_exposure["total"],
        "quote_freshness_summary": quote_freshness_summary,
        "trend": trend,
        **fx_status(),
    }


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
    top_holdings_limit = _summary_top_holdings_limit()
    current_anchor = clock._current_anchor_ts()
    compare_anchor = _previous_update_anchor_ts(current_anchor)
    current_as_of = _effective_as_of(db, current_anchor, current_user.id)
    compare_as_of = _effective_as_of(db, compare_anchor, current_user.id)
    compare_label = compare_as_of.isoformat() if compare_as_of else "unknown"

    # price_overlay=True on both sides (unlike the monthly comparisons elsewhere in
    # this file) so the delta reflects the anchor-scoped `prices` table rather than a
    # frozen position snapshot — see the matching comment in stock_holdings_summary.
    current_nw = _networth_components(db, current_anchor, base_currency, current_user.id, price_overlay=True)
    compare_nw = _networth_components(db, compare_anchor, base_currency, current_user.id, price_overlay=True)

    def _change(current_value: float, previous_value: float) -> dict[str, Any]:
        abs_change = current_value - previous_value
        return {
            "abs": abs_change,
            "pct": (abs_change / previous_value) if previous_value > 0 else None,
            "current_as_of": current_as_of.isoformat() if current_as_of else None,
            "compare_as_of": compare_as_of.isoformat() if compare_as_of else None,
            "compare_month": compare_label,
        }

    net_worth_change = _change(current_nw["total"], compare_nw["total"])
    component_change = {
        key: _change(current_nw[key], compare_nw[key])
        for key in ("cash", "stocks_funds", "crypto")
    }

    snapshot_top = _top_holdings(
        db,
        current_anchor,
        current_nw["total"],
        base_currency,
        current_user.id,
        limit=max(top_holdings_limit, 250),
        price_overlay=True,
    )
    prev_top = _top_holdings(
        db,
        compare_anchor,
        compare_nw["total"],
        base_currency,
        current_user.id,
        limit=max(top_holdings_limit, 250),
        price_overlay=True,
    )
    top_movers = _top_movers_from_holdings(snapshot_top, prev_top, compare_label, limit=5)

    return {
        "base_currency": base_currency,
        "current_as_of": current_as_of.isoformat() if current_as_of else None,
        "compare_as_of": compare_as_of.isoformat() if compare_as_of else None,
        "net_worth_change": net_worth_change,
        "component_change": component_change,
        "top_movers": top_movers,
    }


@router.get("/platform-allocation", response_model=PlatformAllocationOut)
def platform_allocation(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    _parse_month(month)
    anchor = clock._current_anchor_ts()
    as_of = _effective_as_of(db, anchor, current_user.id)
    payload = _platform_allocation(db, anchor, base_currency, current_user.id, price_overlay=True)
    return PlatformAllocationOut(
        as_of=as_of.isoformat() if as_of else None,
        total=payload["total"],
        items=[PlatformAllocationItem(**item) for item in payload["items"]],
    )


@router.get("/cash-deposits", response_model=CashDepositsOut)
def cash_deposits(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    # "browse cash as of {month}" — effective_anchor/is_live decide whether this is
    # live "now" data (current/future month) or a completed historical boundary.
    # The "Where cash sits" breakdown (payload/items) and current_total both follow
    # that same point; snapshot_total is the PRIOR month, for a stable "vs last
    # month" comparison (not "vs whatever month happens to be picked").
    month_start = _parse_month(month)
    effective_anchor, is_live = _effective_anchor_for_month(month_start)
    compare_anchor = _anchor_ts(_add_months(month_start, -1))
    payload = _cash_deposits(db, effective_anchor, base_currency, current_user.id)
    snapshot_balances = _cash_balances(db, compare_anchor, base_currency, current_user.id) + _stablecoin_cash_balances(
        db, compare_anchor, base_currency, current_user.id
    )
    current_balances = _cash_balances(db, effective_anchor, base_currency, current_user.id) + _stablecoin_cash_balances(
        db, effective_anchor, base_currency, current_user.id
    )
    current_total = _sum_balances(current_balances)
    snapshot_total = _sum_balances(snapshot_balances)
    delta_abs = current_total - snapshot_total
    return CashDepositsOut(
        total=payload["total"],
        items=[CashDepositsItem(**item) for item in payload["items"]],
        as_of_month=month,
        base_currency=base_currency,
        snapshot_day=_configured_snapshot_day(),
        is_live=is_live,
        compare_month=_add_months(month_start, -1).strftime("%Y-%m"),
        current_cash_as_of=_iso_value(_effective_as_of(db, effective_anchor, current_user.id)),
        snapshot_cash_as_of=_iso_value(_effective_as_of(db, compare_anchor, current_user.id)),
        current_total=current_total,
        snapshot_total=snapshot_total,
        delta_abs=delta_abs,
        delta_pct=(delta_abs / snapshot_total) if snapshot_total > 0 else None,
        trend=[MiniTrendPoint(**point) for point in _cash_trend(db, month_start, base_currency, current_user.id)],
        currency_breakdown=[
            CashCurrencyBreakdownItem(**item)
            for item in _cash_currency_breakdown(current_balances, snapshot_balances)
        ],
    )


@router.get("/stock-exposure", response_model=StockExposureOut)
def stock_exposure(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    _parse_month(month)
    anchor = clock._current_anchor_ts()
    as_of = _positions_coverage_as_of(db, anchor, current_user.id)
    payload = _stock_exposure(db, anchor, base_currency, current_user.id, price_overlay=True)
    return StockExposureOut(
        as_of=as_of.isoformat() if as_of else None,
        base_currency=base_currency,
        total=payload["total"],
        by_country=[StockExposureItem(**item) for item in payload["by_country"]],
        by_platform=[StockExposureItem(**item) for item in payload["by_platform"]],
    )


@router.get("/geography-exposure", response_model=GeographyExposureOut)
def geography_exposure(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    month_start = _parse_month(month)
    anchor = _completed_snapshot_anchor_ts(month_start)
    as_of = _effective_as_of(db, anchor, current_user.id)
    # A completed month-end: valued like that month's net worth, at its
    # statements' prices, not today's quotes (#144).
    payload = _geography_exposure(db, anchor, base_currency, current_user.id, price_overlay=False)
    return GeographyExposureOut(
        as_of=as_of.isoformat() if as_of else None,
        base_currency=base_currency,
        total=payload["total"],
        items=[GeographyExposureItem(**item) for item in payload["items"]],
    )


@router.get("/data-hub-summary", response_model=DataHubSummaryResponse)
def data_hub_summary(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    return data_hub.data_hub_summary(db, current_user)
