from datetime import date

from pydantic import BaseModel

from app.schemas.fx import FxStatusFields


class CategoryAmount(BaseModel):
    category: str
    amount: float


class SpendingSummaryOut(FxStatusFields):
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
    # Why the bridge can't be drawn; None when it can (#265: exact snapshots no longer needed).
    availability_message: str | None = None
    ending_cash: float | None
    # #265 (D-72): the bridge runs between the nearest cash snapshots at or before the month's
    # start and end anchors (the open month: the newest so far). ``span_basis``: "exact" when
    # both are on the anchors, "nearest" otherwise, None when not available.
    bridge_available: bool = False
    span_start: str | None = None
    span_end: str | None = None
    span_basis: str | None = None


class CashFlowDiagnosticAnswer(BaseModel):
    question: str
    answer: str


class CashFlowComparisonOut(BaseModel):
    """The month vs the month before, like for like (#243, D-63).

    The open month is month to date: its days 1..``through_day`` (today, in the
    user's timezone) against the previous month's days 1..``prior_through_day``
    (the same day, clamped to that month's length). A past (or future) month is
    the whole month against the whole previous month, the same figures as the
    analytics' ``prior_month_net`` / ``free_cash_flow_change_vs_prior_month``.
    """

    basis: str  # "month_to_date" | "full_month"
    month: str
    month_days: int
    through_day: int
    prior_month: str
    prior_month_days: int
    prior_through_day: int
    prior_start: str  # ISO date, first day counted
    prior_end: str  # ISO date, last day counted (inclusive)
    inflows: float
    outflows: float
    net: float
    savings_rate: float | None
    prior_inflows: float
    prior_outflows: float
    prior_net: float
    prior_savings_rate: float | None
    inflows_change: float
    outflows_change: float
    net_change: float
    outflow_category_deltas: list[CashFlowCategoryDeltaItem]
    deterioration_drivers: list[CashFlowCategoryDeltaItem]


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
    comparison: CashFlowComparisonOut | None = None


class CashFlowDetailOut(FxStatusFields):
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


class CashFlowTrendOut(FxStatusFields):
    """GET /spending/cash-flow-trend (#149): only the six-month trend of
    /spending/cash-flow-detail (its ``analytics.trend``), for History."""

    month: str
    base_currency: str
    trend: list[CashFlowTrendPoint]


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


class CreditCardSummaryOut(FxStatusFields):
    month: str
    base_currency: str
    total_spend: float
    cards: list[CreditCardItem]


class CreditCardBalancePeriod(BaseModel):
    """The card between two dated balances (#300); amounts in the card's currency.
    ``to_date`` None: the newest balance, carried to today. ``printed`` is the next
    balance the bank stated; ``difference`` = printed - expected, flagged above S$ 1."""
    from_date: str
    to_date: str | None = None
    opening: float
    charges: float
    fees: float
    interest: float
    payments: float
    credits: float
    transaction_count: int
    expected: float
    printed: float | None = None
    difference: float | None = None
    flagged: bool = False
    paid_in_full: bool | None = None
    # #308: payments found only on the paying bank account (included in ``payments``), and why
    # a difference is left when the ledger can tell (e.g. no card transactions after a date).
    bank_payments: float = 0.0
    note: str | None = None


class CreditCardBalanceItem(BaseModel):
    """One card's running balance and statement check (#300, D-76)."""
    account_id: int
    account_name: str
    card_name: str
    issuer: str
    currency: str
    # running (a dated balance carried by the card's transactions) | transactions
    # (no dated balance yet: this month's net transactions, an estimate).
    method: str
    owed_now: float  # card currency; negative = a credit (overpaid)
    owed_now_base: float
    last_balance_date: str | None = None
    last_balance: float | None = None
    last_balance_source: str | None = None
    paid_since: float = 0.0
    charges_since: float = 0.0
    paid_in_full: bool | None = None
    due_date: str | None = None
    fees_interest_ytd: float = 0.0
    last_transaction_date: str | None = None
    flagged_count: int = 0
    periods: list[CreditCardBalancePeriod] = []  # newest first


class CreditCardBalanceIn(BaseModel):
    """A card balance typed in from a statement (#300): what was owed on that date
    (negative: a credit). For a card whose files state none (Citi)."""
    as_of_date: date
    owed: float


class CreditCardBalancesOut(FxStatusFields):
    base_currency: str
    as_of: str
    total_owed_base: float
    flagged_count: int
    cards: list[CreditCardBalanceItem]


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
    # #266: how it repeats ("monthly"), and its usual amount (median charge, base currency).
    cadence: str = "monthly"
    typical_amount: float | None = None


class CreditCardDetailOut(FxStatusFields):
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


class CreditCardAnalyticsOut(FxStatusFields):
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
