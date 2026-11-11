// Wealth pages: dashboard, history, risk, bridge, stocks: response and request types (split out of lib/api.ts, #368).
import type { FxStatus } from "./common";

/** One comparison of a value with a baseline (net worth or a component). */
export type NetWorthChange = {
  abs: number;
  pct: number | null;
  current_as_of: string | null;
  compare_as_of: string | null;
  compare_month: string;
  /** The baseline value, in the same currency as `abs` (#224). */
  compare_value?: number | null;
  /** No data at all for the baseline (not a real zero): show "no data for <month>" (#224). */
  baseline_missing?: boolean;
};

export type DashboardSummary = FxStatus & {
  as_of_month: string;
  base_currency: string;
  /** #223: true for the open (or a future) month, whose geography/top_holdings/cash_balances
   * are live; false for a past month (its month-end snapshot). */
  is_live?: boolean | null;
  current_net_worth_as_of?: string | null;
  current_net_worth?: NetWorthBreakdown | null;
  current_net_worth_freshness?: NetWorthFreshness | null;
  net_worth_snapshot_as_of?: string | null;
  net_worth_boundary_at?: string | null;
  net_worth_boundary_exact?: boolean | null;
  net_worth_freshness_status?: string | null;

  net_worth: {
    total: number;
    cash: number;
    stocks_funds: number;
    crypto: number;
    liabilities: number;
  };

  geography: Array<{
    country: string;
    value: number;
    percent: number;
  }>;

  cash_flow: {
    income: number;
    expenses: number;
    net: number;
    savings_rate: number | null;
  };

  top_holdings: Array<{
    asset_id: number | null;
    symbol: string;
    name?: string | null;
    asset_class: string;
    value: number;
    percent_of_networth: number;
    quantity?: number;
    avg_cost?: number | null;
    latest_price?: number | null;
    quote_currency?: string;
    geo?: string;
    platform?: string;
    exchange_code?: string | null;
    latest_trade_date?: string | null;
    quote_age_days?: number | null;
    price_source?: string | null;
    /** Live views: why a holding is priced at its statement price (D-21, #124; every holding since #144). */
    price_fallback_reason?: string | null;
    /** No market value on the statement and no usable quote: valued at cost (#144). */
    valued_at_cost?: boolean;
    price_provider?: string | null;
    quote_freshness_status?: string | null;
    /** Where the shown price comes from: the price job's quote or the statement/upload (#224). */
    price_basis?: "quote" | "statement" | null;
  }>;
  cash_balances?: Array<{
    currency: string;
    value: number;
  }>;
  snapshot_day: number | null;
  net_worth_as_of: string | null;
  net_worth_change: null | {
    vs_prev_month?: NetWorthChange;
    vs_prev_year?: NetWorthChange;
  };
  /** Live current_net_worth vs the latest completed month-end (vs_prev_month) and the
   * same month-end a year earlier (vs_prev_year), whatever month was requested (#133). */
  current_net_worth_change?: DashboardSummary["net_worth_change"];
  net_worth_component_change?: null | {
    cash?: NetWorthChange;
    stocks_funds?: NetWorthChange;
    crypto?: NetWorthChange;
  };
  top_movers?: null | {
    compare_month: string;
    gainers: Array<{
      asset_id: number | null;
      symbol: string;
      asset_class: string;
      current_value: number;
      previous_value: number;
      delta_abs: number;
      delta_pct: number | null;
      compare_month: string;
    }>;
    detractors: Array<{
      asset_id: number | null;
      symbol: string;
      asset_class: string;
      current_value: number;
      previous_value: number;
      delta_abs: number;
      delta_pct: number | null;
      compare_month: string;
    }>;
  };
  cash_percent: number;
};

/** A `DashboardSummary.top_holdings` row cut to what the Risk page reads (#149). */
export type RiskHolding = Pick<
  DashboardSummary["top_holdings"][number],
  "asset_id" | "symbol" | "asset_class" | "value" | "percent_of_networth"
>;

/** GET /dashboard/risk-summary (#149): what the Risk page reads from /dashboard/summary,
 * with the same values (same rows, same order). */
export type RiskSummary = FxStatus &
  Pick<DashboardSummary, "as_of_month" | "base_currency" | "is_live" | "net_worth"> & {
    snapshot_day?: number | null;
    top_holdings: RiskHolding[];
    /** #241: one point in time per month. "live" for the open (or a future) month,
     * "month_end" for a past month. */
    basis?: "live" | "month_end" | null;
    /** The net worth Risk's shares divide by, at the positions' point in time: live, the
     * Overview headline (`current_net_worth`); a past month, its month-end `net_worth`. */
    view_net_worth?: DashboardSummary["net_worth"] | null;
    /** The anchor the figures are taken at: the live instant, or the month-end boundary. */
    net_worth_boundary_at?: string | null;
    /** #253, at the same point in time: net worth by currency (its total is
     * `view_net_worth.total`; USD stablecoins count as USD). */
    currency_exposure?: CurrencyExposure | null;
    /** #253: gross assets by platform, the Overview platform donut's split. */
    platform_concentration?: Pick<PlatformAllocation, "total" | "items"> | null;
  };

/** One currency's part of net worth (#253). `currency` is an ISO code, or "CRYPTO" for
 * crypto other than USD stablecoins (not a currency). `value` = cash + stocks_funds +
 * stablecoins + crypto - liabilities; `percent` is its share of net worth. */
export type CurrencyExposureItem = {
  currency: string;
  cash: number;
  stocks_funds: number;
  stablecoins: number;
  crypto: number;
  liabilities: number;
  value: number;
  percent: number;
};

export type CurrencyExposure = { total: number; items: CurrencyExposureItem[] };

/** GET/PUT /dashboard/risk-thresholds (#253): the percent above which Risk calls a
 * figure concentrated; null = the app's default (lib/risk.ts). */
export type RiskThresholdsSetting = {
  largest_position_warn_pct: number | null;
  top_n_warn_pct: number | null;
  platform_warn_pct: number | null;
};

/** One part of a bridge line; a line's parts add up to its amount (#240). */
/** What a part is made of (#332): a holding, account, card or token; a part's items add up to it. */
export type BridgeItem = { label: string; amount: number | null; reason?: string | null; link?: string | null };

export type BridgePart = { key: string; label: string; amount: number; items?: BridgeItem[] };

/** Context for a bridge line that is not part of its amount. */
export type BridgeNote = { key: string; label: string; amount: number | null };

export type BridgeLineStatus = "ok" | "partial" | "unavailable";

/** One cause of the month's change; when `status` isn't ok, `reason` says why and the
 * part that couldn't be computed is in the bridge's `unexplained`. */
export type BridgeLine = {
  key: string;
  label: string;
  amount: number;
  status: BridgeLineStatus | string;
  reason: string | null;
  parts: BridgePart[];
  notes: BridgeNote[];
};

export type BridgeEndpoint = {
  month: string;
  boundary_at: string;
  as_of: string | null;
  value: number;
  net_worth: NetWorthBreakdown;
  baseline_missing: boolean;
};

export type BridgeMover = {
  asset_id: number | null;
  symbol: string;
  name: string | null;
  asset_class: string;
  start_value: number;
  end_value: number;
  change: number;
  price_effect: number;
  quantity_effect: number;
  fx_effect: number;
  /** price_effect + fx_effect: what the market did. Movers are ranked by it. */
  market_effect?: number;
  cause: "price" | "quantity" | "fx" | "unknown" | string;
};

/** A holding bought, sold or (crypto) moved in or out this month: its quantity effect,
 * not a gain or loss. `cash_recorded`: the account's cash is recorded, so a sale's money
 * is in that cash (#240). */
export type BridgeTrade = {
  asset_id: number | null;
  symbol: string;
  name: string | null;
  asset_class: string;
  amount: number;
  side: "bought" | "sold" | "moved_in" | "moved_out" | string;
  cash_recorded: boolean;
};

/** One data cause behind a period's change (#289). `amount` is in the base currency;
 * null when unknown (an FX gap leaves amounts out). */
export type MoveCause = {
  key: "first_statement" | "catch_up" | "statement" | "new_position" | "fx_gap" | "price_fallback" | string;
  label: string;
  detail?: string | null;
  amount?: number | null;
  significant: boolean;
  account_id?: number | null;
  as_of?: string | null;
};

/** Why the headline moved (#289): big = at least 5% of the start; `none_reason` when a
 * big move has no significant data cause. */
export type MoveCauses = {
  change: number;
  change_pct?: number | null;
  is_big_move: boolean;
  causes: MoveCause[];
  none_reason?: string | null;
};

/** GET /dashboard/month-bridge (#240, D-60): start + sum(lines) + unexplained = end. */
export type MonthBridge = FxStatus & {
  as_of_month: string;
  base_currency: string;
  snapshot_day: number;
  is_live: boolean;
  period_start: string;
  period_end: string;
  start: BridgeEndpoint;
  end: BridgeEndpoint;
  change: number;
  lines: BridgeLine[];
  unexplained: BridgeLine;
  liabilities_change: number;
  movers: BridgeMover[];
  trades?: BridgeTrade[];
  move_causes?: MoveCauses | null;
};

/** One bar of a page's six-month trend (Stocks, Crypto, Cash). #241 (D-61): the open
 * month's bar is live, month to date (the page's live headline); every other bar is a
 * completed month-end, or has no value when that month-end hasn't passed yet. */
export type MiniTrendPoint = {
  month: string;
  value?: number | null;
  is_live?: boolean;
};

export type DashboardNetWorthChange = {
  as_of_month: string;
  base_currency: string;
  net_worth_as_of: string | null;
  net_worth_snapshot_as_of?: string | null;
  net_worth_boundary_at?: string | null;
  net_worth_boundary_exact?: boolean | null;
  net_worth_freshness_status?: string | null;
  net_worth_change: DashboardSummary["net_worth_change"];
};

/** A holding's change vs the compare month-end (#251), split as Overview's bridge splits
 * it (D-60), in the base currency: abs = price_effect + quantity_effect + fx_effect + unsplit.
 * Buying or selling is the quantity effect, not a gain or a loss. */
export type StockMonthChange = {
  abs: number;
  /** abs / compare_value; null without a start value (a new holding). */
  pct?: number | null;
  price_effect: number;
  quantity_effect: number;
  fx_effect: number;
  /** What can't be split: no price or quantity on one side, or a value that isn't quantity x price x rate. */
  unsplit: number;
  compare_value: number;
  end_value: number;
  compare_month?: string | null;
  /** No stock data at all for compare_month (the page's stock_snapshot_missing). */
  baseline_missing: boolean;
  /** held | new (not held at the compare month-end) | sold (held then, not now). */
  side: "held" | "new" | "sold";
  start_quantity?: number | null;
  end_quantity?: number | null;
  /** Prices in price_currency; rates in base currency per unit of it. */
  start_price?: number | null;
  end_price?: number | null;
  price_currency?: string | null;
  start_rate?: number | null;
  end_rate?: number | null;
};

/** A Stocks page row: a /summary top holding plus its change this month (#251). */
export type StockHolding = DashboardSummary["top_holdings"][number] & {
  month_change?: StockMonthChange | null;
};

// #293 (D-78): realised P&L on sales, the month and its year to date.
export type RealisedTotals = {
  realised: number;
  sales: number;
  cost_unknown: number;
  fx_missing_currencies: string[];
  sources: Record<string, number>;
};

export type RealisedSale = {
  trade_date: string;
  symbol: string | null;
  platform: string | null;
  quantity: number;
  proceeds: number;
  cost: number | null;
  realised: number | null;
  currency: string;
  realised_base: number | null;
  /** ibkr | fifo | cost_unknown */
  source: string;
  fx_missing: boolean;
};

// #313: any period, grouped per stock (per account).
export type RealisedPeriodKey = "month" | "ytd" | "last_year" | "year" | "range";

export type RealisedPeriod = {
  key: RealisedPeriodKey;
  start: string;
  /** Inclusive, never after today. */
  end: string;
  label: string;
};

export type RealisedInstrument = {
  symbol: string | null;
  platform: string | null;
  currency: string;
  sales_count: number;
  quantity: number;
  /** Sales with a known cost and a rate only. */
  realised_base: number;
  proceeds_base: number;
  cost_base: number;
  /** In the trade currency, sales with a known cost. */
  realised: number;
  in_total: number;
  cost_unknown: number;
  fx_missing: boolean;
  sources: Record<string, number>;
  first_sale: string;
  last_sale: string;
  sales: RealisedSale[];
};

export type RealisedPnl = {
  base_currency: string;
  month: RealisedTotals;
  year_to_date: RealisedTotals;
  sales: RealisedSale[];
  period?: RealisedPeriod | null;
  period_totals?: RealisedTotals | null;
  by_instrument?: RealisedInstrument[];
  years_with_sales?: number[];
  /** The earliest trade the app holds: no sales are known before it. */
  trades_from?: string | null;
  /** Broker platforms with holdings but no trade data. */
  platforms_without_trades?: string[];
};

export type RealisedPeriodQuery = { period: RealisedPeriodKey; year?: number; from?: string; to?: string };

export type StockHoldingsSummary = FxStatus & {
  as_of_month: string;
  base_currency: string;
  snapshot_day: number | null;
  is_live: boolean;
  compare_month: string | null;
  current_holdings_as_of?: string | null;
  net_worth_as_of: string | null;
  net_worth_snapshot_as_of?: string | null;
  net_worth_boundary_at?: string | null;
  net_worth_boundary_exact?: boolean | null;
  net_worth_freshness_status?: string | null;
  top_holdings: StockHolding[];
  geography_breakdown?: Array<{
    geography: string;
    current_value: number;
    snapshot_value: number;
    delta_abs: number;
    delta_pct?: number | null;
  }>;
  geography_performance?: Array<{
    geography: string;
    current_value: number;
    snapshot_value: number;
    delta_abs: number;
    delta_pct?: number | null;
  }>;
  geography_performance_as_of?: string | null;
  platform_breakdown?: Array<{
    key: string;
    current_value: number;
    snapshot_value: number;
    delta_abs: number;
    delta_pct?: number | null;
    percent: number;
  }>;
  // #396 (U7): cost basis and unrealised P&L per platform, in the base currency.
  platform_totals?: StockPlatformTotal[];
  stock_current_total?: number;
  stock_snapshot_total?: number;
  // #232: the date of the holdings stock_snapshot_total is taken from.
  stock_snapshot_as_of?: string | null;
  quote_freshness_summary?: {
    fresh: number;
    stale: number;
    missing: number;
    /** Live view only (null on a past month): holdings without a fresh quote, statement-only ones included (#224). */
    no_live_price?: number | null;
  } | null;
  trend?: MiniTrendPoint[];
  /** No stock data at all for compare_month (not a real zero), #224. */
  stock_snapshot_missing?: boolean;
  /** QUOTE_STALE_DAYS: a price older than this is stale (#224). */
  quote_stale_days?: number | null;
  /** #251: the compare month-end's anchor ("vs 31 Oct close"). */
  compare_boundary_at?: string | null;
  /** #251: held at the compare month-end, sold since (value 0, month_change.side "sold"). */
  sold_holdings?: StockHolding[];
  /** #251: the headline's change as the rows add up:
   * abs = price_effect + quantity_effect + fx_effect + unsplit + not_in_holdings. */
  month_change_total?: {
    abs: number;
    price_effect: number;
    quantity_effect: number;
    fx_effect: number;
    unsplit: number;
    not_in_holdings: number;
    compare_value: number;
    compare_month?: string | null;
    baseline_missing: boolean;
  } | null;
};

export type PlatformAllocation = {
  as_of: string | null;
  /** #223: the requested month, and whether it is live (open month) or a past month-end. */
  as_of_month?: string | null;
  is_live?: boolean | null;
  total: number;
  items: Array<{
    platform: string;
    platform_type: string | null;
    country: string | null;
    value: number;
    percent: number;
  }>;
};

export type GeographyExposure = {
  as_of: string | null;
  base_currency: string;
  /** #241: live (quote-priced) for the open month, else the month-end snapshot. */
  is_live?: boolean | null;
  total: number;
  items: Array<{
    country: string;
    stocks_funds: number;
    cash: number;
    crypto: number;
    total: number;
    percent: number;
  }>;
};

export type CashDeposits = {
  total: number;
  items: Array<{
    source: string;
    value: number;
    percent: number;
  }>;
  as_of_month?: string | null;
  base_currency?: string | null;
  snapshot_day?: number | null;
  is_live?: boolean;
  // #232: the anchor the figures are taken at (a past month's month-end boundary, or "now").
  net_worth_boundary_at?: string | null;
  compare_month?: string | null;
  current_cash_as_of?: string | null;
  snapshot_cash_as_of?: string | null;
  current_total?: number | null;
  snapshot_total?: number | null;
  // #232: the stablecoins (USDC/USDT) in current_total / snapshot_total. The Cash page counts
  // them as cash; net worth (Overview, History) counts them under Crypto (D-42).
  current_stablecoin_total?: number | null;
  snapshot_stablecoin_total?: number | null;
  delta_abs?: number | null;
  delta_pct?: number | null;
  trend?: MiniTrendPoint[];
  currency_breakdown?: Array<{
    currency: string;
    current_value: number;
    snapshot_value: number;
    delta_abs: number;
    delta_pct?: number | null;
  }>;
  /** No cash data at all for compare_month (not a real zero), #224. */
  snapshot_missing?: boolean;
  /** #397 (U13): one row per cash account (and stablecoin source); adds up to current_total. */
  accounts?: CashAccountRow[];
  /** #397 (U14): foreign-currency cash revalued from the compare point to now. */
  fx_revaluation?: CashFxRevaluation | null;
};

/** One cash account on the Cash page (#397). `stale`: overdue on Data Hub (live month only). */
export type CashAccountRow = {
  account_id?: number | null;
  kind: "account" | "stablecoin" | string;
  label: string;
  platform: string;
  currencies?: string[];
  current_value: number;
  snapshot_value: number;
  delta_abs: number;
  last_data_date?: string | null;
  stale?: boolean | null;
};

/** Foreign-currency cash (no stablecoins) revalued at the rates now (#397); the bridge's cash FX part. */
export type CashFxRevaluation = {
  total: number;
  from_at: string;
  to_at: string;
  items: Array<{ currency: string; start_value: number; fx_effect: number }>;
};

export type NetWorthBreakdown = {
  total: number;
  cash: number;
  stocks_funds: number;
  crypto: number;
  liabilities: number;
};

export type AssetClassFreshness = {
  most_recent_at?: string | null;
  most_recent_label?: string | null;
  stalest_at?: string | null;
  stalest_label?: string | null;
};

export type NetWorthFreshness = {
  stocks: AssetClassFreshness;
  crypto: AssetClassFreshness;
  cash: AssetClassFreshness;
};

export type DashboardBootstrap = FxStatus & {
  as_of_month: string;
  base_currency: string;
  snapshot_day: number | null;
  /** #223: true for the open (or a future) month (headline: current_net_worth); false for a
   * past month (headline: net_worth, its month-end snapshot). */
  is_live?: boolean | null;
  current_net_worth_as_of?: string | null;
  current_net_worth?: NetWorthBreakdown | null;
  current_net_worth_freshness?: NetWorthFreshness | null;
  net_worth_as_of: string | null;
  net_worth_snapshot_as_of?: string | null;
  net_worth_boundary_at?: string | null;
  net_worth_boundary_exact?: boolean | null;
  net_worth_freshness_status?: string | null;
  net_worth: NetWorthBreakdown;
  current_stock_exposure_total?: number | null;
  current_crypto_exposure_total?: number | null;
  current_cash_percent?: number | null;
  stock_exposure_total: number;
  crypto_exposure_total: number;
  cash_percent: number;
};

export type WealthTimelineFreshnessStatus = "fresh" | "carried" | "stale" | "missing";

export type WealthTimelineSourceFreshness = {
  platform: string;
  as_of: string | null;
  days_old: number | null;
  status: WealthTimelineFreshnessStatus;
};

export type WealthTimelinePoint = {
  month: string;
  anchor_date: string;
  total: number;
  cash: number;
  stocks_funds: number;
  crypto: number;
  liabilities: number;
  source_freshness: WealthTimelineSourceFreshness[];
  freshness_status: WealthTimelineFreshnessStatus;
  computed_at: string | null;
  uploads: string[];
};

export type WealthTimeline = {
  base_currency: string;
  points: WealthTimelinePoint[];
  now: {
    total: number;
    cash: number;
    stocks_funds: number;
    crypto: number;
    liabilities: number;
    as_of: string | null;
    /** Platforms with a statement import in the still-open month (#138). */
    uploads: string[];
  };
  /** #292: the span of the user's data (History's default range); null with no data. */
  data_span?: WealthTimelineDataSpan | null;
};

export type WealthTimelineBackfillResult = {
  months_written: number;
  base_currency: string;
};

/** The span of the user's imported data (#292): History's default range. */
export type WealthTimelineDataSpan = {
  first_month: string;
  months: number;
};

/** Step 1 of a "Generate history" run: past FX rates, fetched once and capped (#292). */
export type HistoryGenerateFx = {
  status?: string | null;
  fetched_requests?: number | null;
  failed_requests?: number | null;
  remaining_requests?: number | null;
  unsupported_currencies?: string[] | null;
};

/** A background "Generate history" run's progress (#292). */
export type HistoryGenerateStatus = {
  status: "idle" | "running" | "completed" | "failed";
  stage: "fx" | "months" | "done";
  base_currency: string;
  months: number;
  months_total: number;
  months_done: number;
  current_month: string | null;
  months_written: number;
  started_at: string | null;
  finished_at: string | null;
  fx: HistoryGenerateFx | null;
  error: string | null;
};

export type WealthTopMover = {
  asset_id: number | null;
  symbol: string;
  asset_class: string;
  current_value: number;
  previous_value: number;
  delta_abs: number;
  delta_pct: number | null;
  compare_month: string;
};

export type WealthTopMovers = {
  compare_month: string;
  gainers: WealthTopMover[];
  detractors: WealthTopMover[];
};

export type NetWorthSinceUpdateChange = NetWorthChange;

/** #249 (D-65): a since-update mover, with what its compare value was priced at. */
export type SinceUpdateTopMover = WealthTopMover & {
  /** "quote" (last quote on or before the compare date) | "statement" (its own statement price); null for crypto or an asset not held then. */
  compare_price_basis?: "quote" | "statement" | null;
  /** The date of that quote or statement (YYYY-MM-DD). */
  compare_price_as_of?: string | null;
  /** Compared with a statement older than the compare date (no usable quote by then) while quote-priced now. */
  compare_price_fallback?: boolean;
};

export type SinceUpdateTopMovers = {
  compare_month: string;
  gainers: SinceUpdateTopMover[];
  detractors: SinceUpdateTopMover[];
};

/** #249 (D-65): how the compare side's stocks and funds were priced, per asset. */
export type SinceUpdateCompareBasis = {
  price_date: string | null;
  holdings: number;
  quoted: number;
  statement_priced: number;
  older_statement_priced: number;
};

export type NetWorthSinceUpdate = {
  base_currency: string;
  current_as_of: string | null;
  compare_as_of: string | null;
  net_worth_change: NetWorthSinceUpdateChange;
  component_change: {
    cash?: NetWorthSinceUpdateChange;
    stocks_funds?: NetWorthSinceUpdateChange;
    crypto?: NetWorthSinceUpdateChange;
  };
  top_movers: SinceUpdateTopMovers | null;
  /** #249 (D-65): "quoted_at_compare_date": every holding vs its last quote on or before compare_as_of. */
  basis?: string | null;
  compare_basis?: SinceUpdateCompareBasis | null;
};

export type StockExposureItem = {
  key: string;
  value: number;
  percent: number;
};

export type StockExposure = {
  as_of: string | null;
  is_live?: boolean | null;
  base_currency: string;
  total: number;
  by_country: StockExposureItem[];
  by_platform: StockExposureItem[];
};

/** A platform's stocks (#396, U7): rows with no average cost are counted apart, not as a zero cost. */
export type StockPlatformTotal = {
  platform: string;
  value: number;
  cost_basis: number;
  unrealised_pnl: number;
  unrealised_pnl_pct?: number | null;
  positions: number;
  positions_without_cost: number;
  value_without_cost: number;
};
