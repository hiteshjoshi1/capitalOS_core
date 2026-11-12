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
