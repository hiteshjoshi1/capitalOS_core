from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.dashboard import PlatformAllocationOut, PlatformAllocationItem
from app.fx import get_rates

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


def _anchor_ts(month_start: datetime) -> datetime:
    """Anchor timestamp: end of month (00:00Z on next month start)."""
    return _add_months(month_start, 1).replace(hour=0, minute=0, second=0, microsecond=0)


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


def _networth_components(db: Session, anchor_ts: datetime, base_currency: str) -> Dict[str, float]:
    """Compute net worth components using latest snapshot per account up to anchor_ts."""
    q = text("""
        WITH latest AS (
          SELECT account_id, MAX(as_of) AS as_of
          FROM positions
          WHERE as_of <= :anchor_ts
          GROUP BY account_id
        )
        SELECT
          a.asset_class,
          a.quote_currency,
          p.cost_basis_base AS value
        FROM positions p
        JOIN latest l ON l.account_id = p.account_id AND l.as_of = p.as_of
        JOIN assets a ON a.id = p.asset_id
    """)
    rows = db.execute(q, {"anchor_ts": anchor_ts}).mappings().all()
    if not rows:
        return {"cash": 0.0, "stocks_funds": 0.0, "crypto": 0.0, "liabilities": 0.0, "total": 0.0}
    currencies = {r["quote_currency"] for r in rows if r["quote_currency"]}
    rates = get_rates(anchor_ts, base_currency, currencies)
    cash = 0.0
    stocks_funds = 0.0
    crypto = 0.0
    for r in rows:
        cur = (r["quote_currency"] or base_currency).upper()
        value = float(r["value"]) * rates.get(cur, 1.0)
        if r["asset_class"] == "CASH":
            cash += value
        elif r["asset_class"] in ("STOCK", "FUND"):
            stocks_funds += value
        elif r["asset_class"] == "CRYPTO":
            crypto += value
    liabilities = 0.0  # later when loans modeled
    total = cash + stocks_funds + crypto - liabilities
    return {
        "cash": cash,
        "stocks_funds": stocks_funds,
        "crypto": crypto,
        "liabilities": liabilities,
        "total": total,
    }


def _geography(db: Session, anchor_ts: datetime, total: float, base_currency: str) -> List[Dict[str, Any]]:
    if total <= 0:
        return []
    q = text("""
        WITH latest AS (
          SELECT account_id, MAX(as_of) AS as_of
          FROM positions
          WHERE as_of <= :anchor_ts
          GROUP BY account_id
        )
        SELECT
          COALESCE(a.home_country,'UNKNOWN') AS country,
          a.quote_currency,
          p.cost_basis_base AS value
        FROM positions p
        JOIN latest l ON l.account_id = p.account_id AND l.as_of = p.as_of
        JOIN assets a ON a.id = p.asset_id
    """)
    rows = db.execute(q, {"anchor_ts": anchor_ts}).mappings().all()
    currencies = {r["quote_currency"] for r in rows if r["quote_currency"]}
    rates = get_rates(anchor_ts, base_currency, currencies)
    buckets: Dict[str, float] = {}
    for r in rows:
        cur = (r["quote_currency"] or base_currency).upper()
        value = float(r["value"]) * rates.get(cur, 1.0)
        buckets[r["country"]] = buckets.get(r["country"], 0.0) + value
    out = []
    for country, value in sorted(buckets.items(), key=lambda x: x[1], reverse=True):
        out.append({
            "country": country,
            "value": value,
            "percent": round((value / total) * 100, 2)
        })
    return out


def _top_holdings(db: Session, anchor_ts: datetime, total: float, base_currency: str, limit: int = 5) -> List[Dict[str, Any]]:
    if total <= 0:
        return []
    q = text("""
        WITH latest AS (
          SELECT account_id, MAX(as_of) AS as_of
          FROM positions
          WHERE as_of <= :anchor_ts
          GROUP BY account_id
        )
        SELECT
          a.id AS asset_id,
          a.symbol,
          a.asset_class,
          a.quote_currency,
          p.cost_basis_base AS value
        FROM positions p
        JOIN latest l ON l.account_id = p.account_id AND l.as_of = p.as_of
        JOIN assets a ON a.id = p.asset_id
    """)
    rows = db.execute(q, {"anchor_ts": anchor_ts}).mappings().all()
    currencies = {r["quote_currency"] for r in rows if r["quote_currency"]}
    rates = get_rates(anchor_ts, base_currency, currencies)
    agg: Dict[int, Dict[str, Any]] = {}
    for r in rows:
        asset_id = int(r["asset_id"])
        cur = (r["quote_currency"] or base_currency).upper()
        value = float(r["value"]) * rates.get(cur, 1.0)
        if asset_id not in agg:
            agg[asset_id] = {
                "asset_id": asset_id,
                "symbol": r["symbol"],
                "asset_class": r["asset_class"],
                "value": 0.0,
            }
        agg[asset_id]["value"] += value
    out = sorted(agg.values(), key=lambda x: x["value"], reverse=True)[:limit]
    for r in out:
        value = float(r["value"])
        r["percent_of_networth"] = round((value / total) * 100, 2)
    return out


def _cashflow(db: Session, start: datetime, end: datetime, base_currency: str) -> Dict[str, Any]:
    q = text("""
        SELECT
          type,
          amount,
          currency
        FROM transactions
        WHERE ts >= :start AND ts < :end
    """)
    rows = db.execute(q, {"start": start, "end": end}).mappings().all()
    currencies = {r["currency"] for r in rows if r["currency"]}
    rates = get_rates(start, base_currency, currencies)
    income = 0.0
    expenses = 0.0
    for r in rows:
        cur = (r["currency"] or base_currency).upper()
        amount = float(r["amount"]) * rates.get(cur, 1.0)
        if r["type"] == "INCOME":
            income += amount
        elif r["type"] in ("EXPENSE", "FEE", "TAX", "INTEREST"):
            expenses += -amount
    net = income - expenses
    savings_rate = (net / income) if income > 0 else None
    return {"income": income, "expenses": expenses, "net": net, "savings_rate": savings_rate}


def _platform_allocation(db: Session, anchor_ts: datetime, base_currency: str) -> dict:
    q = text("""
        WITH latest AS (
          SELECT account_id, MAX(as_of) AS as_of
          FROM positions
          WHERE as_of <= :anchor_ts
          GROUP BY account_id
        )
        SELECT
          COALESCE(pl.code, a.platform) AS platform,
          pl.platform_type AS platform_type,
          COALESCE(pl.country, a.country) AS country,
          a2.quote_currency AS quote_currency,
          p.cost_basis_base AS value
        FROM positions p
        JOIN latest l ON l.account_id = p.account_id AND l.as_of = p.as_of
        JOIN accounts a ON a.id = p.account_id
        LEFT JOIN platforms pl ON pl.id = a.platform_id
        JOIN assets a2 ON a2.id = p.asset_id
    """)
    rows = db.execute(q, {"anchor_ts": anchor_ts}).mappings().all()
    if not rows:
        return {"as_of": None, "total": 0.0, "items": []}
    currencies = {r["quote_currency"] for r in rows if r["quote_currency"]}
    rates = get_rates(anchor_ts, base_currency, currencies)
    buckets: Dict[tuple, float] = {}
    for r in rows:
        key = (r["platform"], r["platform_type"], r["country"])
        cur = (r["quote_currency"] or base_currency).upper()
        value = float(r["value"]) * rates.get(cur, 1.0)
        buckets[key] = buckets.get(key, 0.0) + value
    total = sum(buckets.values())
    items = []
    for (platform, platform_type, country), value in sorted(buckets.items(), key=lambda x: x[1], reverse=True):
        percent = round((value / total) * 100, 2) if total > 0 else 0.0
        items.append({
            "platform": platform,
            "platform_type": platform_type,
            "country": country,
            "value": value,
            "percent": percent,
        })
    return {"as_of": None, "total": total, "items": items}


@router.get("/summary")
def dashboard_summary(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    compare: str = Query("", description="Comma-separated: prev_month,prev_year"),
    db: Session = Depends(get_db),
):
    # Calendar month window for cashflow
    month_start = _parse_month(month)
    month_end = _add_months(month_start, 1)

    # Snapshot anchor + effective snapshot timestamp
    anchor = _anchor_ts(month_start)
    as_of = _effective_as_of(db, anchor)

    nw = _networth_components(db, anchor, base_currency)
    geo = _geography(db, anchor, nw["total"], base_currency)
    top = _top_holdings(db, anchor, nw["total"], base_currency, limit=5)
    cf = _cashflow(db, month_start, month_end, base_currency)

    # Comparisons (Option A)
    compare_set = {c.strip() for c in compare.split(",") if c.strip()}
    changes = {}

    def _delta(label: str, other_month_start: datetime):
        other_anchor = _anchor_ts(other_month_start)
        other_as_of = _effective_as_of(db, other_anchor)
        other_nw = _networth_components(db, other_as_of, base_currency)

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
        "snapshot_day": None,
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


@router.get("/platform-allocation", response_model=PlatformAllocationOut)
def platform_allocation(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
):
    month_start = _parse_month(month)
    anchor = _anchor_ts(month_start)
    as_of = _effective_as_of(db, anchor)
    payload = _platform_allocation(db, anchor, base_currency)
    return PlatformAllocationOut(
        as_of=as_of.isoformat() if as_of else None,
        total=payload["total"],
        items=[PlatformAllocationItem(**item) for item in payload["items"]],
    )
