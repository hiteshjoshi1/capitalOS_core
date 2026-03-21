from pydantic import BaseModel
from typing import Dict, Any, List, Optional


class NetWorth(BaseModel):
    total: float
    cash: float
    stocks_funds: float
    crypto: float
    liabilities: float


class GeographyItem(BaseModel):
    country: str
    value: float
    percent: float


class CashFlowItem(BaseModel):
    source: str
    income: float
    expense: float
    net: float


class CashFlow(BaseModel):
    income_total: float
    expense_total: float
    net_total: float
    by_source: List[CashFlowItem]


class TopHolding(BaseModel):
    symbol: str
    asset_class: str
    value: float
    percent: float
    quantity: Optional[float] = None
    avg_cost: Optional[float] = None
    latest_price: Optional[float] = None
    quote_currency: Optional[str] = None
    home: Optional[str] = None


class CashBalance(BaseModel):
    source: str
    value: float
    percent: float


class NetWorthChange(BaseModel):
    abs: float
    pct: Optional[float] = None
    current_as_of: Optional[str] = None
    compare_as_of: Optional[str] = None
    compare_month: str


class DashboardSummaryResponse(BaseModel):
    as_of_month: str
    base_currency: str
    snapshot_day: Optional[int] = None
    net_worth_as_of: Optional[str] = None
    net_worth: NetWorth
    geography: List[GeographyItem]
    cash_flow: CashFlow
    top_holdings: List[TopHolding]
    cash_balances: List[CashBalance]
    net_worth_change: Optional[Dict[str, NetWorthChange]] = None
    cash_percent: float


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
