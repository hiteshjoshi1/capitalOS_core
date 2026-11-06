from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional

from app.schemas.fx import FxStatusFields


class NetWorth(BaseModel):
    total: float
    cash: float
    stocks_funds: float
    crypto: float
    liabilities: float


class AssetClassFreshness(BaseModel):
    most_recent_at: Optional[str] = None
    most_recent_label: Optional[str] = None
    stalest_at: Optional[str] = None
    stalest_label: Optional[str] = None


class NetWorthFreshness(BaseModel):
    stocks: AssetClassFreshness
    crypto: AssetClassFreshness
    cash: AssetClassFreshness


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
    name: Optional[str] = None
    asset_class: str
    value: float
    percent_of_networth: float
    quantity: Optional[float] = None
    avg_cost: Optional[float] = None
    latest_price: Optional[float] = None
    quote_currency: Optional[str] = None
    geo: Optional[str] = None
    platform: Optional[str] = None
    exchange_code: Optional[str] = None
    latest_trade_date: Optional[str] = None
    quote_age_days: Optional[int] = None
    price_source: Optional[str] = None
    # Set when a live view prices a holding at its statement price because the price
    # job had no usable quote: no_quote | quote_older | quote_implausible (D-21, #124;
    # every holding since #144, not only IBKR's).
    price_fallback_reason: Optional[str] = None
    # The holding's statement has no market value and no usable quote applied, so
    # it is valued at its cost basis (#144; it used to count as 0).
    valued_at_cost: bool = False
    price_provider: Optional[str] = None
    quote_freshness_status: Optional[str] = None
    # Where the shown price comes from (#224): "quote" (the price job) or "statement"
    # (the holding's statement or uploaded file). None for rows without a price.
    price_basis: Optional[str] = None


class CashBalance(BaseModel):
    currency: str
    value: float


class NetWorthChange(BaseModel):
    abs_: float = Field(alias="abs")
    pct: Optional[float] = None
    current_as_of: Optional[str] = None
    compare_as_of: Optional[str] = None
    compare_month: str
    # The baseline value itself (same currency as abs), and whether there is no data
    # for it at all (no snapshot at or before the comparison anchor and a zero value):
    # "no data for <month>" rather than a delta the size of the whole figure (#224).
    compare_value: Optional[float] = None
    baseline_missing: bool = False


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


class DashboardSummaryResponse(FxStatusFields):
    as_of_month: str
    base_currency: str
    snapshot_day: Optional[int] = None
    # #223: true for the open (or a future) month, whose geography, top_holdings
    # and cash_balances are live; false for a past month (its month-end snapshot).
    is_live: Optional[bool] = None
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
    # Live current_net_worth vs the latest completed month-end anchor (vs_prev_month)
    # and the anchor twelve months before it (vs_prev_year), #133.
    current_net_worth_change: Optional[Dict[str, NetWorthChange]] = None
    net_worth_component_change: Optional[Dict[str, NetWorthChange]] = None
    top_movers: Optional[TopMovers] = None
    cash_percent: float
    data_completeness_indicators: Optional[List[Dict[str, Any]]] = None

    class Config:
        populate_by_name = True


class RiskHolding(BaseModel):
    """A /summary top_holdings row cut to what the Risk page reads (#149); same values."""

    asset_id: Optional[int] = None
    symbol: str
    asset_class: str
    value: float
    percent_of_networth: float


class RiskSummaryResponse(FxStatusFields):
    """GET /dashboard/risk-summary (#149): what the Risk page reads from
    /dashboard/summary (net_worth, and per position its symbol, class and value),
    with the same values, and nothing else."""

    as_of_month: str
    base_currency: str
    snapshot_day: Optional[int] = None
    # As /summary: top_holdings are live for the open (or a future) month, the
    # month-end snapshot for a past month (#223). Same rows, same order.
    is_live: Optional[bool] = None
    net_worth: NetWorth
    top_holdings: List[RiskHolding]


class NetWorthSinceUpdateResponse(BaseModel):
    base_currency: str
    current_as_of: Optional[str] = None
    compare_as_of: Optional[str] = None
    net_worth_change: NetWorthChange
    component_change: Dict[str, NetWorthChange]
    top_movers: Optional[TopMovers] = None

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


class StockHoldingsResponse(FxStatusFields):
    as_of_month: str
    base_currency: str
    snapshot_day: Optional[int] = None
    is_live: bool = False
    compare_month: Optional[str] = None
    current_holdings_as_of: Optional[str] = None
    net_worth_as_of: Optional[str] = None
    net_worth_snapshot_as_of: Optional[str] = None
    net_worth_boundary_at: Optional[str] = None
    net_worth_boundary_exact: Optional[bool] = None
    net_worth_freshness_status: Optional[str] = None
    top_holdings: List[TopHolding]
    geography_breakdown: list["StockGeographyBreakdownItem"] = []
    geography_performance: list["StockGeographyBreakdownItem"] = []
    geography_performance_as_of: Optional[str] = None
    platform_breakdown: list[StockBreakdownItem] = []
    stock_current_total: float = 0.0
    stock_snapshot_total: float = 0.0
    # The date of the holdings stock_snapshot_total is taken from (#232).
    stock_snapshot_as_of: Optional[str] = None
    quote_freshness_summary: Optional["QuoteFreshnessSummary"] = None
    trend: list["MiniTrendPoint"] = []
    # No stock data at all for the compare month (not a real zero), #224.
    stock_snapshot_missing: bool = False
    # QUOTE_STALE_DAYS: a price older than this many days is stale (#224).
    quote_stale_days: Optional[int] = None


class PlatformAllocationItem(BaseModel):
    platform: str
    platform_type: str | None = None
    country: str | None = None
    value: float
    percent: float


class PlatformAllocationOut(BaseModel):
    as_of: str | None = None
    # #223: the requested month, and whether it is the open month (live, quote
    # priced) or a past month (its month-end snapshot).
    as_of_month: str | None = None
    is_live: bool | None = None
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
    is_live: bool = False
    # The anchor the figures are taken at (a past month's month-end boundary,
    # or "now"), as on the Stocks page (#232).
    net_worth_boundary_at: Optional[str] = None
    compare_month: Optional[str] = None
    current_cash_as_of: Optional[str] = None
    snapshot_cash_as_of: Optional[str] = None
    current_total: Optional[float] = None
    snapshot_total: Optional[float] = None
    # The stablecoins (USDC/USDT) in current_total / snapshot_total: the Cash
    # page counts them as cash, net worth as crypto (D-42, #232).
    current_stablecoin_total: Optional[float] = None
    snapshot_stablecoin_total: Optional[float] = None
    delta_abs: Optional[float] = None
    delta_pct: Optional[float] = None
    trend: list["MiniTrendPoint"] = []
    currency_breakdown: list["CashCurrencyBreakdownItem"] = []
    # No cash data at all for the compare month (not a real zero), #224.
    snapshot_missing: bool = False


class StockExposureItem(BaseModel):
    key: str
    value: float
    percent: float


class StockExposureOut(BaseModel):
    as_of: str | None = None
    is_live: bool | None = None
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
    # Live view only (None on a past month): holdings without a fresh quote from the
    # price job, including those priced only from a statement or upload (#224).
    no_live_price: Optional[int] = None


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


class DataHubActivityItem(BaseModel):
    kind: str
    title: str
    meta: str
    occurred_at: str


class DataHubImportHealth(BaseModel):
    pending_count: int
    last_import_platform: Optional[str] = None
    last_import_at: Optional[str] = None


class DataHubUnpricedHolding(BaseModel):
    """A held stock or fund the quote refresh can't price (#222). `reason`:
    no_asset (not linked to an asset), no_symbol (no ticker on a configured
    exchange) or no_quote (no provider has returned a price)."""

    symbol: Optional[str] = None
    name: Optional[str] = None
    currency: Optional[str] = None
    exchange_code: Optional[str] = None
    platform: Optional[str] = None
    reason: str


class DataHubMarketData(BaseModel):
    fresh: int
    stale: int
    unpriced: int = 0
    unpriced_holdings: List[DataHubUnpricedHolding] = []


class DataHubJobScopeStatus(BaseModel):
    scope: str
    label: Optional[str] = None
    last_run_at: Optional[str] = None
    last_run_status: Optional[str] = None
    last_run_trigger: Optional[str] = None
    last_success_at: Optional[str] = None
    data_as_of: Optional[str] = None
    consecutive_failures: int = 0
    last_error: Optional[str] = None


class DataHubJobStatus(BaseModel):
    """One data source's job status from job_runs (#156). `state`: ok, warning
    (a failure below the threshold, or no new data), failing (at least
    `failure_threshold` consecutive failures of one scope), never_run, or
    not_configured (nothing to run for this user)."""

    job: str
    label: str
    state: str
    failure_threshold: int
    last_run_at: Optional[str] = None
    last_run_status: Optional[str] = None
    last_success_at: Optional[str] = None
    data_as_of: Optional[str] = None
    consecutive_failures: int = 0
    last_error: Optional[str] = None
    scopes: List[DataHubJobScopeStatus] = []


class DataHubSummaryResponse(BaseModel):
    linked_accounts: int
    platform_count: int
    currency_count: int
    import_health: DataHubImportHealth
    market_data: DataHubMarketData
    connected_wallet_count: int
    connected_wallet_labels: List[str]
    recent_activity: List[DataHubActivityItem]
    job_status: List[DataHubJobStatus] = []


class BootstrapResponse(FxStatusFields):
    as_of_month: str
    base_currency: str
    snapshot_day: Optional[int] = None
    # #223: true for the open (or a future) month (the page headline is
    # current_net_worth); false for a past month (net_worth, its month-end).
    is_live: Optional[bool] = None
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


class WealthTimelineSourceFreshness(BaseModel):
    platform: str
    as_of: Optional[str] = None
    days_old: Optional[int] = None
    status: str


class WealthTimelinePoint(BaseModel):
    month: str
    anchor_date: str
    total: float
    cash: float
    stocks_funds: float
    crypto: float
    liabilities: float
    source_freshness: List[WealthTimelineSourceFreshness]
    freshness_status: str
    computed_at: Optional[str] = None
    uploads: List[str] = Field(default_factory=list)


class WealthTimelineNow(BaseModel):
    total: float
    cash: float
    stocks_funds: float
    crypto: float
    liabilities: float
    as_of: Optional[str] = None
    # Platforms with a statement import this (still open) month (#138).
    uploads: List[str] = Field(default_factory=list)


class WealthTimelineResponse(BaseModel):
    base_currency: str
    points: List[WealthTimelinePoint]
    now: WealthTimelineNow


class WealthTimelineBackfillResponse(BaseModel):
    months_written: int
    base_currency: str


# ─── This month's bridge (#240, D-60) ────────────────────────────────────────


class BridgePart(BaseModel):
    """One part of a bridge line; a line's parts add up to its amount."""

    key: str
    label: str
    amount: float


class BridgeNote(BaseModel):
    """Context for a line that is not part of its amount (e.g. transfers between
    your own accounts, sources with no data in the period)."""

    key: str
    label: str
    amount: Optional[float] = None


class BridgeLine(BaseModel):
    """One cause of the change. ``status`` is ok | partial | unavailable; when it
    isn't ok, ``reason`` says why and what couldn't be computed is in ``unexplained``."""

    key: str
    label: str
    amount: float
    status: str = "ok"
    reason: Optional[str] = None
    parts: List[BridgePart] = Field(default_factory=list)
    notes: List[BridgeNote] = Field(default_factory=list)


class BridgeEndpoint(BaseModel):
    """The bridge's start (the month-end close Overview compares with) or end
    (Overview's headline: live now, or that month's month-end)."""

    month: str
    # The anchor the value is taken at: a month-end anchor (00:00Z of its date) or
    # the live instant; ``as_of`` is the newest data at or before it.
    boundary_at: str
    as_of: Optional[str] = None
    value: float
    net_worth: NetWorth
    # No data at all at or before the start's anchor (#224).
    baseline_missing: bool = False


class BridgeMover(BaseModel):
    asset_id: Optional[int] = None
    symbol: str
    name: Optional[str] = None
    asset_class: str
    start_value: float
    end_value: float
    change: float
    price_effect: float
    quantity_effect: float
    fx_effect: float
    # What the market did to the holding: price_effect + fx_effect. Movers are ranked
    # by it; a change in quantity (buying, selling) is listed under ``trades``.
    market_effect: float = 0.0
    # The larger of the price and FX effects: price | fx; unknown when the part that
    # can't be split (no price or quantity on one side) is larger than the market effect.
    cause: str


class BridgeTrade(BaseModel):
    """A holding bought, sold or (crypto) moved in or out this month: its quantity
    effect. Not a gain or loss: where the account's cash is recorded the money moved
    to or from that cash."""

    asset_id: Optional[int] = None
    symbol: str
    name: Optional[str] = None
    asset_class: str
    amount: float
    side: str  # bought | sold | moved_in | moved_out
    cash_recorded: bool = False


class MonthBridgeResponse(FxStatusFields):
    """GET /dashboard/month-bridge (#240): start + sum(lines) + unexplained = end."""

    as_of_month: str
    base_currency: str
    snapshot_day: int
    is_live: bool
    # Flows count from this date (the start's anchor date) up to period_end (the
    # end's boundary: a month-end anchor, or now).
    period_start: str
    period_end: str
    start: BridgeEndpoint
    end: BridgeEndpoint
    change: float
    lines: List[BridgeLine]
    unexplained: BridgeLine
    # What the cards owe at the end minus at the start (context: card spending is
    # in "cash kept", so this is not a line of its own).
    liabilities_change: float
    movers: List[BridgeMover]
    trades: List[BridgeTrade] = []
