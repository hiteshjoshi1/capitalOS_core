from __future__ import annotations

from pydantic import BaseModel

from app.schemas.fx import FxStatusFields


class DividendTotalsOut(BaseModel):
    gross: float
    withholding: float
    net_received: float
    estimated_tax: float
    payout_minus_tax: float


class DividendSummaryBucketOut(DividendTotalsOut):
    bucket: str


class DividendSummaryOut(FxStatusFields):
    from_month: str
    to_month: str
    period: str
    base_currency: str
    assumed_tax_rate: float
    country_tax_rates: dict[str, float]
    buckets: list[DividendSummaryBucketOut]
    totals: DividendTotalsOut


class DividendCompanyItemOut(DividendTotalsOut):
    asset_id: int | None
    symbol: str
    company: str
    country: str | None
    yield_pct: float | None


class DividendsByCompanyOut(FxStatusFields):
    from_month: str
    to_month: str
    base_currency: str
    assumed_tax_rate: float
    country_tax_rates: dict[str, float]
    items: list[DividendCompanyItemOut]
    totals: DividendTotalsOut


class DividendHistoryEventOut(DividendTotalsOut):
    month: str


class DividendHistoryOut(FxStatusFields):
    from_month: str
    to_month: str
    base_currency: str
    assumed_tax_rate: float
    country_tax_rates: dict[str, float]
    asset_id: int | None
    symbol: str | None
    company: str | None
    yield_pct: float | None
    events: list[DividendHistoryEventOut]
    totals: DividendTotalsOut


class ExpectedDividendBucketOut(BaseModel):
    bucket: str
    gross: float
    estimated_tax: float
    payout_minus_tax: float


class ExpectedDividendSummaryOut(BaseModel):
    period: str
    buckets: list[ExpectedDividendBucketOut]
    gross: float
    estimated_tax: float
    payout_minus_tax: float


class ExpectedDividendCompanyOut(BaseModel):
    asset_id: int
    symbol: str
    company: str
    country: str | None
    shares: float
    yield_pct: float | None
    price: float | None
    quote_currency: str | None
    yearly_dividend: float
    quarterly_dividend: float
    monthly_dividend: float
    gross: float
    estimated_tax: float
    payout_minus_tax: float
    # #409 (U16, D-113): "yield" (a stored dividend yield x price x shares) or "past_payments"
    # (no yield stored: the dividends it actually paid in the twelve months to the period's end).
    method: str = "yield"


class ExpectedDividendsOverviewOut(BaseModel):
    from_month: str
    to_month: str
    base_currency: str
    assumed_tax_rate: float
    country_tax_rates: dict[str, float]
    holdings_considered: int
    assets_with_actions: int
    actions_evaluated: int
    monthly: ExpectedDividendSummaryOut
    quarterly: ExpectedDividendSummaryOut
    yearly: ExpectedDividendSummaryOut
    companies: list[ExpectedDividendCompanyOut]
    # #409 (U16): how many held companies each method projected, so the page can say which it
    # used ("based on stored yields" / "based on the last 12 months' payments" / both).
    companies_by_yield: int = 0
    companies_by_past_payments: int = 0


class DividendCalendarEventOut(BaseModel):
    """#417 (U17, D-117): one expected dividend in the calendar window."""

    asset_id: int
    symbol: str
    company: str
    # When it's expected to land: the pay date when known, else the ex-date, else (your
    # payments) the date it was paid a year earlier, plus a year.
    date: str
    ex_date: str | None
    pay_date: str | None
    shares: float
    amount_per_share: float | None
    currency: str
    # Expected gross amount: shares held now x amount per share, in `currency` and the base.
    amount: float
    amount_base: float | None
    # "announced": the provider lists this ex-date (the amount is still estimated).
    # "projected": from the holding's own past dividends (its usual gap and amount).
    # "your_payments": the user's own dividend from this holding a year earlier.
    basis: str
    estimated: bool = True


class DividendCalendarMonthOut(BaseModel):
    month: str
    amount_base: float
    count: int


class DividendCalendarOut(BaseModel):
    base_currency: str
    from_date: str
    to_date: str
    events: list[DividendCalendarEventOut]
    months: list[DividendCalendarMonthOut]
    total_base: float
    holdings_considered: int
    holdings_with_events: int
    # Held but nothing expected in the window (they pay at other times of year, or not at all).
    holdings_without_data: int
    # Of those: no dividend history at all (no provider dividends, no payment of yours a year back).
    holdings_no_dividend_history: int = 0
    # Newest provider fetch behind the events (ISO), or None when nothing was ever fetched.
    data_as_of: str | None = None
