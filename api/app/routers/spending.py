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
    CashFlowDetailOut,
    CashFlowDetailSection,
    CashFlowTransactionItem,
    CreditCardSummaryOut,
    CreditCardItem,
    CreditCardDetailOut,
    CreditCardTransactionItem,
    CreditCardRecurringPaymentItem,
)

router = APIRouter(prefix="/spending", tags=["spending"])
INCOME_TYPES = ("INCOME",)
EXPENSE_TYPES = ("EXPENSE", "FEE", "TAX", "INTEREST")
TRANSFER_TYPES = ("TRANSFER",)
EXPLICIT_TRANSFER_RAW_CATEGORIES = {
    "bank::transfer",
    "creditcard::payment",
    "brokerage::transfer",
}
LIKELY_INTERNAL_TRANSFER_MARKERS = (
    "IBKR",
    "INTERACTIVE BROKERS",
    "UOB",
    "OCBC",
    "POSB",
    "COINBASE",
    "OWN ACCOUNT",
    "CARD PAYMENT",
    "CREDIT CARD PAYMENT",
    "SI TO :",
    "REF:SALARY",
)


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


def _cash_flow_rows(db: Session, start: datetime, end: datetime):
    cash_flow_q = text("""
        SELECT
          t.id AS transaction_id,
          t.ts,
          t.account_id,
          a.name AS account_name,
          a.account_type,
          t.amount,
          t.currency,
          t.type,
          t.category AS raw_category,
          COALESCE(override_ct.name, NULLIF(TRIM(t.category), ''), 'Uncategorized') AS resolved_category,
          COALESCE(override_ct.id, parser_ct.id) AS resolved_category_id,
          COALESCE(resolved_ct.code, '') AS resolved_category_code,
          COALESCE(resolved_parent_ct.code, '') AS resolved_parent_category_code,
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
        LEFT JOIN category_overrides co ON co.transaction_id = t.id
        LEFT JOIN category_taxonomy override_ct ON override_ct.id = co.category_id
        LEFT JOIN (
          SELECT MIN(id) AS id, LOWER(TRIM(name)) AS normalized_name
          FROM category_taxonomy
          GROUP BY LOWER(TRIM(name))
          HAVING COUNT(*) = 1
        ) parser_ct
          ON parser_ct.normalized_name = LOWER(TRIM(COALESCE(t.category, '')))
        LEFT JOIN category_taxonomy resolved_ct
          ON resolved_ct.id = COALESCE(override_ct.id, parser_ct.id)
        LEFT JOIN category_taxonomy resolved_parent_ct
          ON resolved_parent_ct.id = resolved_ct.parent_id
        WHERE t.ts >= :start AND t.ts < :end
          AND t.type IN ('INCOME', 'EXPENSE', 'FEE', 'TAX', 'INTEREST', 'TRANSFER')
        ORDER BY t.ts DESC, t.id DESC
    """)
    return db.execute(cash_flow_q, {"start": start, "end": end}).mappings().all()


def _is_transfer_resolved_category(row) -> bool:
    resolved_code = str(row.get("resolved_category_code") or "").strip().lower()
    parent_code = str(row.get("resolved_parent_category_code") or "").strip().lower()
    return resolved_code == "transfer" or parent_code == "transfer"


def _is_explicit_source_transfer(row) -> bool:
    raw_category = str(row.get("raw_category") or "").strip().lower()
    if raw_category in EXPLICIT_TRANSFER_RAW_CATEGORIES:
        return True
    text = " ".join(
        [
            str(row.get("merchant_counterparty") or ""),
            str(row.get("notes") or ""),
        ]
    ).upper()
    if str(row.get("type") or "").upper() != "TRANSFER":
        return False
    return any(marker in text for marker in LIKELY_INTERNAL_TRANSFER_MARKERS)


def _cash_flow_bucket(row) -> str | None:
    if _is_transfer_resolved_category(row) or _is_explicit_source_transfer(row):
        return None
    if row["type"] in INCOME_TYPES:
        return "income"
    if row["type"] in EXPENSE_TYPES:
        return "expense"
    if row["type"] in TRANSFER_TYPES:
        amount = float(row.get("amount") or 0.0)
        if amount > 0:
            return "income"
        if amount < 0:
            return "expense"
        return None
    return None


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
    rows = _cash_flow_rows(db, start, end)
    currencies = {r["currency"] for r in rows if r["currency"]}
    rates = get_rates(start, base_currency, currencies)

    income_total = 0.0
    expense_total = 0.0
    income_categories: dict[str, float] = {}
    expense_categories: dict[str, float] = {}
    for r in rows:
        cur = (r["currency"] or base_currency).upper()
        amount = float(r["amount"]) * rates.get(cur, 1.0)
        category = r["resolved_category"] or "Uncategorized"
        bucket = _cash_flow_bucket(r)
        if bucket == "income":
            income_total += amount
            income_categories[category] = income_categories.get(category, 0.0) + amount
        elif bucket == "expense":
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


@router.get("/cash-flow-detail", response_model=CashFlowDetailOut)
def cash_flow_detail(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
):
    start = _parse_month(month)
    end = _month_end(start)
    rows = _cash_flow_rows(db, start, end)
    currencies = {r["currency"] for r in rows if r["currency"]}
    rates = get_rates(start, base_currency, currencies)

    income_total = 0.0
    expense_total = 0.0
    income_transactions: list[CashFlowTransactionItem] = []
    expense_transactions: list[CashFlowTransactionItem] = []

    for row in rows:
        currency = (row["currency"] or base_currency).upper()
        base_amount = float(row["amount"]) * rates.get(currency, 1.0)
        item = CashFlowTransactionItem(
            transaction_id=int(row["transaction_id"]),
            ts=_tx_iso(row["ts"]),
            account_id=int(row["account_id"]),
            account_name=row["account_name"],
            account_type=row["account_type"],
            amount=float(row["amount"]),
            currency=currency,
            base_amount=base_amount,
            type=row["type"],
            raw_category=row["raw_category"],
            resolved_category=row["resolved_category"] or "Uncategorized",
            resolved_category_id=(
                int(row["resolved_category_id"])
                if row["resolved_category_id"] is not None
                else None
            ),
            category_source=row["category_source"] or "uncategorized",
            merchant_counterparty=row["merchant_counterparty"],
            notes=row["notes"],
        )
        bucket = _cash_flow_bucket(row)
        if bucket == "income":
            income_total += base_amount
            income_transactions.append(item)
        elif bucket == "expense":
            expense_total += -base_amount
            expense_transactions.append(item)

    net = income_total - expense_total
    savings_rate = (net / income_total) if income_total > 0 else None

    return CashFlowDetailOut(
        month=month,
        base_currency=base_currency,
        income_total=income_total,
        expense_total=expense_total,
        net=net,
        savings_rate=savings_rate,
        calculation=(
            "Net = income_total - expense_total using month-scoped transactions with types "
            "INCOME, EXPENSE, FEE, TAX, INTEREST, TRANSFER. Rows resolved under Transfer "
            "categories or explicit source transfer categories are excluded."
        ),
        income=CashFlowDetailSection(
            total=income_total,
            transaction_count=len(income_transactions),
            included_types=list(INCOME_TYPES),
            transactions=income_transactions,
        ),
        expenses=CashFlowDetailSection(
            total=expense_total,
            transaction_count=len(expense_transactions),
            included_types=list(EXPENSE_TYPES),
            transactions=expense_transactions,
        ),
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
