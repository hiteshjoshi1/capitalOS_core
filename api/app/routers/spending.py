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
    CreditCardDetailOut,
    CreditCardTransactionItem,
    CreditCardRecurringPaymentItem,
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


def _tx_iso(value: datetime | str) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _month_key(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m")
    as_text = str(value)
    return as_text[:7]


def _credit_cards(db: Session):
    cards_q = text("""
        SELECT
          a.id AS account_id,
          a.name AS account_name,
          a.currency AS account_currency,
          COALESCE(NULLIF(TRIM(cc.card_name), ''), a.name) AS card_name,
          COALESCE(NULLIF(TRIM(cc.issuer), ''), a.platform) AS issuer,
          COALESCE(cc.credit_limit, 0) AS credit_limit,
          COALESCE(cc.statement_day, 1) AS statement_day,
          COALESCE(cc.due_day, 1) AS due_day
        FROM accounts a
        LEFT JOIN credit_card_accounts cc ON cc.account_id = a.id
        WHERE a.account_type = 'CREDIT_CARD'
        ORDER BY a.name
    """)
    return db.execute(cards_q).mappings().all()


def _spend_by_account(
    db: Session,
    start: datetime,
    end: datetime,
    base_currency: str,
) -> dict[int, float]:
    spend_q = text("""
        SELECT
          t.account_id,
          t.amount,
          t.currency
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE t.ts >= :start AND t.ts < :end
          AND a.account_type = 'CREDIT_CARD'
          AND t.type IN ('EXPENSE','FEE','TAX','INTEREST')
    """)
    spend_rows = db.execute(spend_q, {"start": start, "end": end}).mappings().all()
    currencies = {r["currency"] for r in spend_rows if r["currency"]}
    rates = get_rates(start, base_currency, currencies)
    spend: dict[int, float] = {}
    for row in spend_rows:
        cur = (row["currency"] or base_currency).upper()
        converted = float(row["amount"]) * rates.get(cur, 1.0)
        account_id = int(row["account_id"])
        spend[account_id] = spend.get(account_id, 0.0) + (-converted)
    return spend


def _credit_card_items(
    cards,
    spend_by_account: dict[int, float],
    start: datetime,
    base_currency: str,
) -> list[CreditCardItem]:
    account_currencies = {(c["account_currency"] or base_currency).upper() for c in cards}
    account_rates = get_rates(start, base_currency, account_currencies)
    items: list[CreditCardItem] = []
    for card in cards:
        account_currency = (card["account_currency"] or base_currency).upper()
        rate = account_rates.get(account_currency, 1.0)
        credit_limit = float(card["credit_limit"]) * rate
        current_due = spend_by_account.get(int(card["account_id"]), 0.0)
        utilization = (current_due / credit_limit) if credit_limit > 0 else None
        due_date = _clamp_day(start, int(card["due_day"])).date().isoformat()
        items.append(
            CreditCardItem(
                account_id=int(card["account_id"]),
                account_name=card["account_name"],
                card_name=card["card_name"],
                issuer=card["issuer"],
                credit_limit=credit_limit,
                statement_day=int(card["statement_day"]),
                due_day=int(card["due_day"]),
                due_date=due_date,
                current_due=current_due,
                utilization=utilization,
            )
        )
    return items


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
          t.type,
          t.amount,
          t.currency,
          COALESCE(ct.name, NULLIF(TRIM(t.category), ''), 'Uncategorized') AS category
        FROM transactions t
        LEFT JOIN category_overrides co ON co.transaction_id = t.id
        LEFT JOIN category_taxonomy ct ON ct.id = co.category_id
        WHERE t.ts >= :start AND t.ts < :end
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

    cards = _credit_cards(db)
    spend = _spend_by_account(db, start, end, base_currency)
    items = _credit_card_items(cards, spend, start, base_currency)

    total_spend = sum(i.current_due for i in items)
    return CreditCardSummaryOut(
        month=month,
        base_currency=base_currency,
        total_spend=total_spend,
        cards=items,
    )


@router.get("/credit-card-transactions", response_model=CreditCardDetailOut)
def credit_card_transactions(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
):
    start = _parse_month(month)
    end = _month_end(start)
    lookback_start = _add_months(start, -2)

    cards = _credit_cards(db)
    spend = _spend_by_account(db, start, end, base_currency)
    card_items = _credit_card_items(cards, spend, start, base_currency)

    tx_q = text("""
        SELECT
          t.account_id,
          a.name AS account_name,
          COALESCE(NULLIF(TRIM(cc.card_name), ''), a.name) AS card_name,
          COALESCE(NULLIF(TRIM(cc.issuer), ''), a.platform) AS issuer,
          t.ts,
          t.amount,
          t.type,
          t.currency,
          t.category,
          COALESCE(ct.name, NULLIF(TRIM(t.category), ''), 'Uncategorized') AS resolved_category,
          CASE
            WHEN co.source IS NOT NULL THEN co.source
            WHEN t.category IS NOT NULL
                 AND TRIM(t.category) <> ''
                 AND LOWER(TRIM(t.category)) <> 'uncategorized' THEN 'parser'
            ELSE 'uncategorized'
          END AS category_source,
          t.merchant_counterparty,
          t.notes
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        LEFT JOIN credit_card_accounts cc ON cc.account_id = t.account_id
        LEFT JOIN category_overrides co ON co.transaction_id = t.id
        LEFT JOIN category_taxonomy ct ON ct.id = co.category_id
        WHERE t.ts >= :start AND t.ts < :end
          AND a.account_type = 'CREDIT_CARD'
        ORDER BY t.ts DESC, t.id DESC
    """)
    tx_rows = db.execute(tx_q, {"start": start, "end": end}).mappings().all()
    tx_currencies = {r["currency"] for r in tx_rows if r["currency"]}
    tx_rates = get_rates(start, base_currency, tx_currencies)

    transactions: list[CreditCardTransactionItem] = []
    for row in tx_rows:
        cur = (row["currency"] or base_currency).upper()
        converted = float(row["amount"]) * tx_rates.get(cur, 1.0)
        description = row["merchant_counterparty"] or row["resolved_category"] or row["category"] or "Transaction"
        transactions.append(
            CreditCardTransactionItem(
                account_id=int(row["account_id"]),
                account_name=row["account_name"],
                card_name=row["card_name"],
                issuer=row["issuer"],
                ts=_tx_iso(row["ts"]),
                description=description,
                amount=converted,
                type=row["type"],
                category=row["category"],
                resolved_category=row["resolved_category"],
                category_source=row["category_source"],
                merchant_counterparty=row["merchant_counterparty"],
                notes=row["notes"],
            )
        )

    top_purchases = sorted(
        (tx for tx in transactions if tx.type == "EXPENSE"),
        key=lambda tx: abs(tx.amount),
        reverse=True,
    )[:5]

    recurring_q = text("""
        SELECT
          t.account_id,
          a.name AS account_name,
          COALESCE(NULLIF(TRIM(cc.card_name), ''), a.name) AS card_name,
          COALESCE(NULLIF(TRIM(cc.issuer), ''), a.platform) AS issuer,
          t.ts,
          t.amount,
          t.currency,
          t.merchant_counterparty
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        LEFT JOIN credit_card_accounts cc ON cc.account_id = t.account_id
        WHERE t.ts >= :lookback_start AND t.ts < :end
          AND a.account_type = 'CREDIT_CARD'
          AND t.type = 'EXPENSE'
          AND COALESCE(TRIM(t.merchant_counterparty), '') <> ''
        ORDER BY t.ts DESC, t.id DESC
    """)
    recurring_rows = db.execute(
        recurring_q, {"lookback_start": lookback_start, "end": end}
    ).mappings().all()
    recurring_currencies = {r["currency"] for r in recurring_rows if r["currency"]}
    recurring_rates = get_rates(start, base_currency, recurring_currencies)

    recurring_index: dict[tuple[int, str], dict] = {}
    for row in recurring_rows:
        merchant = str(row["merchant_counterparty"]).strip()
        key = (int(row["account_id"]), merchant)
        cur = (row["currency"] or base_currency).upper()
        converted = float(row["amount"]) * recurring_rates.get(cur, 1.0)
        record = recurring_index.setdefault(
            key,
            {
                "account_id": int(row["account_id"]),
                "account_name": row["account_name"],
                "card_name": row["card_name"],
                "issuer": row["issuer"],
                "merchant_counterparty": merchant,
                "months": set(),
                "current_month_amount": 0.0,
            },
        )
        month_key = _month_key(row["ts"])
        record["months"].add(month_key)
        if month_key == month:
            record["current_month_amount"] += -converted

    recurring_payments: list[CreditCardRecurringPaymentItem] = []
    for record in recurring_index.values():
        months_present = len(record["months"])
        current_month_amount = float(record["current_month_amount"])
        if months_present < 2 or current_month_amount <= 0:
            continue
        recurring_payments.append(
            CreditCardRecurringPaymentItem(
                account_id=record["account_id"],
                account_name=record["account_name"],
                card_name=record["card_name"],
                issuer=record["issuer"],
                merchant_counterparty=record["merchant_counterparty"],
                months_present=months_present,
                current_month_amount=current_month_amount,
            )
        )

    recurring_payments.sort(
        key=lambda item: (item.current_month_amount, item.merchant_counterparty.lower()),
        reverse=True,
    )

    total_spend = sum(item.current_due for item in card_items)
    return CreditCardDetailOut(
        month=month,
        base_currency=base_currency,
        total_spend=total_spend,
        cards=card_items,
        transactions=transactions,
        top_purchases=top_purchases,
        recurring_payments=recurring_payments,
    )
