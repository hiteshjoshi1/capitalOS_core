from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import get_db

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def dashboard_summary(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
):
    # ---- Validate month ----
    try:
        start = datetime.strptime(month + "-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return {"error": "Invalid month format. Use YYYY-MM"}

    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)

    # --------------------------
    # NET WORTH (cost_basis_base for now)
    # --------------------------
    nw_sql = text("""
        SELECT
          COALESCE(SUM(CASE WHEN a.asset_class='CASH' THEN p.cost_basis_base ELSE 0 END),0) AS cash,
          COALESCE(SUM(CASE WHEN a.asset_class IN ('STOCK','FUND') THEN p.cost_basis_base ELSE 0 END),0) AS stocks_funds,
          COALESCE(SUM(CASE WHEN a.asset_class='CRYPTO' THEN p.cost_basis_base ELSE 0 END),0) AS crypto,
          COALESCE(SUM(CASE WHEN a.asset_class='BOND' THEN p.cost_basis_base ELSE 0 END),0) AS bonds
        FROM positions p
        JOIN assets a ON a.id = p.asset_id
        WHERE p.as_of >= :start AND p.as_of < :end
    """)

    nw = db.execute(nw_sql, {"start": start, "end": end}).mappings().one()

    cash = float(nw["cash"])
    stocks_funds = float(nw["stocks_funds"])
    crypto = float(nw["crypto"])
    liabilities = 0.0  # loan modeling later
    total = cash + stocks_funds + crypto - liabilities

    # --------------------------
    # GEOGRAPHY
    # --------------------------
    geo_sql = text("""
    SELECT
      COALESCE(a.home_country,'UNKNOWN') AS country,
      SUM(p.cost_basis_base) AS value
    FROM positions p
    JOIN assets a ON a.id = p.asset_id
    WHERE p.as_of >= :start AND p.as_of < :end
    GROUP BY a.home_country
""")


    geo_rows = db.execute(geo_sql, {"start": start, "end": end}).mappings().all()

    geography = []
    for r in geo_rows:
        value = float(r["value"])
        percent = (value / total * 100) if total > 0 else 0
        geography.append({
            "country": r["country"],
            "value": value,
            "percent": round(percent, 2),
        })

    # --------------------------
    # CASH FLOW
    # --------------------------
    cf_sql = text("""
        SELECT
          COALESCE(SUM(CASE WHEN type='INCOME' THEN amount ELSE 0 END),0) AS income,
          COALESCE(SUM(CASE WHEN type IN ('EXPENSE','FEE','TAX','INTEREST') THEN -amount ELSE 0 END),0) AS expenses
        FROM transactions
        WHERE ts >= :start AND ts < :end
          AND currency = :base_currency
    """)

    cf = db.execute(cf_sql, {"start": start, "end": end, "base_currency": base_currency}).mappings().one()

    income = float(cf["income"])
    expenses = float(cf["expenses"])
    net = income - expenses
    savings_rate = (net / income) if income > 0 else None

    # --------------------------
    # TOP HOLDINGS
    # --------------------------
    top_sql = text("""
        SELECT
          a.id,
          a.symbol,
          a.asset_class,
          p.cost_basis_base AS value
        FROM positions p
        JOIN assets a ON a.id = p.asset_id
        WHERE p.as_of >= :start AND p.as_of < :end
        ORDER BY p.cost_basis_base DESC
        LIMIT 5
    """)

    top_rows = db.execute(top_sql, {"start": start, "end": end}).mappings().all()

    top_holdings = []
    for r in top_rows:
        value = float(r["value"])
        percent = (value / total * 100) if total > 0 else 0
        top_holdings.append({
            "asset_id": r["id"],
            "symbol": r["symbol"],
            "asset_class": r["asset_class"],
            "value": value,
            "percent_of_networth": round(percent, 2),
        })

    return {
        "as_of_month": month,
        "base_currency": base_currency,
        "net_worth": {
            "total": total,
            "cash": cash,
            "stocks_funds": stocks_funds,
            "crypto": crypto,
            "liabilities": liabilities,
        },
        "geography": geography,
        "cash_flow": {
            "income": income,
            "expenses": expenses,
            "net": net,
            "savings_rate": savings_rate,
        },
        "top_holdings": top_holdings,
    }
