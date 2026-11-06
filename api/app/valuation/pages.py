"""One function per dashboard response, composing the valuation modules.

Each takes parsed arguments (a month start, not a 'YYYY-MM' string) and returns
the response as plain data; ``app.routers.dashboard`` turns it into the
response model.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.portfolio.canonical_reads import get_data_completeness_status
from app.valuation import clock
from app.valuation.clock import (
    _add_months,
    _anchor_ts,
    _completed_snapshot_anchor_ts,
    _completed_snapshot_month_start,
    _configured_snapshot_day,
    _effective_anchor_for_month,
    _iso_value,
    _month_view_anchor,
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
    _cached_networth_components,
    _compute_component_changes,
    _compute_net_worth_changes,
    _live_compare_months,
    _refresh_wealth_rollups,
    _snapshot_compare_months,
    _stored_timeline_points,
    _trailing_month_keys,
    baseline_missing,
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
from app.valuation.prices import _quote_stale_days
from app.valuation.state import _effective_as_of, _positions_coverage_as_of, _snapshot_freshness


def _summary_top_holdings_limit() -> int:
    raw = os.getenv("DASHBOARD_TOP_HOLDINGS_LIMIT", "200")
    try:
        limit = int(raw)
    except ValueError:
        limit = 200
    # Keep payload bounded while allowing rich detail pages to paginate client-side.
    return max(20, min(limit, 500))


def _compare_set(compare: str) -> set[str]:
    return {c.strip() for c in compare.split(",") if c.strip()}


def _snapshot_header(db: Session, anchor: datetime, current_user_id: int) -> tuple[Optional[datetime], Dict[str, Any]]:
    """The snapshot-boundary fields of /bootstrap, /net-worth-change and /summary."""
    as_of, boundary_exact, freshness_status = _snapshot_freshness(db, anchor, current_user_id)
    reporting_as_of = anchor if freshness_status in {"exact", "synthetic"} else as_of
    return as_of, {
        "net_worth_as_of": reporting_as_of.isoformat() if reporting_as_of else None,
        "net_worth_snapshot_as_of": as_of.isoformat() if as_of else None,
        "net_worth_boundary_at": anchor.isoformat(),
        "net_worth_boundary_exact": boundary_exact,
        "net_worth_freshness_status": freshness_status,
    }


def _current_header(current_state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "current_net_worth_as_of": current_state["anchor"].isoformat(),
        "current_net_worth": current_state["net_worth"],
        "current_net_worth_freshness": current_state["freshness"],
    }


def _cash_percent(nw: Dict[str, float]) -> float:
    return round((nw["cash"] / nw["total"]) * 100, 2) if nw["total"] > 0 else 0.0


def bootstrap(db: Session, current_user_id: int, month: str, month_start: datetime, base_currency: str) -> Dict[str, Any]:
    """Lean first-paint payload: net worth + exposure totals only."""
    anchor = _completed_snapshot_anchor_ts(month_start)
    current_state = _current_networth_state(db, base_currency, current_user_id)
    current_stock_data = _stock_exposure(db, current_state["anchor"], base_currency, current_user_id, price_overlay=True)
    _as_of, snapshot_header = _snapshot_header(db, anchor, current_user_id)
    nw = _networth_components(db, anchor, base_currency, current_user_id)
    stock_data = _stock_exposure(db, anchor, base_currency, current_user_id)
    return {
        "as_of_month": month,
        "base_currency": base_currency,
        "snapshot_day": _configured_snapshot_day(),
        # Whether `month` is the open (or a future) month, whose page shows the
        # live headline; a past month shows its month-end `net_worth` (#223).
        "is_live": _month_view_anchor(month_start)[1],
        **_current_header(current_state),
        **snapshot_header,
        "net_worth": _serialize_net_worth(nw),
        "current_stock_exposure_total": current_stock_data["total"],
        "current_crypto_exposure_total": current_state["net_worth"]["crypto"],
        "current_cash_percent": current_state["cash_percent"],
        "stock_exposure_total": stock_data["total"],
        "crypto_exposure_total": nw["crypto"],
        "cash_percent": _cash_percent(nw),
        **fx_status(),
    }


def net_worth_change(
    db: Session, current_user_id: int, month: str, month_start: datetime, base_currency: str, compare: str
) -> Dict[str, Any]:
    anchor = _completed_snapshot_anchor_ts(month_start)
    as_of, snapshot_header = _snapshot_header(db, anchor, current_user_id)
    nw = _networth_components(db, anchor, base_currency, current_user_id)
    changes = _compute_net_worth_changes(
        db=db,
        compare_months=_snapshot_compare_months(_completed_snapshot_month_start(month_start), _compare_set(compare)),
        as_of=as_of,
        current_value=nw["total"],
        base_currency=base_currency,
        current_user_id=current_user_id,
    )
    return {
        "as_of_month": month,
        "base_currency": base_currency,
        **snapshot_header,
        "net_worth_change": changes if changes else None,
    }


def net_worth_timeline(db: Session, current_user_id: int, months: int, base_currency: str) -> Dict[str, Any]:
    """Stored History rows (stale ones recomputed first, #138) plus the live "now" point."""
    current_month_start = clock._parse_month(clock._current_anchor_ts().strftime("%Y-%m"))
    range_start = _add_months(current_month_start, -(months - 1))
    current_month_key = current_month_start.strftime("%Y-%m")

    _refresh_wealth_rollups(db, current_user_id, base_currency, months=_trailing_month_keys(months))
    points, upload_markers = _stored_timeline_points(db, current_user_id, base_currency, range_start)
    current_state = _current_networth_state(db, base_currency, current_user_id)
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


def timeline_movers(db: Session, current_user_id: int, month_start: datetime, base_currency: str, limit: int) -> Dict[str, Any]:
    # Like for like (#133): the anchor actually used vs the completed anchor one
    # month before it. For the open month both used to resolve to the same date.
    snapshot_month_start = _completed_snapshot_month_start(month_start)
    anchor = _anchor_ts(snapshot_month_start)
    prev_month_start = _add_months(snapshot_month_start, -1)
    prev_anchor = _anchor_ts(prev_month_start)

    nw = _networth_components(db, anchor, base_currency, current_user_id)
    prev_nw = _networth_components(db, prev_anchor, base_currency, current_user_id)
    current_holdings = _top_holdings(db, anchor, nw["total"], base_currency, current_user_id, limit=250)
    prior_holdings = _top_holdings(db, prev_anchor, prev_nw["total"], base_currency, current_user_id, limit=250)
    return _top_movers_from_holdings(current_holdings, prior_holdings, prev_month_start.strftime("%Y-%m"), limit=limit)


def summary_without_net_worth(
    db: Session, current_user_id: int, month: str, month_start: datetime, base_currency: str
) -> Dict[str, Any]:
    """/summary?skip_networth=true: the geography, holdings, cash and cash flow
    only. Live for the open month; a past month's month-end snapshot (#223)."""
    month_end = _add_months(month_start, 1)
    view_anchor, is_live = _month_view_anchor(month_start)
    view_nw = _networth_components(db, view_anchor, base_currency, current_user_id, price_overlay=is_live)
    geo = _geography(db, view_anchor, view_nw["total"], base_currency, current_user_id, price_overlay=is_live)
    top = _top_holdings(
        db,
        view_anchor,
        view_nw["total"],
        base_currency,
        current_user_id,
        limit=_summary_top_holdings_limit(),
        price_overlay=is_live,
    )
    return {
        "as_of_month": month,
        "base_currency": base_currency,
        "snapshot_day": _configured_snapshot_day(),
        "is_live": is_live,
        "geography": geo,
        "cash_flow": _cashflow(db, month_start, month_end, base_currency, current_user_id),
        "top_holdings": top,
        "cash_balances": _cash_balances(db, view_anchor, base_currency, current_user_id),
        "cash_percent": _cash_percent(view_nw),
        **fx_status(),
    }


def summary(
    db: Session, current_user_id: int, month: str, month_start: datetime, base_currency: str, compare: str
) -> Dict[str, Any]:
    # Calendar month window for cashflow
    month_end = _add_months(month_start, 1)

    # Snapshot anchor + effective snapshot timestamp. Comparisons are taken
    # relative to the month whose anchor is actually used (#133).
    snapshot_month_start = _completed_snapshot_month_start(month_start)
    anchor = _anchor_ts(snapshot_month_start)
    top_holdings_limit = _summary_top_holdings_limit()

    as_of, snapshot_header = _snapshot_header(db, anchor, current_user_id)
    current_state = _current_networth_state(db, base_currency, current_user_id)
    current_anchor = current_state["anchor"]
    current_nw = current_state["net_worth"]

    nw = _networth_components(db, anchor, base_currency, current_user_id)
    # Geography, positions and cash balances: live for the open month (as the
    # headline is); a past month's are its month-end snapshot, the same anchor
    # and prices as its net worth (#223).
    view_anchor, is_live = _month_view_anchor(month_start)
    view_total = current_nw["total"] if is_live else nw["total"]
    geo = _geography(db, view_anchor, view_total, base_currency, current_user_id, price_overlay=is_live)
    top = _top_holdings(
        db,
        view_anchor,
        view_total,
        base_currency,
        current_user_id,
        limit=top_holdings_limit,
        price_overlay=is_live,
    )
    cash_balances = _cash_balances(db, view_anchor, base_currency, current_user_id)
    cf = _cashflow(db, month_start, month_end, base_currency, current_user_id)

    compare_set = _compare_set(compare)
    nw_cache: Dict[datetime, Dict[str, float]] = {anchor: nw}
    changes = _compute_net_worth_changes(
        db=db,
        compare_months=_snapshot_compare_months(snapshot_month_start, compare_set),
        as_of=as_of,
        current_value=nw["total"],
        base_currency=base_currency,
        current_user_id=current_user_id,
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
        current_user_id=current_user_id,
        nw_cache=nw_cache,
    )
    component_changes = (
        _compute_component_changes(
            db=db,
            month_start=snapshot_month_start,
            as_of=as_of,
            current_components=nw,
            base_currency=base_currency,
            current_user_id=current_user_id,
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
            current_user_id,
            limit=max(top_holdings_limit, 250),
        )
        prev_components = _cached_networth_components(db, prev_anchor, base_currency, current_user_id, nw_cache)
        prev_top = _top_holdings(
            db,
            prev_anchor,
            prev_components["total"],
            base_currency,
            current_user_id,
            limit=max(top_holdings_limit, 250),
        )
        top_movers = _top_movers_from_holdings(snapshot_top, prev_top, prev_month_start.strftime("%Y-%m"))

    # Data completeness indicators from canonical portfolio sources
    completeness_indicators = get_data_completeness_status(db, current_user_id=current_user_id, anchor_date=anchor.date())

    return {
        "as_of_month": month,
        "base_currency": base_currency,
        "snapshot_day": _configured_snapshot_day(),
        "is_live": is_live,
        **_current_header(current_state),
        **snapshot_header,
        "net_worth": _serialize_net_worth(nw),
        "geography": geo,
        "cash_flow": cf,
        "top_holdings": top,
        "cash_balances": cash_balances,
        "net_worth_change": changes if changes else None,
        "current_net_worth_change": current_changes if current_changes else None,
        "net_worth_component_change": component_changes,
        "top_movers": top_movers,
        "cash_percent": _cash_percent(nw),
        "data_completeness_indicators": completeness_indicators if completeness_indicators else None,
        **fx_status(),
    }


def risk_summary(
    db: Session, current_user_id: int, month: str, month_start: datetime, base_currency: str
) -> Dict[str, Any]:
    """/dashboard/risk-summary (#149): /summary's ``net_worth`` and ``top_holdings``,
    computed exactly as ``summary`` computes them, without the rest of its work
    (geography, cash flow, comparisons, movers, completeness)."""
    anchor = _anchor_ts(_completed_snapshot_month_start(month_start))
    nw = _networth_components(db, anchor, base_currency, current_user_id)
    view_anchor, is_live = _month_view_anchor(month_start)
    # summary's view_total: the live headline total (``_current_networth_state``'s
    # components, at the same live anchor) for the open month, else the month-end's.
    view_total = (
        _networth_components(db, view_anchor, base_currency, current_user_id, price_overlay=True)["total"]
        if is_live
        else nw["total"]
    )
    top = _top_holdings(
        db,
        view_anchor,
        view_total,
        base_currency,
        current_user_id,
        limit=_summary_top_holdings_limit(),
        price_overlay=is_live,
    )
    return {
        "as_of_month": month,
        "base_currency": base_currency,
        "snapshot_day": _configured_snapshot_day(),
        "is_live": is_live,
        "net_worth": _serialize_net_worth(nw),
        "top_holdings": top,
        **fx_status(),
    }


def stock_holdings(db: Session, current_user_id: int, month: str, month_start: datetime, base_currency: str) -> Dict[str, Any]:
    # "browse holdings as of {month}" — effective_anchor/is_live decide whether this
    # is live "now" data (current/future month) or a completed historical boundary.
    # stock_current_total/top_holdings/geography_breakdown/platform_breakdown are all
    # anchored to that same point; stock_snapshot_total is the PRIOR month, for a
    # stable "vs last month" comparison (not "vs whatever month happens to be picked").
    effective_anchor, is_live = _effective_anchor_for_month(month_start)
    compare_anchor = _anchor_ts(_add_months(month_start, -1))
    as_of = _effective_as_of(db, effective_anchor, current_user_id)
    holdings_as_of = _positions_coverage_as_of(db, effective_anchor, current_user_id)
    reporting_as_of = effective_anchor if as_of is not None else None
    boundary_exact = as_of.date() == effective_anchor.date() if as_of is not None else False
    freshness_status = "exact" if boundary_exact else ("synthetic" if as_of is not None else "missing")
    nw = _networth_components(db, effective_anchor, base_currency, current_user_id, price_overlay=is_live)
    top = [
        row
        for row in _top_holdings(
            db,
            effective_anchor,
            nw["total"],
            base_currency,
            current_user_id,
            limit=_summary_top_holdings_limit(),
            price_overlay=is_live,
        )
        if str(row.get("asset_class") or "").upper() in {"STOCK", "FUND"}
    ]
    stock_exposure = _stock_exposure(db, effective_anchor, base_currency, current_user_id, price_overlay=is_live)
    compare_stock_exposure = _stock_exposure(db, compare_anchor, base_currency, current_user_id)
    geography_breakdown = _stock_geography_breakdown(stock_exposure, compare_stock_exposure)
    platform_breakdown = _stock_platform_breakdown(stock_exposure, compare_stock_exposure)
    quote_freshness_summary = _quote_freshness_summary(top, is_live=is_live)
    compare_holdings_as_of = _positions_coverage_as_of(db, compare_anchor, current_user_id)
    trend = _stock_trend(db, month_start, base_currency, current_user_id)

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
            db, day_compare_anchor, base_currency, current_user_id, price_overlay=True
        )
        geography_performance = _stock_geography_breakdown(stock_exposure, day_compare_stock_exposure)
        geography_performance_as_of = _iso_value(_effective_as_of(db, day_compare_anchor, current_user_id))

    return {
        "as_of_month": month,
        "base_currency": base_currency,
        "snapshot_day": _configured_snapshot_day(),
        "is_live": is_live,
        "compare_month": _add_months(month_start, -1).strftime("%Y-%m"),
        "current_holdings_as_of": holdings_as_of.isoformat() if holdings_as_of else None,
        "net_worth_as_of": reporting_as_of.isoformat() if reporting_as_of else None,
        "net_worth_snapshot_as_of": _iso_value(_effective_as_of(db, compare_anchor, current_user_id)),
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
        "stock_snapshot_missing": baseline_missing(compare_holdings_as_of, compare_stock_exposure["total"]),
        "quote_stale_days": _quote_stale_days(),
        **fx_status(),
    }


def net_worth_since_update(db: Session, current_user_id: int, base_currency: str) -> Dict[str, Any]:
    """Since-last-update net-worth delta: current live state vs. the last
    available prior data point (not a fixed calendar day — if prices haven't
    refreshed in days, both anchors resolve to the same data and the delta is 0).
    """
    top_holdings_limit = _summary_top_holdings_limit()
    current_anchor = clock._current_anchor_ts()
    compare_anchor = _previous_update_anchor_ts(current_anchor)
    current_as_of = _effective_as_of(db, current_anchor, current_user_id)
    compare_as_of = _effective_as_of(db, compare_anchor, current_user_id)
    compare_label = compare_as_of.isoformat() if compare_as_of else "unknown"

    # price_overlay=True on both sides (unlike the monthly comparisons elsewhere)
    # so the delta reflects the anchor-scoped `prices` table rather than a frozen
    # position snapshot — see the matching comment in stock_holdings.
    current_nw = _networth_components(db, current_anchor, base_currency, current_user_id, price_overlay=True)
    compare_nw = _networth_components(db, compare_anchor, base_currency, current_user_id, price_overlay=True)

    def _change(current_value: float, previous_value: float) -> dict[str, Any]:
        abs_change = current_value - previous_value
        return {
            "abs": abs_change,
            "pct": (abs_change / previous_value) if previous_value > 0 else None,
            "current_as_of": current_as_of.isoformat() if current_as_of else None,
            "compare_as_of": compare_as_of.isoformat() if compare_as_of else None,
            "compare_month": compare_label,
            "compare_value": previous_value,
            "baseline_missing": baseline_missing(compare_as_of, previous_value),
        }

    snapshot_top = _top_holdings(
        db,
        current_anchor,
        current_nw["total"],
        base_currency,
        current_user_id,
        limit=max(top_holdings_limit, 250),
        price_overlay=True,
    )
    prev_top = _top_holdings(
        db,
        compare_anchor,
        compare_nw["total"],
        base_currency,
        current_user_id,
        limit=max(top_holdings_limit, 250),
        price_overlay=True,
    )
    return {
        "base_currency": base_currency,
        "current_as_of": current_as_of.isoformat() if current_as_of else None,
        "compare_as_of": compare_as_of.isoformat() if compare_as_of else None,
        "net_worth_change": _change(current_nw["total"], compare_nw["total"]),
        "component_change": {key: _change(current_nw[key], compare_nw[key]) for key in ("cash", "stocks_funds", "crypto")},
        "top_movers": _top_movers_from_holdings(snapshot_top, prev_top, compare_label, limit=5),
    }


def platform_allocation(
    db: Session, current_user_id: int, month: str, month_start: datetime, base_currency: str
) -> Dict[str, Any]:
    # Live (quote-priced) for the open month, like the Overview headline; a past
    # month is its month-end snapshot at statement prices, the same anchor as
    # its net worth (#223; this used to discard `month`, see #197).
    anchor, is_live = _month_view_anchor(month_start)
    as_of = _effective_as_of(db, anchor, current_user_id)
    payload = _platform_allocation(db, anchor, base_currency, current_user_id, price_overlay=is_live)
    return {
        "as_of": as_of.isoformat() if as_of else None,
        "as_of_month": month,
        "is_live": is_live,
        "total": payload["total"],
        "items": payload["items"],
    }


def cash_deposits(db: Session, current_user_id: int, month: str, month_start: datetime, base_currency: str) -> Dict[str, Any]:
    # "browse cash as of {month}" — effective_anchor/is_live decide whether this is
    # live "now" data (current/future month) or a completed historical boundary.
    # The "Where cash sits" breakdown (payload/items) and current_total both follow
    # that same point; snapshot_total is the PRIOR month, for a stable "vs last
    # month" comparison (not "vs whatever month happens to be picked").
    effective_anchor, is_live = _effective_anchor_for_month(month_start)
    compare_anchor = _anchor_ts(_add_months(month_start, -1))
    payload = _cash_deposits(db, effective_anchor, base_currency, current_user_id)
    snapshot_balances = _cash_balances(db, compare_anchor, base_currency, current_user_id) + _stablecoin_cash_balances(
        db, compare_anchor, base_currency, current_user_id
    )
    current_balances = _cash_balances(db, effective_anchor, base_currency, current_user_id) + _stablecoin_cash_balances(
        db, effective_anchor, base_currency, current_user_id
    )
    current_total = _sum_balances(current_balances)
    snapshot_total = _sum_balances(snapshot_balances)
    delta_abs = current_total - snapshot_total
    snapshot_cash_as_of = _effective_as_of(db, compare_anchor, current_user_id)
    return {
        "total": payload["total"],
        "items": payload["items"],
        "as_of_month": month,
        "base_currency": base_currency,
        "snapshot_day": _configured_snapshot_day(),
        "is_live": is_live,
        "compare_month": _add_months(month_start, -1).strftime("%Y-%m"),
        "current_cash_as_of": _iso_value(_effective_as_of(db, effective_anchor, current_user_id)),
        "snapshot_cash_as_of": _iso_value(snapshot_cash_as_of),
        "current_total": current_total,
        "snapshot_total": snapshot_total,
        "delta_abs": delta_abs,
        "delta_pct": (delta_abs / snapshot_total) if snapshot_total > 0 else None,
        "trend": _cash_trend(db, month_start, base_currency, current_user_id),
        "currency_breakdown": _cash_currency_breakdown(current_balances, snapshot_balances),
        "snapshot_missing": baseline_missing(snapshot_cash_as_of, snapshot_total),
    }


def stock_exposure(db: Session, current_user_id: int, month_start: datetime, base_currency: str) -> Dict[str, Any]:
    # Same rule as platform_allocation (#223; this used to discard `month`).
    anchor, is_live = _month_view_anchor(month_start)
    as_of = _positions_coverage_as_of(db, anchor, current_user_id)
    payload = _stock_exposure(db, anchor, base_currency, current_user_id, price_overlay=is_live)
    return {
        "as_of": as_of.isoformat() if as_of else None,
        "is_live": is_live,
        "base_currency": base_currency,
        "total": payload["total"],
        "by_country": payload["by_country"],
        "by_platform": payload["by_platform"],
    }


def geography_exposure(db: Session, current_user_id: int, month_start: datetime, base_currency: str) -> Dict[str, Any]:
    anchor = _completed_snapshot_anchor_ts(month_start)
    as_of = _effective_as_of(db, anchor, current_user_id)
    # A completed month-end: valued like that month's net worth, at its
    # statements' prices, not today's quotes (#144).
    payload = _geography_exposure(db, anchor, base_currency, current_user_id, price_overlay=False)
    return {
        "as_of": as_of.isoformat() if as_of else None,
        "base_currency": base_currency,
        "total": payload["total"],
        "items": payload["items"],
    }
