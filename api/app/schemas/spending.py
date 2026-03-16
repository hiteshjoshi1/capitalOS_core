from pydantic import BaseModel


class CategoryAmount(BaseModel):
    category: str
    amount: float


class SpendingSummaryOut(BaseModel):
    month: str
    base_currency: str
    income_total: float
    expense_total: float
    net: float
    savings_rate: float | None
    income_categories: list[CategoryAmount]
    expense_categories: list[CategoryAmount]


class CashFlowTransactionItem(BaseModel):
    transaction_id: int
    ts: str
    account_id: int
    account_name: str
    account_type: str
    amount: float
    currency: str
    base_amount: float
    type: str
    raw_category: str | None
    resolved_category: str
    resolved_category_id: int | None = None
    category_source: str
    merchant_counterparty: str | None
    notes: str | None


class CashFlowDetailSection(BaseModel):
    total: float
    transaction_count: int
    included_types: list[str]
    transactions: list[CashFlowTransactionItem]


class CashFlowDetailOut(BaseModel):
    month: str
    base_currency: str
    income_total: float
    expense_total: float
    net: float
    savings_rate: float | None
    calculation: str
    income: CashFlowDetailSection
    expenses: CashFlowDetailSection


class CreditCardItem(BaseModel):
    account_id: int
    account_name: str
    card_name: str
    issuer: str
    credit_limit: float
    statement_day: int
    due_day: int
    due_date: str
    current_due: float
    utilization: float | None


class CreditCardSummaryOut(BaseModel):
    month: str
    base_currency: str
    total_spend: float
    cards: list[CreditCardItem]


class CreditCardTransactionItem(BaseModel):
    account_id: int
    account_name: str
    card_name: str
    issuer: str
    ts: str
    description: str
    amount: float
    type: str
    category: str | None
    resolved_category: str | None = None
    category_source: str | None = None
    merchant_counterparty: str | None
    notes: str | None


class CreditCardRecurringPaymentItem(BaseModel):
    account_id: int
    account_name: str
    card_name: str
    issuer: str
    merchant_counterparty: str
    months_present: int
    current_month_amount: float


class CreditCardDetailOut(BaseModel):
    month: str
    base_currency: str
    total_spend: float
    cards: list[CreditCardItem]
    transactions: list[CreditCardTransactionItem]
    top_purchases: list[CreditCardTransactionItem]
    recurring_payments: list[CreditCardRecurringPaymentItem]
