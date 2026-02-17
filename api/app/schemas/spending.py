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
