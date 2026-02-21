from __future__ import annotations

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.fx import get_rates
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
          type,
          amount,
          currency,
          COALESCE(category, 'Uncategorized') AS category
        FROM transactions
        WHERE ts >= :start AND ts < :end
    """)
    rows = db.execute(totals_q, {"start": start, "end": end}).mappings().all()
    currencies = {r["currency"] for r in rows if r["currency"]}
    rates = get_rates(start, base_currency, currencies)

    income_total = 0.0
    expense_total = 0.0
    income_categories: dict[str, float] = {}
    expense_categories: dict[str, float] = {}
    for r in rows:
        cur = (r["currency"] or base_currency).upper()
        amount = float(r["amount"]) * rates.get(cur, 1.0)
        category = r["category"] or "Uncategorized"
        if r["type"] == "INCOME":
            income_total += amount
            income_categories[category] = income_categories.get(category, 0.0) + amount
        elif r["type"] in ("EXPENSE", "FEE", "TAX", "INTEREST"):
            expense_total += -amount
            expense_categories[category] = expense_categories.get(category, 0.0) + (-amount)
    net = income_total - expense_total
    savings_rate = (net / income_total) if income_total > 0 else None

    income_categories_list = [
        CategoryAmount(category=k, amount=v) for k, v in income_categories.items() if v > 0
    ]
    expense_categories_list = [
        CategoryAmount(category=k, amount=v) for k, v in expense_categories.items() if v > 0
    ]

    return SpendingSummaryOut(
        month=month,
        base_currency=base_currency,
        income_total=income_total,
        expense_total=expense_total,
        net=net,
        savings_rate=savings_rate,
        income_categories=income_categories_list,
        expense_categories=expense_categories_list,
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
          a.currency AS account_currency,
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
          amount,
          currency
        FROM transactions
        WHERE ts >= :start AND ts < :end
          AND type IN ('EXPENSE','FEE','TAX','INTEREST')
    """)
    spend_rows = db.execute(spend_q, {"start": start, "end": end}).mappings().all()
    currencies = {r["currency"] for r in spend_rows if r["currency"]}
    rates = get_rates(start, base_currency, currencies)
    spend_by_account: dict[int, float] = {}
    for r in spend_rows:
        cur = (r["currency"] or base_currency).upper()
        amount = float(r["amount"]) * rates.get(cur, 1.0)
        spend_by_account[int(r["account_id"])] = spend_by_account.get(int(r["account_id"]), 0.0) + (-amount)

    items = []
    for c in cards:
        account_currency = (c["account_currency"] or base_currency).upper()
        rate = get_rates(start, base_currency, [account_currency]).get(account_currency, 1.0)
        credit_limit = float(c["credit_limit"]) * rate
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
