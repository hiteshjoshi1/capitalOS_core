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


class CashFlowBreakdownItem(BaseModel):
    label: str
    amount: float
    percent: float


class CashFlowMerchantItem(BaseModel):
    merchant: str
    amount: float
    percent: float
    transaction_count: int


class CashFlowCategoryDeltaItem(BaseModel):
    label: str
    current_amount: float
    prior_amount: float
    delta_amount: float
    delta_percent: float | None
    direction: str


class CashFlowTrendPoint(BaseModel):
    month: str
    inflows: float
    outflows: float
    net: float
    savings_rate: float | None
    burn_rate: float | None


class CashFlowWaterfallOut(BaseModel):
    starting_cash: float | None
    snapshot_start_as_of: str | None = None
    snapshot_start_boundary_at: str | None = None
    inflows: float
    outflows: float
    transfers_and_funding: float | None = None
    investment_and_fx_effects: float | None = None
    other_cash_movements: float | None = None
    snapshot_end_as_of: str | None = None
    snapshot_end_boundary_at: str | None = None
    boundary_exact: bool = False
    availability_message: str | None = None
    ending_cash: float | None


class CashFlowDiagnosticAnswer(BaseModel):
    question: str
    answer: str


class CashFlowAnalyticsOut(BaseModel):
    burn_rate: float | None
    prior_month: str | None
    prior_month_net: float | None
    free_cash_flow_change_vs_prior_month: float | None
    outflow_categories: list[CashFlowBreakdownItem]
    inflow_categories: list[CashFlowBreakdownItem]
    outflow_recurring_split: list[CashFlowBreakdownItem]
    inflow_recurring_split: list[CashFlowBreakdownItem]
    outflow_fixed_variable_split: list[CashFlowBreakdownItem]
    inflow_source_mix: list[CashFlowBreakdownItem]
    top_outflow_merchants: list[CashFlowMerchantItem]
    largest_inflow_drivers: list[CashFlowBreakdownItem]
    outflow_category_deltas: list[CashFlowCategoryDeltaItem]
    deterioration_drivers: list[CashFlowCategoryDeltaItem]
    trend: list[CashFlowTrendPoint]
    waterfall: CashFlowWaterfallOut
    answers: list[CashFlowDiagnosticAnswer]


class CashFlowDetailOut(BaseModel):
    month: str
    base_currency: str
    income_total: float
    expense_total: float
    net: float
    savings_rate: float | None
    calculation: str
    analytics: CashFlowAnalyticsOut
    income: CashFlowDetailSection
    expenses: CashFlowDetailSection


class CreditCardItem(BaseModel):
    account_id: int
    account_name: str
    card_name: str
    issuer: str
    credit_limit: float
    available_limit: float | None = None
    available_limit_as_of: str | None = None
    current_due_source: str = "transactions"
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


class CreditCardAnalyticsCardItem(BaseModel):
    account_id: int
    account_name: str
    card_name: str
    issuer: str
    spend: float
    transaction_count: int
    available_limit: float | None = None
    available_limit_as_of: str | None = None
    statement_day: int
    due_day: int
    due_date: str


class CreditCardAnalyticsTrendPoint(BaseModel):
    month: str
    spend: float


class CreditCardAnalyticsOut(BaseModel):
    month: str
    base_currency: str
    months: int
    account_id: int | None = None
    total_spend: float
    transaction_count: int
    purchase_spend: float
    prior_month: str
    prior_month_spend: float
    cards: list[CreditCardAnalyticsCardItem]
    charges: list[CreditCardTransactionItem]
    charge_total: float
    categories: list[CashFlowBreakdownItem]
    trend: list[CreditCardAnalyticsTrendPoint]
    transactions: list[CreditCardTransactionItem]
    recurring_payments: list[CreditCardRecurringPaymentItem]
