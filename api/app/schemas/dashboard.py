from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional


class NetWorth(BaseModel):
    total: float
    cash: float
    stocks_funds: float
    crypto: float
    liabilities: float


class NetWorthFreshness(BaseModel):
    positions_as_of: Optional[str] = None
    market_data_as_of: Optional[str] = None
    crypto_as_of: Optional[str] = None
    crypto_holdings_as_of: Optional[str] = None
    crypto_price_as_of: Optional[str] = None


class GeographyItem(BaseModel):
    country: str
    value: float
    percent: float


class CashFlow(BaseModel):
    income: float
    expenses: float
    net: float
    savings_rate: Optional[float] = None


class TopHolding(BaseModel):
    asset_id: Optional[int] = None
    symbol: str
    asset_class: str
    value: float
    percent_of_networth: float
    quantity: Optional[float] = None
    avg_cost: Optional[float] = None
    latest_price: Optional[float] = None
    quote_currency: Optional[str] = None
    geo: Optional[str] = None
    platform: Optional[str] = None
    latest_trade_date: Optional[str] = None
    quote_age_days: Optional[int] = None
    price_source: Optional[str] = None
    price_provider: Optional[str] = None
    quote_freshness_status: Optional[str] = None


class CashBalance(BaseModel):
    currency: str
    value: float


class NetWorthChange(BaseModel):
    abs_: float = Field(alias="abs")
    pct: Optional[float] = None
    current_as_of: Optional[str] = None
    compare_as_of: Optional[str] = None
    compare_month: str


class TopMover(BaseModel):
    asset_id: Optional[int] = None
    symbol: str
    asset_class: str
    current_value: float
    previous_value: float
    delta_abs: float
    delta_pct: Optional[float] = None
    compare_month: str


class TopMovers(BaseModel):
    compare_month: str
    gainers: List[TopMover]
    detractors: List[TopMover]


class DashboardSummaryResponse(BaseModel):
    as_of_month: str
    base_currency: str
    snapshot_day: Optional[int] = None
    current_net_worth_as_of: Optional[str] = None
    current_net_worth: Optional[NetWorth] = None
    current_net_worth_freshness: Optional[NetWorthFreshness] = None
    net_worth_as_of: Optional[str] = None
    net_worth_snapshot_as_of: Optional[str] = None
    net_worth_boundary_at: Optional[str] = None
    net_worth_boundary_exact: Optional[bool] = None
    net_worth_freshness_status: Optional[str] = None
    net_worth: Optional[NetWorth] = None
    geography: List[GeographyItem]
    cash_flow: CashFlow
    top_holdings: List[TopHolding]
    cash_balances: List[CashBalance]
    net_worth_change: Optional[Dict[str, NetWorthChange]] = None
    net_worth_component_change: Optional[Dict[str, NetWorthChange]] = None
    top_movers: Optional[TopMovers] = None
    cash_percent: float
    data_completeness_indicators: Optional[List[Dict[str, Any]]] = None

    class Config:
        populate_by_name = True


class NetWorthChangeResponse(BaseModel):
    as_of_month: str
    base_currency: str
    net_worth_as_of: Optional[str] = None
    net_worth_snapshot_as_of: Optional[str] = None
    net_worth_boundary_at: Optional[str] = None
    net_worth_boundary_exact: Optional[bool] = None
    net_worth_freshness_status: Optional[str] = None
    net_worth_change: Optional[Dict[str, NetWorthChange]] = None

    class Config:
        populate_by_name = True


class StockBreakdownItem(BaseModel):
    key: str
    current_value: float
    snapshot_value: float
    delta_abs: float
    delta_pct: Optional[float] = None
    percent: float


class StockHoldingsResponse(BaseModel):
    as_of_month: str
    base_currency: str
    snapshot_day: Optional[int] = None
    current_holdings_as_of: Optional[str] = None
    net_worth_as_of: Optional[str] = None
    net_worth_snapshot_as_of: Optional[str] = None
    net_worth_boundary_at: Optional[str] = None
    net_worth_boundary_exact: Optional[bool] = None
    net_worth_freshness_status: Optional[str] = None
    top_holdings: List[TopHolding]
    geography_breakdown: list["StockGeographyBreakdownItem"] = []
    platform_breakdown: list[StockBreakdownItem] = []
    stock_current_total: float = 0.0
    stock_snapshot_total: float = 0.0
    quote_freshness_summary: Optional["QuoteFreshnessSummary"] = None
    trend: list["MiniTrendPoint"] = []


class PlatformAllocationItem(BaseModel):
    platform: str
    platform_type: str | None = None
    country: str | None = None
    value: float
    percent: float


class PlatformAllocationOut(BaseModel):
    as_of: str | None = None
    total: float
    items: list[PlatformAllocationItem]


class CashDepositsItem(BaseModel):
    source: str
    value: float
    percent: float


class CashDepositsOut(BaseModel):
    total: float
    items: list[CashDepositsItem]
    as_of_month: Optional[str] = None
    base_currency: Optional[str] = None
    snapshot_day: Optional[int] = None
    current_cash_as_of: Optional[str] = None
    snapshot_cash_as_of: Optional[str] = None
    current_total: Optional[float] = None
    snapshot_total: Optional[float] = None
    delta_abs: Optional[float] = None
    delta_pct: Optional[float] = None
    trend: list["MiniTrendPoint"] = []
    currency_breakdown: list["CashCurrencyBreakdownItem"] = []


class StockExposureItem(BaseModel):
    key: str
    value: float
    percent: float


class StockExposureOut(BaseModel):
    as_of: str | None = None
    base_currency: str
    total: float
    by_country: list[StockExposureItem]
    by_platform: list[StockExposureItem]


class GeographyExposureItem(BaseModel):
    country: str
    stocks_funds: float
    cash: float
    crypto: float
    total: float
    percent: float


class GeographyExposureOut(BaseModel):
    as_of: str | None = None
    base_currency: str
    total: float
    items: list[GeographyExposureItem]


class QuoteFreshnessSummary(BaseModel):
    fresh: int
    stale: int
    missing: int


class StockGeographyBreakdownItem(BaseModel):
    geography: str
    current_value: float
    snapshot_value: float
    delta_abs: float
    delta_pct: Optional[float] = None


class MiniTrendPoint(BaseModel):
    month: str
    value: Optional[float] = None


class CashCurrencyBreakdownItem(BaseModel):
    currency: str
    current_value: float
    snapshot_value: float
    delta_abs: float
    delta_pct: Optional[float] = None


class BootstrapResponse(BaseModel):
    as_of_month: str
    base_currency: str
    snapshot_day: Optional[int] = None
    current_net_worth_as_of: Optional[str] = None
    current_net_worth: Optional[NetWorth] = None
    current_net_worth_freshness: Optional[NetWorthFreshness] = None
    net_worth_as_of: Optional[str] = None
    net_worth_snapshot_as_of: Optional[str] = None
    net_worth_boundary_at: Optional[str] = None
    net_worth_boundary_exact: Optional[bool] = None
    net_worth_freshness_status: Optional[str] = None
    net_worth: NetWorth
    current_stock_exposure_total: Optional[float] = None
    current_crypto_exposure_total: Optional[float] = None
    current_cash_percent: Optional[float] = None
    stock_exposure_total: float
    crypto_exposure_total: float
    cash_percent: float
