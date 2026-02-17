from __future__ import annotations

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.spending import (
    SpendingSummaryOut,
    CategoryAmount,
    CreditCardSummaryOut,
    CreditCardItem,
)

router = APIRouter(prefix="/spending", tags=["spending"])


def _parse_month(month: str) -> datetime:
    try:
        return datetime.strptime(month + "-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid month format. Use YYYY-MM, e.g. 2026-02")


def _add_months(dt: datetime, months: int) -> datetime:
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    return dt.replace(year=y, month=m)


def _month_end(dt: datetime) -> datetime:
    return _add_months(dt, 1)


def _clamp_day(dt: datetime, day: int) -> datetime:
    month_end = _month_end(dt)
    last_day = (month_end - timedelta(days=1)).day
    safe_day = min(day, last_day)
    return dt.replace(day=safe_day)


@router.get("/summary", response_model=SpendingSummaryOut)
def spending_summary(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
):
    start = _parse_month(month)
    end = _month_end(start)

    totals_q = text("""
        SELECT
          COALESCE(SUM(CASE WHEN type='INCOME' THEN amount ELSE 0 END),0) AS income,
          COALESCE(SUM(CASE WHEN type IN ('EXPENSE','FEE','TAX','INTEREST') THEN -amount ELSE 0 END),0) AS expenses
        FROM transactions
        WHERE ts >= :start AND ts < :end
          AND currency = :base_currency
    """)
    totals = db.execute(totals_q, {"start": start, "end": end, "base_currency": base_currency}).mappings().one()
    income_total = float(totals["income"])
    expense_total = float(totals["expenses"])
    net = income_total - expense_total
    savings_rate = (net / income_total) if income_total > 0 else None

    categories_q = text("""
        SELECT
          COALESCE(category, 'Uncategorized') AS category,
          COALESCE(SUM(CASE WHEN type='INCOME' THEN amount ELSE 0 END),0) AS income,
          COALESCE(SUM(CASE WHEN type IN ('EXPENSE','FEE','TAX','INTEREST') THEN -amount ELSE 0 END),0) AS expenses
        FROM transactions
        WHERE ts >= :start AND ts < :end
          AND currency = :base_currency
        GROUP BY COALESCE(category, 'Uncategorized')
        ORDER BY COALESCE(SUM(CASE WHEN type IN ('EXPENSE','FEE','TAX','INTEREST') THEN -amount ELSE 0 END),0) DESC
    """)
    rows = db.execute(categories_q, {"start": start, "end": end, "base_currency": base_currency}).mappings().all()

    income_categories = []
    expense_categories = []
    for r in rows:
        if float(r["income"]) > 0:
            income_categories.append(CategoryAmount(category=r["category"], amount=float(r["income"])))
        if float(r["expenses"]) > 0:
            expense_categories.append(CategoryAmount(category=r["category"], amount=float(r["expenses"])))

    return SpendingSummaryOut(
        month=month,
        base_currency=base_currency,
        income_total=income_total,
        expense_total=expense_total,
        net=net,
        savings_rate=savings_rate,
        income_categories=income_categories,
        expense_categories=expense_categories,
    )


@router.get("/credit-cards", response_model=CreditCardSummaryOut)
def credit_card_summary(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
):
    start = _parse_month(month)
    end = _month_end(start)

    cards_q = text("""
        SELECT
          a.id AS account_id,
          a.name AS account_name,
          cc.card_name,
          cc.issuer,
          cc.credit_limit,
          cc.statement_day,
          cc.due_day
        FROM credit_card_accounts cc
        JOIN accounts a ON a.id = cc.account_id
        ORDER BY a.name
    """)
    cards = db.execute(cards_q).mappings().all()

    spend_q = text("""
        SELECT
          account_id,
          COALESCE(SUM(-amount),0) AS spend
        FROM transactions
        WHERE ts >= :start AND ts < :end
          AND currency = :base_currency
          AND type IN ('EXPENSE','FEE','TAX','INTEREST')
        GROUP BY account_id
    """)
    spend_rows = db.execute(spend_q, {"start": start, "end": end, "base_currency": base_currency}).mappings().all()
    spend_by_account = {int(r["account_id"]): float(r["spend"]) for r in spend_rows}

    items = []
    for c in cards:
        credit_limit = float(c["credit_limit"])
        current_due = spend_by_account.get(int(c["account_id"]), 0.0)
        utilization = (current_due / credit_limit) if credit_limit > 0 else None
        due_date = _clamp_day(start, int(c["due_day"])).date().isoformat()
        items.append(
            CreditCardItem(
                account_id=int(c["account_id"]),
                account_name=c["account_name"],
                card_name=c["card_name"],
                issuer=c["issuer"],
                credit_limit=credit_limit,
                statement_day=int(c["statement_day"]),
                due_day=int(c["due_day"]),
                due_date=due_date,
                current_due=current_due,
                utilization=utilization,
            )
        )

    total_spend = sum(i.current_due for i in items)
    return CreditCardSummaryOut(
        month=month,
        base_currency=base_currency,
        total_spend=total_spend,
        cards=items,
    )
