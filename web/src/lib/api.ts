import { currentAbortSignal, isAbortError } from "./abortScope";

export function resolveApiBase(
  rawApiBase?: string,
  locationLike?: { protocol?: string; hostname?: string } | null,
  rawApiPort?: string,
): string {
  const explicit = rawApiBase?.trim();
  if (explicit) {
    return explicit.replace(/\/+$/, "");
  }

  const port = rawApiPort?.trim() || "8000";
  const currentLocation =
    locationLike ?? (typeof window !== "undefined" ? window.location : null);
  const hostname = currentLocation?.hostname?.trim();
  const protocol = currentLocation?.protocol === "https:" ? "https:" : "http:";
  if (hostname) {
    return `${protocol}//${hostname}:${port}`;
  }
  return `http://localhost:${port}`;
}

const RAW_API_BASE = import.meta.env.VITE_API_BASE as string | undefined;
const RAW_API_PORT = import.meta.env.VITE_API_PORT as string | undefined;
const API_BASE = resolveApiBase(RAW_API_BASE, null, RAW_API_PORT);
let accessTokenMemory: string | null = null;
let refreshInFlight: Promise<AuthSession | null> | null = null;
let authFailureHandler: (() => void) | null = null;

export function getAccessToken(): string | null {
  return accessTokenMemory;
}

export function setAccessToken(token: string | null): void {
  accessTokenMemory = token;
}

export function setAuthFailureHandler(handler: (() => void) | null): void {
  authFailureHandler = handler;
}

function notifyAuthFailure(): void {
  authFailureHandler?.();
}

function buildHeaders(
  initHeaders?: HeadersInit,
  opts?: { includeJsonContentType?: boolean; skipAuth?: boolean },
): Headers {
  const headers = new Headers(initHeaders);
  if (opts?.includeJsonContentType !== false && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!opts?.skipAuth) {
    const token = getAccessToken();
    if (token && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }
  return headers;
}

type RequestOptions = { skipAuth?: boolean; skipRefreshRetry?: boolean };

type ApiValidationDetail = {
  loc?: Array<string | number>;
  msg?: string;
};

function formatApiValidationMessage(detail: unknown): string | null {
  if (typeof detail === "string" && detail.trim()) {
    return detail.trim();
  }

  // A structured refusal (e.g. an upload sent to the wrong account, #180).
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message.trim();
  }

  if (!Array.isArray(detail)) {
    return null;
  }

  const messages = detail
    .map((item) => {
      const entry = item as ApiValidationDetail;
      const msg = typeof entry.msg === "string" ? entry.msg.trim() : "";
      if (!msg) return null;

      const field = Array.isArray(entry.loc)
        ? entry.loc
            .filter((part) => typeof part === "string")
            .filter((part) => part !== "body")
            .join(".")
        : "";
      return field ? `${field}: ${msg}` : msg;
    })
    .filter((message): message is string => Boolean(message));

  if (!messages.length) {
    return null;
  }
  return messages.join("; ");
}

function formatHttpError(status: number, rawText: string): string {
  const text = rawText.trim();
  if (!text) {
    return `Request failed (${status}).`;
  }

  try {
    const parsed = JSON.parse(text) as { detail?: unknown; message?: unknown };
    const detailMessage = formatApiValidationMessage(parsed.detail);
    if (detailMessage) return detailMessage;
    if (typeof parsed.message === "string" && parsed.message.trim()) return parsed.message.trim();
  } catch {
    // Not JSON, fall through to plain text handling.
  }

  if (status >= 500) return "Server error. Please try again.";
  return text;
}

/**
 * Thrown when a session is definitively invalid (401 from the server).
 * Distinct from transient network or server errors.
 */
export class AuthSessionExpiredError extends Error {
  constructor(message = "Session expired. Please sign in again.") {
    super(message);
    this.name = "AuthSessionExpiredError";
  }
}

async function callRefreshEndpoint(): Promise<AuthSession | null> {
  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: buildHeaders(undefined, { includeJsonContentType: false, skipAuth: true }),
    });
    if (!res.ok) {
      if (res.status === 401) {
        // Definitive auth failure: the session is truly invalid.
        setAccessToken(null);
        notifyAuthFailure();
      }
      // For 5xx or other transient errors, don't clear auth state.
      return null;
    }
    const payload = (await res.json()) as AuthSession;
    if (!payload?.access_token) {
      setAccessToken(null);
      notifyAuthFailure();
      return null;
    }
    setAccessToken(payload.access_token);
    return payload;
  } catch {
    // Network/transport error: treat as transient. Do not force logout.
    return null;
  }
}

function refreshSession(): Promise<AuthSession | null> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = callRefreshEndpoint().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

async function refreshAccessToken(): Promise<string | null> {
  const session = await refreshSession();
  return session?.access_token ?? null;
}

export async function refreshAccessTokenNow(): Promise<string | null> {
  return refreshAccessToken();
}

/**
 * Same deduped refresh as refreshAccessTokenNow(), but resolves to the whole response:
 * since #146 /auth/refresh also carries `user` and `preferences`, so a cold load needs
 * this one request instead of refresh -> /auth/me -> /auth/preferences.
 */
export async function refreshSessionNow(): Promise<AuthSession | null> {
  return refreshSession();
}

async function req<T>(path: string, init?: RequestInit, opts: RequestOptions = {}): Promise<T> {
  // Read synchronously, before the first await (#148): see lib/abortScope.ts.
  const signal = init?.signal ?? currentAbortSignal();
  const execute = async (): Promise<Response> => {
    try {
      const { headers: initHeaders, ...restInit } = init ?? {};
      return await fetch(`${API_BASE}${path}`, {
        credentials: "include",
        ...restInit,
        ...(signal ? { signal } : {}),
        headers: buildHeaders(initHeaders, { includeJsonContentType: true, skipAuth: opts.skipAuth }),
      });
    } catch (err: unknown) {
      // An aborted request (a superseded month/currency, or the page went away) is not
      // an unreachable API: let the caller see the AbortError as-is.
      if (isAbortError(err)) throw err;
      const reason = err instanceof Error ? err.message : String(err);
      throw new Error(`Unable to reach API at ${API_BASE}: ${reason}`, { cause: err });
    }
  };

  let res = await execute();
  let sessionExpired = false;
  if (res.status === 401 && !opts.skipAuth && !opts.skipRefreshRetry) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      res = await execute();
    } else {
      sessionExpired = true;
    }
  }
  if (!res.ok) {
    const text = await res.text();
    if (res.status === 401) {
      if (!opts.skipAuth && sessionExpired) {
        throw new AuthSessionExpiredError("Your session expired. Please sign in again.");
      }
      if (opts.skipAuth) {
        // e.g. /auth/refresh returned 401 → truly invalid session
        throw new AuthSessionExpiredError(formatHttpError(res.status, text));
      }
    }
    throw new Error(formatHttpError(res.status, text));
  }
  return res.json() as Promise<T>;
}

export type Platform = {
  id: number;
  code: string;
  name: string;
  platform_type: string; // BANK | BROKER | EXCHANGE | CARD_ISSUER | WALLET_PROVIDER
  country: string;       // SG | US | IN | HK | GLOBAL
  website?: string | null;
};

export type AuthMe = {
  id: number;
  username: string;
  display_name?: string | null;
  email?: string | null;
  is_admin: boolean;
};

export type AuthToken = {
  access_token: string;
  token_type: string;
  expires_in: number;
};

/** /auth/login and /auth/refresh response (#146): the token plus, additively, the user
 * (same shape as /auth/me) and their preferences (same shape as /auth/preferences).
 * Optional: callers fall back to authMe()/getPreferences() when absent. */
export type AuthSession = AuthToken & {
  user?: AuthMe | null;
  preferences?: UserPreferences | null;
};

export type ChangePasswordResult = {
  status: string;
  signed_out_sessions: number;
};

/** Where the effective home timezone comes from (#202): chosen by the user (or filled
 * from their browser), the app's TZ for an account from before #202, or not filled yet. */
export type TimezoneSource = "user" | "app" | "unset";

export type UserPreferences = {
  theme: "dark" | "light";
  accent_color: "#0f7a5c" | "#2b6ddb" | "#8650d9" | "#b5842a";
  /** #202 (additive; absent from older servers). The effective home timezone (IANA name):
   * months, month-end anchors and History follow it. */
  timezone?: string | null;
  timezone_source?: TimezoneSource | null;
  /** #202: the base currency saved on the server; null until set. */
  base_currency?: string | null;
};

export type UserPreferencesPatch = {
  theme?: "dark" | "light";
  accent_color?: "#0f7a5c" | "#2b6ddb" | "#8650d9" | "#b5842a";
  /** IANA timezone name, e.g. "America/New_York" (#202). */
  timezone?: string;
  /** One of CURRENCY_OPTIONS (#202). */
  base_currency?: string;
};

export type Account = {
  id: number;
  name: string;
  platform: string;      // legacy text column (DBS, IBKR, etc.)
  platform_id?: number | null;
  account_type: string;  // BANK | BROKER | EXCHANGE | WALLET | CREDIT_CARD | LOAN | MUTUAL_FUND
  currency: string;
  country?: string | null;
  /** #207: closed on this date (YYYY-MM-DD); counts up to it, nothing after. */
  closed_on?: string | null;
  /** #207: the month (YYYY-MM) the two fields below describe (default: latest completed). */
  data_month?: string | null;
  /** #207: date of the newest fact that month's valuation reads for the account. */
  last_data_as_of?: string | null;
  /** #207: set when that fact predates the month: its value is carried forward from this date. */
  carried_forward_from?: string | null;
};

/** PATCH /accounts/{id} (#207): a close date, or null to reopen. */
export type AccountUpdate = {
  closed_on: string | null;
};

/** Additive FX fields (#139) on responses with base-currency totals.
 * fx_incomplete: a value had no FX rate at all and is left out of the totals
 * (never counted 1:1); fx_missing_currencies names those currencies.
 * fx_stale_currencies: converted with a stored rate older than the lookback. */
export type FxStatus = {
  fx_incomplete?: boolean;
  fx_missing_currencies?: string[];
  fx_stale_currencies?: string[];
};

/** FX back-fill (#290): `GET /fx/backfill-plan` and `POST /fx/backfill` (admin). */
export type FxBackfillPlan = {
  span_start: string | null;
  span_end: string | null;
  currencies: string[];
  unsupported_currencies: string[];
  uncovered_days: number;
  planned_requests: Array<{ start: string; end: string }>;
  remaining_requests: number;
};

export type FxBackfillResult = FxBackfillPlan & {
  status: "completed" | "partial" | "failed" | "up_to_date" | "remote_disabled";
  fetched_requests: number;
  failed_requests: number;
  rows_stored: number;
};

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

export type SpendingSummary = FxStatus & {
  month: string;
  base_currency: string;
  income_total: number;
  expense_total: number;
  net: number;
  savings_rate: number | null;
  income_categories: Array<{ category: string; amount: number }>;
  expense_categories: Array<{ category: string; amount: number }>;
};

export type CashFlowTransaction = {
  transaction_id: number;
  ts: string;
  account_id: number;
  account_name: string;
  account_type: string;
  amount: number;
  currency: string;
  base_amount: number;
  type: string;
  raw_category: string | null;
  resolved_category: string;
  resolved_category_id: number | null;
  category_source: string;
  merchant_counterparty: string | null;
  notes: string | null;
};

export type CashFlowDetailSection = {
  total: number;
  transaction_count: number;
  included_types: string[];
  transactions: CashFlowTransaction[];
};

export type CashFlowBreakdownItem = {
  label: string;
  amount: number;
  percent: number;
};

export type CashFlowMerchantItem = {
  merchant: string;
  amount: number;
  percent: number;
  transaction_count: number;
};

export type CashFlowCategoryDeltaItem = {
  label: string;
  current_amount: number;
  prior_amount: number;
  delta_amount: number;
  delta_percent: number | null;
  direction: string;
};

export type CashFlowTrendPoint = {
  month: string;
  inflows: number;
  outflows: number;
  net: number;
  savings_rate: number | null;
  burn_rate: number | null;
};

export type CashFlowWaterfall = {
  starting_cash: number | null;
  snapshot_start_as_of: string | null;
  snapshot_start_boundary_at: string | null;
  inflows: number;
  outflows: number;
  transfers_and_funding: number | null;
  investment_and_fx_effects: number | null;
  other_cash_movements: number | null;
  snapshot_end_as_of: string | null;
  snapshot_end_boundary_at: string | null;
  boundary_exact: boolean;
  availability_message: string | null;
  ending_cash: number | null;
  /** #265 (D-72): drawn between the nearest cash snapshots at or before the month's start and
   * end anchors (the open month: the newest so far). Optional for older API responses. */
  bridge_available?: boolean;
  span_start?: string | null;
  span_end?: string | null;
  span_basis?: "exact" | "nearest" | string | null;
};

export type CashFlowDiagnosticAnswer = {
  question: string;
  answer: string;
};

/** The month vs the month before, like for like (#243, D-63): the open month is month to
 * date (days 1..through_day) against the previous month's days 1..prior_through_day (the
 * same day, clamped to that month's length); any other month is whole vs whole. */
export type CashFlowComparison = {
  basis: "month_to_date" | "full_month" | string;
  month: string;
  month_days: number;
  through_day: number;
  prior_month: string;
  prior_month_days: number;
  prior_through_day: number;
  /** ISO date, first day counted. */
  prior_start: string;
  /** ISO date, last day counted (inclusive). */
  prior_end: string;
  inflows: number;
  outflows: number;
  net: number;
  savings_rate: number | null;
  prior_inflows: number;
  prior_outflows: number;
  prior_net: number;
  prior_savings_rate: number | null;
  inflows_change: number;
  outflows_change: number;
  net_change: number;
  outflow_category_deltas: CashFlowCategoryDeltaItem[];
  deterioration_drivers: CashFlowCategoryDeltaItem[];
};

export type CashFlowAnalytics = {
  /** Still returned (fields are only added); the page no longer shows it (#243). */
  burn_rate: number | null;
  prior_month: string | null;
  prior_month_net: number | null;
  free_cash_flow_change_vs_prior_month: number | null;
  outflow_categories: CashFlowBreakdownItem[];
  inflow_categories: CashFlowBreakdownItem[];
  outflow_recurring_split: CashFlowBreakdownItem[];
  inflow_recurring_split: CashFlowBreakdownItem[];
  outflow_fixed_variable_split: CashFlowBreakdownItem[];
  inflow_source_mix: CashFlowBreakdownItem[];
  top_outflow_merchants: CashFlowMerchantItem[];
  largest_inflow_drivers: CashFlowBreakdownItem[];
  outflow_category_deltas: CashFlowCategoryDeltaItem[];
  deterioration_drivers: CashFlowCategoryDeltaItem[];
  trend: CashFlowTrendPoint[];
  waterfall: CashFlowWaterfall;
  answers: CashFlowDiagnosticAnswer[];
  /** #243: always sent by the API; optional here like its Python default. */
  comparison?: CashFlowComparison | null;
};

export type CashFlowDetail = FxStatus & {
  month: string;
  base_currency: string;
  income_total: number;
  expense_total: number;
  net: number;
  savings_rate: number | null;
  calculation: string;
  analytics: CashFlowAnalytics;
  income: CashFlowDetailSection;
  expenses: CashFlowDetailSection;
};

/** GET /spending/cash-flow-trend (#149): /spending/cash-flow-detail's `analytics.trend`
 * only (the same numbers), for History. */
export type CashFlowTrend = FxStatus & {
  month: string;
  base_currency: string;
  trend: CashFlowTrendPoint[];
};

export type CreditCardSummary = FxStatus & {
  month: string;
  base_currency: string;
  total_spend: number;
  cards: Array<{
    account_id: number;
    account_name: string;
    card_name: string;
    issuer: string;
    credit_limit: number;
    available_limit?: number | null;
    available_limit_as_of?: string | null;
    current_due_source?: string;
    statement_day: number;
    due_day: number;
    due_date: string;
    current_due: number;
    utilization: number | null;
  }>;
};

export type CreditCardTransaction = {
  account_id: number;
  account_name: string;
  card_name: string;
  issuer: string;
  ts: string;
  description: string;
  amount: number;
  type: string;
  category: string | null;
  resolved_category: string;
  category_source: string;
  merchant_counterparty: string | null;
  notes: string | null;
};

export type CreditCardRecurringPayment = {
  account_id: number;
  account_name: string;
  card_name: string;
  issuer: string;
  merchant_counterparty: string;
  months_present: number;
  current_month_amount: number;
  /** #266: how it repeats ("monthly") and its usual amount (median charge). Older APIs omit them. */
  cadence?: string;
  typical_amount?: number | null;
};

export type CreditCardDetail = FxStatus & {
  month: string;
  base_currency: string;
  total_spend: number;
  cards: CreditCardSummary["cards"];
  transactions: CreditCardTransaction[];
  top_purchases: CreditCardTransaction[];
  recurring_payments: CreditCardRecurringPayment[];
};

export type CreditCardAnalyticsCard = {
  account_id: number;
  account_name: string;
  card_name: string;
  issuer: string;
  spend: number;
  transaction_count: number;
  available_limit?: number | null;
  available_limit_as_of?: string | null;
  statement_day: number;
  due_day: number;
  due_date: string;
};

export type CreditCardAnalyticsTrendPoint = {
  month: string;
  spend: number;
};

export type CreditCardAnalyticsCategory = {
  label: string;
  amount: number;
  percent: number;
};

/** One card between two dated balances (#300); amounts in the card's currency.
 *  `to_date` null: the newest balance carried to today. `difference` = printed - expected. */
export type CreditCardBalancePeriod = {
  from_date: string;
  to_date: string | null;
  opening: number;
  charges: number;
  fees: number;
  interest: number;
  payments: number;
  credits: number;
  transaction_count: number;
  expected: number;
  printed: number | null;
  difference: number | null;
  flagged: boolean;
  paid_in_full: boolean | null;
  /** #308: payments found only on the paying bank account (included in `payments`). */
  bank_payments?: number;
  /** #308: why a difference is left, when the ledger can tell. */
  note?: string | null;
};

/** A card's running balance and statement check (#300, D-76). */
export type CreditCardBalanceItem = {
  account_id: number;
  account_name: string;
  card_name: string;
  issuer: string;
  currency: string;
  /** "running" (a dated balance carried by the card's transactions) | "transactions" (none yet: an estimate). */
  method: "running" | "transactions" | string;
  /** Negative: a credit (overpaid). */
  owed_now: number;
  owed_now_base: number;
  last_balance_date: string | null;
  last_balance: number | null;
  last_balance_source: string | null;
  paid_since: number;
  charges_since: number;
  paid_in_full: boolean | null;
  due_date: string | null;
  fees_interest_ytd: number;
  last_transaction_date: string | null;
  flagged_count: number;
  /** Newest first. */
  periods: CreditCardBalancePeriod[];
};

export type CreditCardBalances = FxStatus & {
  base_currency: string;
  as_of: string;
  total_owed_base: number;
  flagged_count: number;
  cards: CreditCardBalanceItem[];
};

export type CreditCardAnalytics = FxStatus & {
  month: string;
  base_currency: string;
  months: number;
  account_id: number | null;
  total_spend: number;
  transaction_count: number;
  purchase_spend: number;
  prior_month: string;
  prior_month_spend: number;
  cards: CreditCardAnalyticsCard[];
  charges: CreditCardTransaction[];
  charge_total: number;
  categories: CreditCardAnalyticsCategory[];
  trend: CreditCardAnalyticsTrendPoint[];
  transactions: CreditCardTransaction[];
  recurring_payments: CreditCardRecurringPayment[];
};

export type ImportJobListItem = {
  id: number;
  status: string;
  platform: string;
  account_id: number;
  original_filename: string;
  created_at: string | null;
  // #180: why it was refused or failed, when it was removed, and whether
  // "Remove this import" can undo it.
  error_message?: string | null;
  removed_at?: string | null;
  removable?: boolean;
};

// Why an upload was refused before anything was written (409 detail, #180).
export type UploadRefusal = {
  code: "account_type_mismatch" | "statement_account_mismatch" | string;
  message: string;
  job_id?: number | null;
  parser_key?: string | null;
  account_type?: string | null;
  expected_account_types?: string[];
  statement_last4?: string;
  linked_last4?: string;
  suggested_account_id?: number | null;
  // Present when the refusal can be overridden ("upload anyway").
  override_field?: string;
};

export class UploadRefusedError extends Error {
  refusal: UploadRefusal;

  constructor(refusal: UploadRefusal) {
    super(refusal.message);
    this.name = "UploadRefusedError";
    this.refusal = refusal;
  }
}

function uploadRefusalFrom(status: number, rawText: string): UploadRefusal | null {
  if (status !== 409) return null;
  try {
    const detail = (JSON.parse(rawText) as { detail?: unknown }).detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      const refusal = detail as UploadRefusal;
      if (typeof refusal.code === "string" && typeof refusal.message === "string") return refusal;
    }
  } catch {
    // Not JSON.
  }
  return null;
}

export type ImportJobRemoval = {
  job_id: number;
  status: "REMOVED";
  account_id: number;
  removed: {
    transactions: number;
    balance_snapshots: number;
    position_snapshots: number;
    restored_rows: number;
  };
  history_dirty_from: string | null;
};

export type ImportJobDetail = {
  job: {
    id: number;
    status: string;
    platform: string;
    account_id: number;
    original_filename: string;
    stored_path: string;
    file_sha256: string;
    format_signature: string | null;
    parser_key: string | null;
    report_path: string | null;
    error_message: string | null;
    created_at: string | null;
    updated_at: string | null;
  };
  report: Record<string, unknown> | string | null;
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
};

export type CryptoWallet = {
  id: string;
  chain_type: string;
  chain: string;
  address: string;
  label?: string | null;
  status: string;
  created_at?: string | null;
  verified_at?: string | null;
};

export type CryptoWalletInitResponse = {
  verification_id?: number;
  chain_type: string;
  chain: string;
  address: string;
  message_to_sign: string;
  message_bytes_b64?: string;
  message_hash?: string;
  nonce: string;
  expires_at: string;
};

export type TokenVisibility = "shown" | "hidden";
export type TokenVisibilityOverride = { chain: string; contract_or_mint: string; visibility: TokenVisibility };

export type CryptoSummary = FxStatus & {
  month?: string;
  is_live?: boolean;
  compare_month?: string | null;
  as_of?: string | null;
  snapshot_day?: number | null;
  snapshot_as_of?: string | null;
  total_crypto_usd: number;
  total_crypto_base: number;
  snapshot_total_base?: number;
  snapshot_total_usd?: number;
  snapshot_delta_base?: number;
  snapshot_delta_pct?: number | null;
  /** Nothing to compare with for compare_month (#224): no_data, or no_fx_rate (D-30). */
  snapshot_missing?: boolean;
  snapshot_missing_reason?: "no_data" | "no_fx_rate" | null;
  base_currency: string;
  eth_exposure_usd?: number;
  eth_exposure_base?: number;
  token_exposure_usd?: number;
  token_exposure_base?: number;
  token_count?: number;
  priced_token_count?: number;
  trend?: MiniTrendPoint[];
  eth: { balance: number; value_usd: number; value_base: number };
  sol: { balance: number; value_usd: number; value_base: number };
  top5_holdings: Array<{
    symbol: string;
    chain: string;
    amount: number;
    value_usd: number;
    value_base: number;
    wallet_id?: string;
  }>;
  top_holdings: Array<{
    symbol: string;
    chain: string;
    amount: number;
    value_usd: number;
    value_base: number;
    asset_class: string;
    wallet_id?: string;
    wallet_label?: string | null;
    wallet_address?: string | null;
    price_usd?: number | null;
    price_change_usd?: number | null;
    price_change_pct?: number | null;
    value_change_base?: number | null;
    value_change_pct?: number | null;
    snapshot_value_base?: number | null;
    snapshot_delta_base?: number | null;
    snapshot_delta_pct?: number | null;
    holdings_as_of?: string | null;
    price_as_of?: string | null;
    holdings_provider?: string | null;
    price_provider?: string | null;
    /** #342: the token's contract/mint and "chain:contract" key (null for a native coin). */
    contract_or_mint?: string | null;
    token_key?: string | null;
    /** Never priced in any snapshot and not allowlisted: likely airdropped spam. */
    unknown_token?: boolean;
    /** The user's own choice: "shown" (not spam), "hidden", or null (automatic). */
    visibility_override?: TokenVisibility | null;
    /** Hidden from the lists by default (unknown, or hidden by the user). */
    hidden?: boolean;
    hidden_reason?: "unknown_token" | "user_hidden" | null;
  }>;
  /** #342: how many of top_holdings are hidden. */
  hidden_token_count?: number;
  wallet_exposure?: Array<{
    wallet_id: string;
    label?: string | null;
    address: string;
    chain_type: string;
    chain: string;
    total_usd: number;
    total_base: number;
    percent?: number;
    holdings_as_of?: string | null;
    price_as_of?: string | null;
    holdings_provider?: string | null;
    price_provider?: string | null;
    stale_holdings?: boolean;
    stale_prices?: boolean;
  }>;
  chain_exposure?: Array<{
    chain: string;
    total_usd: number;
    total_base: number;
    percent: number;
  }>;
  wallet_chain_exposure?: Array<{
    wallet_id: string;
    chain: string;
    total_usd: number;
    total_base: number;
  }>;
  last_refreshed_at: string | null;
  holdings_as_of?: string | null;
  price_as_of?: string | null;
  stale_holdings?: boolean;
  stale_prices?: boolean;
  is_stale: boolean;
  refresh_triggered: boolean;
};

/** One stablecoin row: the same values as its row in `CryptoSummary.top_holdings`. */
export type StablecoinHolding = {
  symbol: string;
  chain: string;
  amount: number;
  value_usd: number;
  value_base: number;
  asset_class: string;
  wallet_id: string;
  wallet_label?: string | null;
  holdings_as_of?: string | null;
  price_as_of?: string | null;
};

/** GET /crypto/stablecoins (#149): the stablecoin rows of /crypto/summary's top_holdings
 * (same month, anchor and FX rate) and their total, for the Cash page. */
export type CryptoStablecoins = FxStatus & {
  month: string;
  is_live: boolean;
  as_of: string;
  base_currency: string;
  /** The symbols counted as stablecoins, in display order. */
  symbols: string[];
  total_base: number;
  holdings: StablecoinHolding[];
};

export type CryptoAllowlistItem = {
  id: number;
  chain: string;
  contract_address: string;
  symbol?: string | null;
  name?: string | null;
  created_at?: string | null;
};

export type CategoryTaxonomy = {
  id: number;
  code: string;
  name: string;
  parent_id: number | null;
  display_order: number;
};

export type UnmappedTransaction = {
  transaction_id: number;
  ts: string;
  account_id: number;
  account_name: string;
  amount: number;
  currency: string;
  type: string;
  raw_category: string | null;
  merchant_counterparty: string | null;
  notes: string | null;
};

export type CategoryOverridePayload = {
  transaction_id: number;
  category_id: number;
};

export type CategoryOverrideBulkPayload = {
  transaction_ids: number[];
  category_id: number;
};

export type CategoryOverrideBulkResult = {
  applied: number;
  transaction_ids: number[];
};

export type CategoryResolution = {
  transaction_id: number;
  raw_category: string | null;
  override_category: string | null;
  resolved_category: string;
  source: string;
  rule_id: number | null;
  rule_name: string | null;
};

export type Health = {
  status: string;
  /** #155: "ok", or "unreachable" (with HTTP 503). */
  database?: string;
  /** #155: newest applied migration vs the newest migration file; current is null when either is unknown. */
  migrations?: { applied: string | null; latest_file: string | null; current: boolean | null };
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

export type Currency = {
  id: number;
  code: string;
  name?: string | null;
  country?: string | null;
};

export type AccountOptions = {
  account_types: string[];
  currencies: string[];
  countries: string[];
  currency_pattern: string;
};

export type AccountCreate = {
  name: string;
  platform_id: number | null;
  platform: string;
  account_type: string;
  currency: string;
  country: string | null;
};

export type PlatformCreate = {
  code: string;
  name: string;
  platform_type: string;
  country: string;
  website?: string | null;
};

export type PlatformOptions = {
  platform_types: string[];
  countries: string[];
  country_pattern: string;
};

export type CurrencyCreate = {
  code: string;
  name?: string | null;
  country?: string | null;
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

export type MarketDataRun = {
  id: number;
  provider: string;
  exchange_code: string;
  trade_date: string;
  status: string;
  requested_symbols: number;
  received_rows: number;
  upserted_rows: number;
  missing_symbols: number;
  started_at?: string | null;
  finished_at?: string | null;
  error_summary?: string | null;
};

export type MarketDataSymbolDiagnostic = {
  asset_id: number;
  symbol: string;
  mapped_symbol: string;
  provider_symbol?: string | null;
  provider?: string | null;
  source?: string | null;
  currency?: string | null;
  latest_price?: number | null;
  latest_trade_date?: string | null;
  age_days?: number | null;
  freshness_status: string;
  refresh_status: string;
  failure_reason?: string | null;
  reason_code?: "RATE_LIMITED" | "NO_TRADE_REPORTED" | "PROVIDER_ERROR" | "INVALID_PRICE" | null;
  attempt_status?: string | null;
};

/** A held stock or fund the quote refresh can't price (#222, #320), with Yahoo tickers worth trying. */
export type MarketDataUnpricedItem = {
  instrument_id: number;
  asset_id: number | null;
  symbol: string | null;
  name: string | null;
  currency: string | null;
  exchange_code: string | null;
  platform: string | null;
  reason: "no_asset" | "no_symbol" | "no_quote" | string;
  suggested_yahoo_symbols: string[];
};

export type MarketDataUnpriced = {
  items: MarketDataUnpricedItem[];
  /** Admins only: the symbol map and prices are shared data (#152). */
  can_fix: boolean;
};

/** POST /market-data/ticker-test (#320). */
export type MarketDataTickerTest = {
  found: boolean;
  yahoo_symbol: string;
  close?: number | null;
  trade_date?: string | null;
  currency?: string | null;
  error?: string | null;
};

/** POST /market-data/ticker (#320): the saved override and the stored quote. */
export type MarketDataTickerSet = MarketDataTickerTest & {
  asset_id: number;
  exchange_code: string;
  action: "set" | "create_map" | "unchanged" | string;
};

export type MarketDataExchangeStatus = Partial<MarketDataRun> & {
  exchange_code: string;
  diagnostics_summary: {
    active_symbols: number;
    refreshed: number;
    failed: number;
    deferred: number;
    fresh: number;
    stale: number;
    missing: number;
  };
  symbols: MarketDataSymbolDiagnostic[];
};

export type DataHubActivityItem = {
  kind: string;
  title: string;
  meta: string;
  occurred_at: string;
};

export type DataHubJobScopeStatus = {
  scope: string;
  label?: string | null;
  last_run_at?: string | null;
  last_run_status?: string | null;
  last_run_trigger?: string | null;
  last_success_at?: string | null;
  data_as_of?: string | null;
  consecutive_failures: number;
  last_error?: string | null;
};

// One data source's job status from job_runs (#156).
export type DataHubJobState = "ok" | "warning" | "failing" | "never_run" | "not_configured";

export type DataHubJobStatus = {
  job: string;
  label: string;
  state: DataHubJobState | string;
  failure_threshold: number;
  last_run_at?: string | null;
  last_run_status?: string | null;
  last_success_at?: string | null;
  data_as_of?: string | null;
  consecutive_failures: number;
  last_error?: string | null;
  scopes: DataHubJobScopeStatus[];
};

// A held stock or fund with no live price (#222): not linked to an asset,
// no ticker on a configured exchange, or never quoted.
export type DataHubUnpricedHolding = {
  symbol?: string | null;
  name?: string | null;
  currency?: string | null;
  exchange_code?: string | null;
  platform?: string | null;
  reason: "no_asset" | "no_symbol" | "no_quote" | string;
};

// Source freshness (#252, D-67): one row per data source (/dashboard/source-freshness).
export type SourceFreshnessKind =
  | "ibkr_flex"
  | "broker_statement"
  | "bank_statement"
  | "card_statement"
  | "account_statement"
  | "crypto_wallet"
  | "market_data"
  | "fx";

export type SourceFreshnessCadence = "daily" | "weekdays" | "weekly" | "monthly" | "quarterly" | "off";

export type SourceFreshnessStatus = "on_time" | "overdue" | "never_loaded" | "no_schedule";

export type SourceFreshnessRow = {
  source_key: string;
  kind: SourceFreshnessKind | string;
  label: string;
  platform?: string | null;
  /** ISO date of the newest data, or null when the source has never loaded. */
  last_data_date?: string | null;
  cadence: SourceFreshnessCadence | string;
  /** Business days for "weekdays", calendar days otherwise. */
  grace_days: number;
  default_cadence: SourceFreshnessCadence | string;
  default_grace_days: number;
  overridden: boolean;
  /** The last day the newest data is on time. */
  due_date?: string | null;
  status: SourceFreshnessStatus | string;
  /** True for overdue and never-loaded sources. */
  overdue: boolean;
  days_overdue?: number | null;
};

export type SourceFreshness = {
  as_of: string;
  overdue_count: number;
  cadences: string[];
  sources: SourceFreshnessRow[];
};

/** The Data Hub inbox (#316): one item that needs the user, with its action. */
export type InboxAction = {
  label: string;
  /** A page to open, with `params` as its query string. */
  route: string | null;
  params: Record<string, string>;
  /** A refresh the page runs in place. */
  run: "refresh_prices" | "fx_backfill" | "refresh_ibkr" | "refresh_crypto" | null;
  /** Writes shared data (#152): only an admin gets the button. */
  admin_only: boolean;
};

export type InboxItem = {
  id: string;
  kind:
    | "source_overdue"
    | "source_never_loaded"
    | "unknown_format"
    | "import_pending"
    | "unpriced_holding"
    | "fx_gap"
    | "fx_unsupported"
    | "job_failing"
    | "unmapped_transactions"
    | string;
  severity: "high" | "medium" | "low";
  title: string;
  detail: string | null;
  action: InboxAction | null;
  /** The source-freshness row, for the source kinds (prefilled Upload link, #278). */
  source: SourceFreshnessRow | null;
};

export type InboxResponse = {
  as_of: string;
  count: number;
  items: InboxItem[];
  all_good: string[];
  recent_activity: DataHubActivityItem[];
};

export type DataHubSummary = {
  linked_accounts: number;
  platform_count: number;
  currency_count: number;
  import_health: {
    pending_count: number;
    last_import_platform?: string | null;
    last_import_at?: string | null;
  };
  market_data: {
    fresh: number;
    stale: number;
    // Held stocks/funds the quote refresh can't price (#222).
    unpriced?: number;
    unpriced_holdings?: DataHubUnpricedHolding[];
  };
  connected_wallet_count: number;
  connected_wallet_labels: string[];
  recent_activity: DataHubActivityItem[];
  job_status: DataHubJobStatus[];
};

export type UploadReminder = {
  account_id: number;
  account_name: string;
  platform: string;
  account_type: string;
  last_upload_date: string | null;
  last_transaction_date: string | null;
  days_since_upload: number;
  message: string;
};

export type UploadReminderCount = {
  count: number;
};

export type UnifiedAlertsResponse = {
  upload_reminders: UploadReminder[];
  total_count: number;
};

/** GET /alerts/notifications/count (#149): /alerts/notifications' total_count only. */
export type UnifiedAlertsCount = {
  total_count: number;
};

export type DividendTotals = {
  gross: number;
  withholding: number;
  net_received: number;
  estimated_tax: number;
  payout_minus_tax: number;
};

export type DividendSummaryBucket = DividendTotals & {
  bucket: string;
};

/** Dividends (net of withholding) plus interest over [from_date, to_date], inclusive (#267). */
export type IncomeWindow = {
  from_date: string;
  to_date: string;
  dividends: number;
  interest: number;
  total: number;
};

export type IncomeMonth = {
  month: string;
  dividends: number;
  interest: number;
  total: number;
};

/** GET /income/summary (#267): trailing 12 months and year to date, each vs a year earlier. */
export type IncomeSummary = FxStatus & {
  month: string;
  base_currency: string;
  as_of: string;
  partial_month: boolean;
  trailing_12: IncomeWindow;
  prior_12: IncomeWindow;
  trailing_12_change_pct: number | null;
  ytd: IncomeWindow;
  prior_ytd: IncomeWindow;
  ytd_change_pct: number | null;
  months: IncomeMonth[];
};

export type DividendsSummary = FxStatus & {
  from_month: string;
  to_month: string;
  current_net_worth_as_of?: string | null;
  current_net_worth?: NetWorthBreakdown | null;
  current_net_worth_freshness?: NetWorthFreshness | null;
  period: "month" | "quarter" | "year";
  base_currency: string;
  assumed_tax_rate: number;
  country_tax_rates: Record<string, number>;
  buckets: DividendSummaryBucket[];
  totals?: DividendTotals;
  net_worth?: NetWorthBreakdown;
  country?: string | null;
  yield_pct?: number | null;
};

export type DividendCompanyItem = {
  asset_id: number | null;
  symbol: string | null;
  company: string;
  country: string | null;
  gross: number;
  withholding: number;
  net_received: number;
  estimated_tax: number;
  payout_minus_tax: number;
  yield_pct: number | null;
};

export type DividendsByCompany = FxStatus & {
  from_month: string;
  to_month: string;
  base_currency: string;
  assumed_tax_rate: number;
  country_tax_rates: Record<string, number>;
  items: DividendCompanyItem[];
  totals: DividendTotals;
};

export type DividendHistoryEvent = DividendTotals & {
  month: string;
};

export type DividendHistory = FxStatus & {
  from_month: string;
  to_month: string;
  base_currency: string;
  assumed_tax_rate: number;
  country_tax_rates: Record<string, number>;
  asset_id: number | null;
  symbol: string | null;
  company: string | null;
  yield_pct: number | null;
  events: DividendHistoryEvent[];
  totals: DividendTotals;
};

export type ExpectedDividendBucket = {
  bucket: string;
  gross: number;
  estimated_tax: number;
  payout_minus_tax: number;
};

export type ExpectedDividendSummary = {
  period: "month" | "quarter" | "year";
  buckets: ExpectedDividendBucket[];
  gross: number;
  estimated_tax: number;
  payout_minus_tax: number;
};

export type ExpectedDividendCompany = {
  asset_id: number;
  symbol: string;
  company: string;
  country: string | null;
  shares: number;
  yield_pct: number | null;
  price: number | null;
  quote_currency: string | null;
  yearly_dividend: number;
  quarterly_dividend: number;
  monthly_dividend: number;
  gross: number;
  estimated_tax: number;
  payout_minus_tax: number;
};

export type ExpectedDividendsOverview = {
  from_month: string;
  to_month: string;
  base_currency: string;
  assumed_tax_rate: number;
  country_tax_rates: Record<string, number>;
  holdings_considered: number;
  assets_with_actions: number;
  actions_evaluated: number;
  monthly: ExpectedDividendSummary;
  quarterly: ExpectedDividendSummary;
  yearly: ExpectedDividendSummary;
  companies: ExpectedDividendCompany[];
};

export type RealtimeEventEnvelope<TPayload = Record<string, unknown>> = {
  id: string;
  topic: string;
  event_name: string;
  batch_id?: string | null;
  author_id?: string | null;
  source_id?: string | null;
  job_id?: string | null;
  status?: string | null;
  created_at?: string | null;
  payload: TPayload;
};

export const api = {
  health: () => req<Health>("/health"),
  /** Returns true when there is an in-memory access token (user is logged in). */
  isAuthenticated: (): boolean => Boolean(accessTokenMemory),
  authSignup: (payload: { username: string; password: string; display_name?: string }) =>
    req<AuthMe>("/auth/signup", { method: "POST", body: JSON.stringify(payload) }, { skipAuth: true }),
  authLogin: (payload: { username: string; password: string }) =>
    req<AuthSession>("/auth/login", { method: "POST", body: JSON.stringify(payload) }, { skipAuth: true }),
  authRefresh: () =>
    req<AuthSession>("/auth/refresh", { method: "POST" }, { skipAuth: true, skipRefreshRetry: true }),
  authMe: () => req<AuthMe>("/auth/me"),
  authLogout: () => req<{ status: string }>("/auth/logout", { method: "POST" }),
  changePassword: (payload: { current_password: string; new_password: string }) =>
    req<ChangePasswordResult>("/auth/change-password", { method: "POST", body: JSON.stringify(payload) }),
  getPreferences: () => req<UserPreferences>("/auth/preferences"),
  patchPreferences: (patch: UserPreferencesPatch) =>
    req<UserPreferences>("/auth/preferences", { method: "PATCH", body: JSON.stringify(patch) }),
  dashboardBootstrap: (month: string, baseCurrency = "SGD") =>
    req<DashboardBootstrap>(`/dashboard/bootstrap?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  dashboardNetWorthChange: (month: string, baseCurrency = "SGD", compare = "prev_month,prev_year") =>
    req<DashboardNetWorthChange>(`/dashboard/net-worth-change?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}&compare=${encodeURIComponent(compare)}`),
  netWorthTimeline: (months: number, baseCurrency = "SGD") =>
    req<WealthTimeline>(`/dashboard/net-worth-timeline?months=${encodeURIComponent(String(months))}&base_currency=${encodeURIComponent(baseCurrency)}`),
  netWorthTimelineBackfill: (months: number, baseCurrency = "SGD") =>
    req<WealthTimelineBackfillResult>(
      `/dashboard/net-worth-timeline/backfill?months=${encodeURIComponent(String(months))}&base_currency=${encodeURIComponent(baseCurrency)}`,
      { method: "POST" },
    ),
  /** Starts "Generate history" in the background (#292); no `months` = the span of your data. */
  netWorthTimelineGenerate: (baseCurrency = "SGD", months?: number) =>
    req<HistoryGenerateStatus>(
      `/dashboard/net-worth-timeline/generate?base_currency=${encodeURIComponent(baseCurrency)}${
        months == null ? "" : `&months=${encodeURIComponent(String(months))}`
      }`,
      { method: "POST" },
    ),
  netWorthTimelineGenerateStatus: (baseCurrency = "SGD") =>
    req<HistoryGenerateStatus>(
      `/dashboard/net-worth-timeline/generate/status?base_currency=${encodeURIComponent(baseCurrency)}`,
    ),
  netWorthTimelineMovers: (month: string, baseCurrency = "SGD", limit = 5) =>
    req<WealthTopMovers>(
      `/dashboard/net-worth-timeline/${encodeURIComponent(month)}/movers?base_currency=${encodeURIComponent(baseCurrency)}&limit=${encodeURIComponent(String(limit))}`,
    ),
  categories: () => req<CategoryTaxonomy[]>("/categories"),
  unmappedTransactions: (month: string, accountId?: number) =>
    req<UnmappedTransaction[]>(
      `/categories/unmapped?month=${encodeURIComponent(month)}${
        accountId == null ? "" : `&account_id=${encodeURIComponent(String(accountId))}`
      }`
    ),
  categoryOverride: (payload: CategoryOverridePayload) =>
    req<CategoryResolution>("/categories/override", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  categoryOverrideBulk: (payload: CategoryOverrideBulkPayload) =>
    req<CategoryOverrideBulkResult>("/categories/override-bulk", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  platforms: () => req<Platform[]>("/platforms"),
  platformOptions: () => req<PlatformOptions>("/platforms/options"),
  createPlatform: (payload: PlatformCreate) =>
    req<Platform>("/platforms", { method: "POST", body: JSON.stringify(payload) }),
  accounts: () => req<Account[]>("/accounts"),
  accountOptions: () => req<AccountOptions>("/accounts/options"),
  createAccount: (payload: AccountCreate) =>
    req<Account>("/accounts", { method: "POST", body: JSON.stringify(payload) }),
  updateAccount: (id: number, patch: AccountUpdate) =>
    req<Account>(`/accounts/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  currencies: () => req<Currency[]>("/currencies"),
  createCurrency: (payload: CurrencyCreate) =>
    req<Currency>("/currencies", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  dashboardSummary: (month: string, compare?: string, baseCurrency = "SGD", skipNetworth = false) =>
  req<DashboardSummary>(`/dashboard/summary?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}${compare ? `&compare=${encodeURIComponent(compare)}` : ""}${skipNetworth ? "&skip_networth=true" : ""}`),
  riskSummary: (month: string, baseCurrency = "SGD") =>
    req<RiskSummary>(`/dashboard/risk-summary?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  riskThresholds: () => req<RiskThresholdsSetting>("/dashboard/risk-thresholds"),
  saveRiskThresholds: (payload: RiskThresholdsSetting) =>
    req<RiskThresholdsSetting>("/dashboard/risk-thresholds", { method: "PUT", body: JSON.stringify(payload) }),
  monthBridge: (month: string, baseCurrency = "SGD") =>
    req<MonthBridge>(`/dashboard/month-bridge?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  realisedPnl: (month: string, baseCurrency = "SGD", period?: RealisedPeriodQuery) => {
    const params = new URLSearchParams({ month, base_currency: baseCurrency });
    if (period) {
      params.set("period", period.period);
      if (period.year != null) params.set("year", String(period.year));
      if (period.from) params.set("from", period.from);
      if (period.to) params.set("to", period.to);
    }
    return req<RealisedPnl>(`/dashboard/realised-pnl?${params.toString()}`);
  },
  stockHoldingsSummary: (month: string, baseCurrency = "SGD") =>
    req<StockHoldingsSummary>(`/dashboard/stock-holdings?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  netWorthSinceUpdate: (baseCurrency = "SGD") =>
    req<NetWorthSinceUpdate>(`/dashboard/net-worth-since-update?base_currency=${encodeURIComponent(baseCurrency)}`),
  dataHubSummary: () => req<DataHubSummary>("/dashboard/data-hub-summary"),
  operationsInbox: () => req<InboxResponse>("/operations/inbox"),
  sourceFreshness: () => req<SourceFreshness>("/dashboard/source-freshness"),
  setSourceFreshnessCadence: (sourceKey: string, body: { cadence: string; grace_days: number }) =>
    req<SourceFreshnessRow>(`/dashboard/source-freshness/${encodeURIComponent(sourceKey)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  resetSourceFreshnessCadence: (sourceKey: string) =>
    req<SourceFreshnessRow>(`/dashboard/source-freshness/${encodeURIComponent(sourceKey)}`, { method: "DELETE" }),
  cashDeposits: (month: string, baseCurrency = "SGD") =>
    req<CashDeposits>(`/dashboard/cash-deposits?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  platformAllocation: (month: string, baseCurrency = "SGD") =>
    req<PlatformAllocation>(`/dashboard/platform-allocation?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  dashboardGeographyExposure: (month: string, baseCurrency = "SGD") =>
    req<GeographyExposure>(`/dashboard/geography-exposure?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  stockExposure: (month: string, baseCurrency = "SGD") =>
    req<StockExposure>(`/dashboard/stock-exposure?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  spendingSummary: (month: string, baseCurrency = "SGD") =>
    req<SpendingSummary>(`/spending/summary?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  cashFlowDetail: (month: string, baseCurrency = "SGD") =>
    req<CashFlowDetail>(`/spending/cash-flow-detail?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  cashFlowTrend: (month: string, baseCurrency = "SGD") =>
    req<CashFlowTrend>(`/spending/cash-flow-trend?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  creditCardSummary: (month: string, baseCurrency = "SGD") =>
    req<CreditCardSummary>(`/spending/credit-cards?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  creditCardTransactions: (month: string, baseCurrency = "SGD") =>
    req<CreditCardDetail>(`/spending/credit-card-transactions?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  creditCardBalances: (baseCurrency = "SGD") =>
    req<CreditCardBalances>(`/spending/credit-card-balances?base_currency=${encodeURIComponent(baseCurrency)}`),
  // A statement balance typed in by hand (#300), for a card whose files state none.
  setCreditCardBalance: (accountId: number, payload: { as_of_date: string; owed: number }, baseCurrency = "SGD") =>
    req<CreditCardBalances>(
      `/spending/credit-card-balances/${encodeURIComponent(String(accountId))}?base_currency=${encodeURIComponent(baseCurrency)}`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  creditCardAnalytics: (month: string, baseCurrency = "SGD", months = 12, accountId?: number | null) =>
    req<CreditCardAnalytics>(
      `/spending/credit-card-analytics?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}&months=${encodeURIComponent(String(months))}${
        accountId != null ? `&account_id=${encodeURIComponent(String(accountId))}` : ""
      }`,
    ),
  // asOf (YYYY-MM-DD): the statement's date, used when the file states none of its own (#141).
  // A refused upload throws UploadRefusedError (#180); allowAccountMismatch uploads a
  // statement that names another account anyway.
  ingestUpload: async (accountId: number, file: File, asOf?: string, opts?: { allowAccountMismatch?: boolean }) => {
    const form = new FormData();
    form.append("file", file);
    if (asOf) form.append("as_of", asOf);
    if (opts?.allowAccountMismatch) form.append("allow_account_mismatch", "true");
    const headers = buildHeaders(undefined, { includeJsonContentType: false });
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/ingest/upload?account_id=${accountId}`, {
        method: "POST",
        credentials: "include",
        headers,
        body: form,
      });
    } catch (err: unknown) {
      const reason = err instanceof Error ? err.message : String(err);
      throw new Error(`Unable to reach API at ${API_BASE}: ${reason}`, { cause: err });
    }
    if (!res.ok) {
      const text = await res.text();
      const refusal = uploadRefusalFrom(res.status, text);
      if (refusal) throw new UploadRefusedError(refusal);
      throw new Error(formatHttpError(res.status, text));
    }
    return res.json() as Promise<Record<string, unknown>>;
  },
  ingestIbkr: async (accountId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const headers = buildHeaders(undefined, { includeJsonContentType: false });
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/ingest/ibkr?account_id=${accountId}`, {
        method: "POST",
        credentials: "include",
        headers,
        body: form,
      });
    } catch (err: unknown) {
      const reason = err instanceof Error ? err.message : String(err);
      throw new Error(`Unable to reach API at ${API_BASE}: ${reason}`, { cause: err });
    }
    if (!res.ok) {
      const text = await res.text();
      throw new Error(formatHttpError(res.status, text));
    }
    return res.json() as Promise<Record<string, unknown>>;
  },
  ingestJobs: () => req<ImportJobListItem[]>("/ingest/jobs"),
  ingestJob: (jobId: number) => req<ImportJobDetail>(`/ingest/jobs/${jobId}`),
  registerIngestSignature: (jobId: number, parserKey: string, asOf?: string) =>
    req<Record<string, unknown>>(`/ingest/jobs/${jobId}/register`, {
      method: "POST",
      body: JSON.stringify(asOf ? { parser_key: parserKey, as_of: asOf } : { parser_key: parserKey }),
    }),
  // "Remove this import" (#180): deletes the rows the upload wrote; the job stays as REMOVED.
  removeIngestJob: (jobId: number) =>
    req<ImportJobRemoval>(`/ingest/jobs/${jobId}/remove`, { method: "POST" }),
  cryptoWallets: () => req<CryptoWallet[]>("/crypto/wallets"),
  cryptoWalletInit: (payload: { chain_type: string; chain: string; address: string; label?: string }) =>
    req<CryptoWalletInitResponse>("/crypto/wallets/init", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  cryptoWalletVerify: (payload: { chain_type: string; chain: string; address: string; signature: string; public_key?: string; verification_id?: number }) =>
    req<{ wallet_id: string; status: string }>("/crypto/wallets/verify", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  cryptoWalletVerifyOnchain: (payload: { address: string; signature: string; verification_id: number }) =>
    req<{ wallet_id: string; status: string }>("/crypto/wallets/verify-onchain", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  solanaBlockhash: () => req<{ blockhash: string }>("/crypto/solana/blockhash"),
  solanaSubmit: (payload: { tx_b64: string }) =>
    req<{ signature: string }>("/crypto/solana/submit", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  solanaPreflight: (payload: { tx_b64: string }) =>
    req<{ ok: boolean }>("/crypto/solana/preflight", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  cryptoSummary: (month?: string, baseCurrency = "USD") =>
    req<CryptoSummary>(`/crypto/summary?base_currency=${encodeURIComponent(baseCurrency)}${month ? `&month=${encodeURIComponent(month)}` : ""}`),
  cryptoStablecoins: (month?: string, baseCurrency = "USD") =>
    req<CryptoStablecoins>(`/crypto/stablecoins?base_currency=${encodeURIComponent(baseCurrency)}${month ? `&month=${encodeURIComponent(month)}` : ""}`),
  cryptoRefreshNow: (adminKey?: string) =>
    req<Record<string, unknown>>("/crypto/refresh-now", {
      method: "POST",
      headers: adminKey ? { "X-Admin-Key": adminKey } : undefined,
    }),
  cryptoAllowlist: () => req<CryptoAllowlistItem[]>("/crypto/allowlist"),
  /** #342: show ("Not spam"), hide, or reset (null) one wallet token for this user. */
  cryptoSetTokenVisibility: (payload: { chain: string; contract_or_mint: string; visibility: TokenVisibility | null }) =>
    req<{ overrides: TokenVisibilityOverride[] }>("/crypto/token-visibility", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  cryptoAllowlistAdd: (payload: { chain: string; contract_address: string }) =>
    req<CryptoAllowlistItem>("/crypto/allowlist", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  marketDataStatus: () => req<{ status: MarketDataExchangeStatus[] }>("/market-data/status"),
  marketDataRuns: (limit = 50) =>
    req<{ runs: MarketDataRun[] }>(`/market-data/runs?limit=${encodeURIComponent(String(limit))}`),
  fxBackfillPlan: (baseCurrency: string) =>
    req<FxBackfillPlan>(`/fx/backfill-plan?base_currency=${encodeURIComponent(baseCurrency)}`),
  fxBackfill: (baseCurrency: string) =>
    req<FxBackfillResult>(`/fx/backfill?base_currency=${encodeURIComponent(baseCurrency)}`, { method: "POST" }),
  marketDataRefreshNow: (adminKey?: string, exchange?: string) =>
    req<{ status: string; exchanges: Array<Record<string, unknown>> }>(
      `/market-data/refresh-now${exchange ? `?exchange=${encodeURIComponent(exchange)}` : ""}`,
      {
        method: "POST",
        headers: adminKey ? { "X-Admin-Key": adminKey } : undefined,
      },
    ),
  marketDataUnpriced: () => req<MarketDataUnpriced>("/market-data/unpriced"),
  marketDataTickerTest: (yahooSymbol: string, exchangeCode?: string | null) =>
    req<MarketDataTickerTest>("/market-data/ticker-test", {
      method: "POST",
      body: JSON.stringify({ yahoo_symbol: yahooSymbol, exchange_code: exchangeCode ?? null }),
    }),
  marketDataSetTicker: (assetId: number, exchangeCode: string, yahooSymbol: string) =>
    req<MarketDataTickerSet>("/market-data/ticker", {
      method: "POST",
      body: JSON.stringify({ asset_id: assetId, exchange_code: exchangeCode, yahoo_symbol: yahooSymbol }),
    }),
  ibkrFlexImportNow: (accountId: number, adminKey?: string) =>
    req<Record<string, unknown>>(`/portfolio/ibkr-flex/import-now?account_id=${encodeURIComponent(String(accountId))}`, {
      method: "POST",
      headers: adminKey ? { "X-Admin-Key": adminKey } : undefined,
    }),
  uploadReminders: (month?: string) =>
    req<UploadReminder[]>(`/alerts/upload-reminders${month ? `?month=${encodeURIComponent(month)}` : ""}`),
  uploadReminderCount: (month?: string) =>
    req<UploadReminderCount>(`/alerts/upload-reminders/count${month ? `?month=${encodeURIComponent(month)}` : ""}`),
  alertNotifications: (month?: string) =>
    req<UnifiedAlertsResponse>(`/alerts/notifications${month ? `?month=${encodeURIComponent(month)}` : ""}`),
  alertNotificationsCount: (month?: string) =>
    req<UnifiedAlertsCount>(`/alerts/notifications/count${month ? `?month=${encodeURIComponent(month)}` : ""}`),
  incomeSummary: (month: string, baseCurrency = "SGD") =>
    req<IncomeSummary>(
      `/income/summary?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`,
    ),
  dividendsSummary: (
    fromMonth: string,
    toMonth: string,
    period: "month" | "quarter" | "year",
    baseCurrency = "SGD",
    assumedTaxRate = 0,
    countryTaxRates?: string,
  ) =>
    req<DividendsSummary>(
      `/dividends/summary?from_month=${encodeURIComponent(fromMonth)}&to_month=${encodeURIComponent(toMonth)}&period=${encodeURIComponent(period)}&base_currency=${encodeURIComponent(baseCurrency)}&assumed_tax_rate=${encodeURIComponent(String(assumedTaxRate))}${countryTaxRates ? `&country_tax_rates=${encodeURIComponent(countryTaxRates)}` : ""}`
    ),
  dividendsByCompany: (
    fromMonth: string,
    toMonth: string,
    baseCurrency = "SGD",
    assumedTaxRate = 0,
    countryTaxRates?: string,
  ) =>
    req<DividendsByCompany>(
      `/dividends/by-company?from_month=${encodeURIComponent(fromMonth)}&to_month=${encodeURIComponent(toMonth)}&base_currency=${encodeURIComponent(baseCurrency)}&assumed_tax_rate=${encodeURIComponent(String(assumedTaxRate))}${countryTaxRates ? `&country_tax_rates=${encodeURIComponent(countryTaxRates)}` : ""}`
    ),
  dividendsHistory: (
    assetId: number,
    fromMonth: string,
    toMonth: string,
    baseCurrency = "SGD",
    assumedTaxRate = 0,
    countryTaxRates?: string,
  ) =>
    req<DividendHistory>(
      `/dividends/history?asset_id=${encodeURIComponent(String(assetId))}&from_month=${encodeURIComponent(fromMonth)}&to_month=${encodeURIComponent(toMonth)}&base_currency=${encodeURIComponent(baseCurrency)}&assumed_tax_rate=${encodeURIComponent(String(assumedTaxRate))}${countryTaxRates ? `&country_tax_rates=${encodeURIComponent(countryTaxRates)}` : ""}`
    ),
  expectedDividendsOverview: (
    fromMonth: string,
    toMonth: string,
    baseCurrency = "SGD",
    assumedTaxRate = 0,
    countryTaxRates?: string,
  ) =>
    req<ExpectedDividendsOverview>(
      `/dividends/expected/overview?from_month=${encodeURIComponent(fromMonth)}&to_month=${encodeURIComponent(toMonth)}&base_currency=${encodeURIComponent(baseCurrency)}&assumed_tax_rate=${encodeURIComponent(String(assumedTaxRate))}${countryTaxRates ? `&country_tax_rates=${encodeURIComponent(countryTaxRates)}` : ""}`
    ),
};
