from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _parse_month(month: str) -> datetime:
    """month: 'YYYY-MM' -> tz-aware datetime at month start (UTC)."""
    try:
        return datetime.strptime(month + "-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid month format. Use YYYY-MM, e.g. 2026-02")


def _add_months(dt: datetime, months: int) -> datetime:
    """Add months to a datetime (month start)."""
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    return dt.replace(year=y, month=m)


def _anchor_ts(month_start: datetime, snapshot_day: int) -> datetime:
    """Anchor timestamp: YYYY-MM-snapshot_day at 00:00Z."""
    # snapshot_day assumed valid (1-28ish); 6 is always safe
    return month_start.replace(day=snapshot_day, hour=0, minute=0, second=0, microsecond=0)


def _effective_as_of(db: Session, anchor_ts: datetime) -> Optional[datetime]:
    """
    Pick the effective snapshot timestamp:
    max(positions.as_of) where as_of <= anchor_ts.
    Returns None if no snapshots exist at/before anchor.
    """
    q = text("SELECT MAX(as_of) AS as_of FROM positions WHERE as_of <= :anchor_ts")
    r = db.execute(q, {"anchor_ts": anchor_ts}).mappings().one()
    as_of = r["as_of"]
    if isinstance(as_of, str):
        try:
            as_of = datetime.fromisoformat(as_of)
        except ValueError:
            return None
    if isinstance(as_of, datetime) and as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    return as_of


def _networth_components(db: Session, as_of: Optional[datetime]) -> Dict[str, float]:
    """Compute net worth components for a given snapshot timestamp."""
    if as_of is None:
        return {"cash": 0.0, "stocks_funds": 0.0, "crypto": 0.0, "liabilities": 0.0, "total": 0.0}

    q = text("""
        SELECT
          COALESCE(SUM(CASE WHEN a.asset_class='CASH' THEN p.cost_basis_base ELSE 0 END),0) AS cash,
          COALESCE(SUM(CASE WHEN a.asset_class IN ('STOCK','FUND') THEN p.cost_basis_base ELSE 0 END),0) AS stocks_funds,
          COALESCE(SUM(CASE WHEN a.asset_class='CRYPTO' THEN p.cost_basis_base ELSE 0 END),0) AS crypto
        FROM positions p
        JOIN assets a ON a.id = p.asset_id
        WHERE p.as_of = :as_of
    """)
    r = db.execute(q, {"as_of": as_of}).mappings().one()
    cash = float(r["cash"])
    stocks_funds = float(r["stocks_funds"])
    crypto = float(r["crypto"])
    liabilities = 0.0  # later when loans modeled
    total = cash + stocks_funds + crypto - liabilities
    return {
        "cash": cash,
        "stocks_funds": stocks_funds,
        "crypto": crypto,
        "liabilities": liabilities,
        "total": total,
    }


def _geography(db: Session, as_of: Optional[datetime], total: float) -> List[Dict[str, Any]]:
    if as_of is None or total <= 0:
        return []
    q = text("""
        SELECT
          COALESCE(a.home_country,'UNKNOWN') AS country,
          SUM(p.cost_basis_base) AS value
        FROM positions p
        JOIN assets a ON a.id = p.asset_id
        WHERE p.as_of = :as_of
        GROUP BY a.home_country
        ORDER BY value DESC
    """)
    rows = db.execute(q, {"as_of": as_of}).mappings().all()
    out = []
    for r in rows:
        value = float(r["value"])
        out.append({
            "country": r["country"],
            "value": value,
            "percent": round((value / total) * 100, 2)
        })
    return out


def _top_holdings(db: Session, as_of: Optional[datetime], total: float, limit: int = 5) -> List[Dict[str, Any]]:
    if as_of is None or total <= 0:
        return []
    q = text(f"""
        SELECT
          a.id AS asset_id,
          a.symbol,
          a.asset_class,
          p.cost_basis_base AS value
        FROM positions p
        JOIN assets a ON a.id = p.asset_id
        WHERE p.as_of = :as_of
        ORDER BY p.cost_basis_base DESC
        LIMIT {limit}
    """)
    rows = db.execute(q, {"as_of": as_of}).mappings().all()
    out = []
    for r in rows:
        value = float(r["value"])
        out.append({
            "asset_id": int(r["asset_id"]),
            "symbol": r["symbol"],
            "asset_class": r["asset_class"],
            "value": value,
            "percent_of_networth": round((value / total) * 100, 2)
        })
    return out


def _cashflow(db: Session, start: datetime, end: datetime, base_currency: str) -> Dict[str, Any]:
    # NOTE: amount is stored signed in your model. We'll treat:
    # - income: sum(amount) where type=INCOME
    # - expenses: sum(-amount) where type in expense-like and amount is negative => positive expenses
    q = text("""
        SELECT
          COALESCE(SUM(CASE WHEN type='INCOME' THEN amount ELSE 0 END),0) AS income,
          COALESCE(SUM(CASE WHEN type IN ('EXPENSE','FEE','TAX','INTEREST') THEN -amount ELSE 0 END),0) AS expenses
        FROM transactions
        WHERE ts >= :start AND ts < :end
          AND currency = :base_currency
    """)
    r = db.execute(q, {"start": start, "end": end, "base_currency": base_currency}).mappings().one()
    income = float(r["income"])
    expenses = float(r["expenses"])
    net = income - expenses
    savings_rate = (net / income) if income > 0 else None
    return {"income": income, "expenses": expenses, "net": net, "savings_rate": savings_rate}


@router.get("/summary")
def dashboard_summary(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    compare: str = Query("", description="Comma-separated: prev_month,prev_year"),
    db: Session = Depends(get_db),
):
    # Configurable snapshot day (default 6)
    snapshot_day = int(os.getenv("SNAPSHOT_DAY", "6"))
    if snapshot_day < 1 or snapshot_day > 28:
        raise HTTPException(status_code=500, detail="SNAPSHOT_DAY must be between 1 and 28")

    # Calendar month window for cashflow
    month_start = _parse_month(month)
    month_end = _add_months(month_start, 1)

    # Snapshot anchor + effective snapshot timestamp
    anchor = _anchor_ts(month_start, snapshot_day)
    as_of = _effective_as_of(db, anchor)

    nw = _networth_components(db, as_of)
    geo = _geography(db, as_of, nw["total"])
    top = _top_holdings(db, as_of, nw["total"], limit=5)
    cf = _cashflow(db, month_start, month_end, base_currency)

    # Comparisons (Option A)
    compare_set = {c.strip() for c in compare.split(",") if c.strip()}
    changes = {}

    def _delta(label: str, other_month_start: datetime):
        other_anchor = _anchor_ts(other_month_start, snapshot_day)
        other_as_of = _effective_as_of(db, other_anchor)
        other_nw = _networth_components(db, other_as_of)

        cur = nw["total"]
        prev = other_nw["total"]
        abs_change = cur - prev
        pct_change = (abs_change / prev) if prev > 0 else None

        changes[label] = {
            "abs": abs_change,
            "pct": pct_change,
            "current_as_of": as_of.isoformat() if as_of else None,
            "compare_as_of": other_as_of.isoformat() if other_as_of else None,
            "compare_month": other_month_start.strftime("%Y-%m"),
        }

    if "prev_month" in compare_set:
        _delta("vs_prev_month", _add_months(month_start, -1))
    if "prev_year" in compare_set:
        _delta("vs_prev_year", _add_months(month_start, -12))

    return {
        "as_of_month": month,
        "base_currency": base_currency,
        "snapshot_day": snapshot_day,
        "net_worth_as_of": as_of.isoformat() if as_of else None,
        "net_worth": {
            "total": nw["total"],
            "cash": nw["cash"],
            "stocks_funds": nw["stocks_funds"],
            "crypto": nw["crypto"],
            "liabilities": nw["liabilities"],
        },
        "geography": geo,
        "cash_flow": cf,
        "top_holdings": top,
        "net_worth_change": changes if changes else None,
    }
