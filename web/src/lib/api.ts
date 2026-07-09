export function resolveApiBase(
  rawApiBase?: string,
  locationLike?: { protocol?: string; hostname?: string } | null,
): string {
  const explicit = rawApiBase?.trim();
  if (explicit) {
    return explicit.replace(/\/+$/, "");
  }

  const currentLocation =
    locationLike ?? (typeof window !== "undefined" ? window.location : null);
  const hostname = currentLocation?.hostname?.trim();
  const protocol = currentLocation?.protocol === "https:" ? "https:" : "http:";
  if (hostname) {
    return `${protocol}//${hostname}:8000`;
  }
  return "http://localhost:8000";
}

const RAW_API_BASE = import.meta.env.VITE_API_BASE as string | undefined;
const API_BASE = resolveApiBase(RAW_API_BASE);
let accessTokenMemory: string | null = null;
let refreshInFlight: Promise<string | null> | null = null;
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

async function callRefreshEndpoint(): Promise<string | null> {
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
    const payload = (await res.json()) as AuthToken;
    if (!payload?.access_token) {
      setAccessToken(null);
      notifyAuthFailure();
      return null;
    }
    setAccessToken(payload.access_token);
    return payload.access_token;
  } catch {
    // Network/transport error: treat as transient. Do not force logout.
    return null;
  }
}

async function refreshAccessToken(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = callRefreshEndpoint().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

export async function refreshAccessTokenNow(): Promise<string | null> {
  return refreshAccessToken();
}

async function req<T>(path: string, init?: RequestInit, opts: RequestOptions = {}): Promise<T> {
  const execute = async (): Promise<Response> => {
    try {
      const { headers: initHeaders, ...restInit } = init ?? {};
      return await fetch(`${API_BASE}${path}`, {
        credentials: "include",
        ...restInit,
        headers: buildHeaders(initHeaders, { includeJsonContentType: true, skipAuth: opts.skipAuth }),
      });
    } catch (err: unknown) {
      const reason = err instanceof Error ? err.message : String(err);
      throw new Error(`Unable to reach API at ${API_BASE}: ${reason}`);
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

export type Account = {
  id: number;
  name: string;
  platform: string;      // legacy text column (DBS, IBKR, etc.)
  platform_id?: number | null;
  account_type: string;  // BANK | BROKER | EXCHANGE | WALLET | CREDIT_CARD | LOAN | MUTUAL_FUND
  currency: string;
  country?: string | null;
};

export type DashboardSummary = {
  as_of_month: string;
  base_currency: string;
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
    price_provider?: string | null;
    quote_freshness_status?: string | null;
  }>;
  cash_balances?: Array<{
    currency: string;
    value: number;
  }>;
  snapshot_day: number | null;
  net_worth_as_of: string | null;
  net_worth_change: null | {
    vs_prev_month?: {
      abs: number;
      pct: number | null;
      current_as_of: string | null;
      compare_as_of: string | null;
      compare_month: string;
    };
    vs_prev_year?: {
      abs: number;
      pct: number | null;
      current_as_of: string | null;
      compare_as_of: string | null;
      compare_month: string;
    };
  };
  net_worth_component_change?: null | {
    cash?: {
      abs: number;
      pct: number | null;
      current_as_of: string | null;
      compare_as_of: string | null;
      compare_month: string;
    };
    stocks_funds?: {
      abs: number;
      pct: number | null;
      current_as_of: string | null;
      compare_as_of: string | null;
      compare_month: string;
    };
    crypto?: {
      abs: number;
      pct: number | null;
      current_as_of: string | null;
      compare_as_of: string | null;
      compare_month: string;
    };
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

export type StockHoldingsSummary = {
  as_of_month: string;
  base_currency: string;
  snapshot_day: number | null;
  current_holdings_as_of?: string | null;
  net_worth_as_of: string | null;
  net_worth_snapshot_as_of?: string | null;
  net_worth_boundary_at?: string | null;
  net_worth_boundary_exact?: boolean | null;
  net_worth_freshness_status?: string | null;
  top_holdings: DashboardSummary["top_holdings"];
  geography_breakdown?: Array<{
    geography: string;
    current_value: number;
    snapshot_value: number;
    delta_abs: number;
    delta_pct?: number | null;
  }>;
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
  quote_freshness_summary?: {
    fresh: number;
    stale: number;
    missing: number;
  } | null;
  trend?: Array<{
    month: string;
    value?: number | null;
  }>;
};

export type SpendingSummary = {
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
};

export type CashFlowDiagnosticAnswer = {
  question: string;
  answer: string;
};

export type CashFlowAnalytics = {
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
};

export type CashFlowDetail = {
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

export type CreditCardSummary = {
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
};

export type CreditCardDetail = {
  month: string;
  base_currency: string;
  total_spend: number;
  cards: CreditCardSummary["cards"];
  transactions: CreditCardTransaction[];
  top_purchases: CreditCardTransaction[];
  recurring_payments: CreditCardRecurringPayment[];
};

export type ImportJobListItem = {
  id: number;
  status: string;
  platform: string;
  account_id: number;
  original_filename: string;
  created_at: string | null;
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
  current_cash_as_of?: string | null;
  snapshot_cash_as_of?: string | null;
  current_total?: number | null;
  snapshot_total?: number | null;
  delta_abs?: number | null;
  delta_pct?: number | null;
  trend?: Array<{
    month: string;
    value?: number | null;
  }>;
  currency_breakdown?: Array<{
    currency: string;
    current_value: number;
    snapshot_value: number;
    delta_abs: number;
    delta_pct?: number | null;
  }>;
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

export type CryptoSummary = {
  month?: string;
  snapshot_day?: number | null;
  snapshot_as_of?: string | null;
  total_crypto_usd: number;
  total_crypto_base: number;
  snapshot_total_base?: number;
  snapshot_total_usd?: number;
  snapshot_delta_base?: number;
  snapshot_delta_pct?: number | null;
  base_currency: string;
  eth_exposure_usd?: number;
  eth_exposure_base?: number;
  token_exposure_usd?: number;
  token_exposure_base?: number;
  token_count?: number;
  priced_token_count?: number;
  trend?: Array<{
    month: string;
    value?: number | null;
  }>;
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
  }>;
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

export type CategoryResolution = {
  transaction_id: number;
  raw_category: string | null;
  override_category: string | null;
  resolved_category: string;
  source: string;
  rule_id: number | null;
  rule_name: string | null;
};

export type Health = { status: string };

export type NetWorthBreakdown = {
  total: number;
  cash: number;
  stocks_funds: number;
  crypto: number;
  liabilities: number;
};

export type NetWorthFreshness = {
  positions_as_of?: string | null;
  market_data_as_of?: string | null;
  crypto_as_of?: string | null;
  crypto_holdings_as_of?: string | null;
  crypto_price_as_of?: string | null;
};

export type DashboardBootstrap = {
  as_of_month: string;
  base_currency: string;
  snapshot_day: number | null;
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
  attempt_status?: string | null;
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
  };
  connected_wallet_count: number;
  connected_wallet_labels: string[];
  recent_activity: DataHubActivityItem[];
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

export type SystemNotification = {
  id: string;
  alert_type: "system_notification";
  topic: string;
  event_name: string;
  author_id: string | null;
  source_id: string | null;
  job_id: string | null;
  batch_id: string | null;
  status: string | null;
  message: string;
  created_at: string;
  payload: Record<string, unknown>;
};

export type UnifiedAlertsResponse = {
  upload_reminders: UploadReminder[];
  system_notifications: SystemNotification[];
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

export type DividendsSummary = {
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

export type DividendsByCompany = {
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

export type DividendHistory = {
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

export type RagAuthor = {
  id: string;
  name: string;
  enabled: boolean;
  domains: string[];
  expertise_tags: string[];
  overall_weight: number;
  role_type: string | null;
};

export type RagSourceRecord = {
  id: string;
  author_id: string;
  author_name?: string | null;
  url: string | null;
  source_type: string;
  status: string;
  hash: string | null;
  selective_options?: SelectiveIngestionOptions | null;
  ingestion_config?: Record<string, unknown> | null;
  last_ingested_at: string | null;
  created_at: string;
};

export type RagIngestionJobRecord = {
  id: string;
  source_id: string;
  batch_id?: string | null;
  status: string;
  failure_category: string | null;
  error: string | null;
  stats_json: Record<string, unknown>;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
};

export type SelectiveIngestionOptions = {
  start_after?: string | null;
  stop_before?: string | null;
  include_headings?: string[];
  exclude_sections?: string[];
};

export type RagLogicalDocumentConfigInput = {
  key: string;
  title: string;
  author_id?: string | null;
  published_at?: string | null;
  publication_year?: number | null;
  venue?: string | null;
  collection?: string | null;
  canonical_work_id?: string | null;
  canonical_status?: string | null;
  canonical_metadata?: Record<string, string>;
  dedupe_priority?: number | null;
  source_section?: string | null;
  note_taker?: string | null;
  work_type?: string | null;
  parent_key?: string | null;
  metadata?: Record<string, string>;
  selective_ingestion?: SelectiveIngestionOptions | null;
};

export type RagIngestionConfigInput = {
  mode: "single_work" | "fanout";
  documents: RagLogicalDocumentConfigInput[];
};

export type RagLogicalDocumentPreview = {
  key: string;
  title: string | null;
  author_id: string | null;
  published_at: string | null;
  publication_year: number | null;
  venue: string | null;
  collection: string | null;
  canonical_work_id: string | null;
  canonical_status: string | null;
  dedupe_priority: number | null;
  source_section: string | null;
  note_taker: string | null;
  work_type: string | null;
  parent_key: string | null;
  metadata: Record<string, unknown>;
  selective_ingestion: Record<string, unknown>;
};

export type RagFanoutPreview = {
  mode: string;
  document_count: number;
  documents: RagLogicalDocumentPreview[];
};

export type IngestUrlsBatchResult = {
  author_id: string;
  registered: number;
  requeued_existing?: number;
  skipped_duplicate: number;
  jobs_queued: number;
  sources: RagSourceRecord[];
  job_ids: string[];
};

export type RagAuthorCreate = {
  id: string;
  name: string;
  enabled: boolean;
  domains?: string[];
  expertise_tags?: string[];
  overall_weight?: number;
  role_type?: string | null;
};

export type RagIngestionAuthorSummary = {
  id: string;
  name: string;
};

export type RagIngestionBatchSummary = {
  id: string | null;
  status: string;
  source_count?: number;
  completed_source_count?: number;
  failed_source_count?: number;
};

export type RagAuthorIngestionEventPayload = {
  author?: RagIngestionAuthorSummary;
  batch?: RagIngestionBatchSummary;
  source?: RagSourceRecord;
  job?: RagIngestionJobRecord;
  failure_reason?: string | null;
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

export type RagIngestionActivity = {
  topic: string;
  sources: RagSourceRecord[];
  jobs: RagIngestionJobRecord[];
  events: RealtimeEventEnvelope<RagAuthorIngestionEventPayload>[];
};

export type RagLibraryAuthor = {
  id: string;
  name: string;
  document_count: number;
  source_count: number;
  collections: string[];
  work_types: string[];
  latest_document_at: string | null;
  photo_url: string | null;
  about_text: string | null;
};

export type RagLibraryDocumentSummary = {
  id: string;
  source_id: string;
  title: string;
  author_id: string | null;
  author_name: string | null;
  published_at: string | null;
  publication_year: number | null;
  publication_label: string | null;
  venue: string | null;
  collection: string | null;
  canonical_work_id: string | null;
  canonical_status: string | null;
  source_type: string;
  source_url: string | null;
  work_type: string | null;
  source_section: string | null;
  metadata: Record<string, unknown>;
  char_count: number;
  parent_document_id: string | null;
  parent_title: string | null;
  child_count: number;
};

export type RagLibrarySecondaryGroup = {
  field: string;
  label: string;
  value: string;
  document_count: number;
  documents: RagLibraryDocumentSummary[];
};

export type RagLibraryGroup = {
  field: string;
  label: string;
  value: string;
  document_count: number;
  documents: RagLibraryDocumentSummary[];
  secondary_field: string | null;
  secondary_groups: RagLibrarySecondaryGroup[];
};

export type RagAuthorLibrary = {
  author: RagLibraryAuthor;
  grouping: {
    primary_field: string | null;
    secondary_field: string | null;
    available_fields: string[];
  };
  groups: RagLibraryGroup[];
  documents: RagLibraryDocumentSummary[];
};

export type RagLibraryRelatedDocument = {
  id: string;
  title: string;
  author_id: string | null;
  author_name: string | null;
  publication_label: string | null;
  work_type: string | null;
  source_url: string | null;
  relationship: string;
};

export type RagLibraryDocumentDetail = {
  id: string;
  source_id: string;
  title: string;
  author_id: string | null;
  author_name: string | null;
  published_at: string | null;
  publication_year: number | null;
  publication_label: string | null;
  venue: string | null;
  collection: string | null;
  canonical_work_id: string | null;
  canonical_status: string | null;
  source_type: string;
  source_url: string | null;
  work_type: string | null;
  source_section: string | null;
  metadata: Record<string, unknown>;
  char_count: number;
  parent_document: RagLibraryRelatedDocument | null;
  child_documents: RagLibraryRelatedDocument[];
  source_author_id: string | null;
  source_author_name: string | null;
  source_status: string;
  created_at: string | null;
};

export type RagSelectedAuthor = {
  author_id: string;
  name: string;
  score: number;
  domains: string[];
  expertise_tags: string[];
  match_reason: string[];
  worldview?: string;
  key_maxims?: string[];
  favored_decision_variables?: string[];
};

export type RagEvidenceChunk = {
  chunk_id: string;
  author_id: string;
  author_name: string;
  text: string;
  similarity: number;
  metadata: Record<string, unknown>;
  document_id?: string;
  ranking_score?: number;
  score_type?: string;
};

export type RagQueryResult = {
  query: string;
  mode: string;
  selected_authors: RagSelectedAuthor[];
  evidence_chunks: RagEvidenceChunk[];
  answer: string | null;
  missing_information: string | null;
  evidence_sufficient: boolean;
};

export type RagCompanyContextResult = {
  company: string;
  question: string;
  relevant_author_lenses: RagSelectedAuthor[];
  evidence_pack: RagEvidenceChunk[];
  evidence_sufficient: boolean;
};

export type ThesisLiveSource = {
  url: string;
  title: string;
  snippet: string;
  source_type: "web" | "filing" | "transcript";
};

export type UpdatedThesisView = {
  stronger: string[];
  weaker: string[];
  unresolved: string[];
};

export type ConceptQueryResult = {
  query: string;
  best_passages: RagEvidenceChunk[];
  critique: string | null;
  evidence_sufficient: boolean;
  weak_evidence_note: string | null;
  // Thesis mode fields — present and populated only when mode === "thesis"
  mode?: "concept" | "thesis";
  thesis_question?: string | null;
  pushback_questions?: string[];
  missing_information?: string[];
  key_facts?: string[];
  updated_thesis_view?: UpdatedThesisView | null;
  live_sources?: ThesisLiveSource[];
  follow_up_questions?: string[];
  intent?: Record<string, unknown> | null;
  constraints_relaxed?: boolean;
  constraint_relaxation_reason?: string | null;
};

export type AISageChatEvidence = {
  id: string;
  chunk_id: string | null;
  document_id: string | null;
  author_id: string | null;
  author_name: string | null;
  source_url: string | null;
  title: string | null;
  snippet: string | null;
  similarity: number | null;
  ranking_score: number | null;
  score_type: string | null;
  metadata_json?: Record<string, unknown> | null;
};

export type AISageChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  status: string;
  created_at: string;
  completed_at?: string | null;
  error_message?: string | null;
  metadata_json?: Record<string, unknown> | null;
  evidence: AISageChatEvidence[];
};

export type AISageChatSummary = {
  id: string;
  title: string;
  preview?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  last_activity_at: string;
  pinned_at?: string | null;
};

export type AISageChatList = {
  items: AISageChatSummary[];
  total: number;
  limit: number;
  offset: number;
};

export type AISageChatDetail = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  last_activity_at: string;
  pinned_at?: string | null;
  metadata_json?: Record<string, unknown> | null;
  messages: AISageChatMessage[];
};

export type AISageChatSearchResult = {
  chat_id: string;
  title: string;
  snippet?: string | null;
  updated_at: string;
};

export type AISageChatSearchResults = {
  items: AISageChatSearchResult[];
  total: number;
};

export type AISageChatTurn = {
  chat: AISageChatDetail;
  user_message: AISageChatMessage;
  assistant_message: AISageChatMessage;
};

export type AISageStreamEvent =
  | {
      type: "ack";
      chat_id: string;
      user_message: AISageChatMessage;
      assistant_message_id: string;
    }
  | {
      type: "delta";
      assistant_message_id: string;
      delta: string;
    }
  | {
      type: "done";
      chat: AISageChatDetail;
      user_message: AISageChatMessage;
      assistant_message: AISageChatMessage;
    }
  | {
      type: "error";
      assistant_message: AISageChatMessage;
      error: string;
    };

async function rawRequest(path: string, init?: RequestInit, opts: RequestOptions = {}): Promise<Response> {
  const execute = async (): Promise<Response> => {
    try {
      const { headers: initHeaders, ...restInit } = init ?? {};
      return await fetch(`${API_BASE}${path}`, {
        credentials: "include",
        ...restInit,
        headers: buildHeaders(initHeaders, { includeJsonContentType: true, skipAuth: opts.skipAuth }),
      });
    } catch (err: unknown) {
      const reason = err instanceof Error ? err.message : String(err);
      throw new Error(`Unable to reach API at ${API_BASE}: ${reason}`);
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
    if (res.status === 401 && !opts.skipAuth && sessionExpired) {
      throw new AuthSessionExpiredError("Your session expired. Please sign in again.");
    }
    throw new Error(formatHttpError(res.status, text));
  }
  return res;
}

export const api = {
  health: () => req<Health>("/health"),
  authSignup: (payload: { username: string; password: string; display_name?: string }) =>
    req<AuthMe>("/auth/signup", { method: "POST", body: JSON.stringify(payload) }, { skipAuth: true }),
  authLogin: (payload: { username: string; password: string }) =>
    req<AuthToken>("/auth/login", { method: "POST", body: JSON.stringify(payload) }, { skipAuth: true }),
  authRefresh: () =>
    req<AuthToken>("/auth/refresh", { method: "POST" }, { skipAuth: true, skipRefreshRetry: true }),
  authMe: () => req<AuthMe>("/auth/me"),
  authLogout: () => req<{ status: string }>("/auth/logout", { method: "POST" }),
  dashboardBootstrap: (month: string, baseCurrency = "SGD") =>
    req<DashboardBootstrap>(`/dashboard/bootstrap?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  dashboardNetWorthChange: (month: string, baseCurrency = "SGD", compare = "prev_month,prev_year") =>
    req<DashboardNetWorthChange>(`/dashboard/net-worth-change?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}&compare=${encodeURIComponent(compare)}`),
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
  platforms: () => req<Platform[]>("/platforms"),
  platformOptions: () => req<PlatformOptions>("/platforms/options"),
  createPlatform: (payload: PlatformCreate) =>
    req<Platform>("/platforms", { method: "POST", body: JSON.stringify(payload) }),
  accounts: () => req<Account[]>("/accounts"),
  accountOptions: () => req<AccountOptions>("/accounts/options"),
  createAccount: (payload: AccountCreate) =>
    req<Account>("/accounts", { method: "POST", body: JSON.stringify(payload) }),
  currencies: () => req<Currency[]>("/currencies"),
  createCurrency: (payload: CurrencyCreate) =>
    req<Currency>("/currencies", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  dashboardSummary: (month: string, compare?: string, baseCurrency = "SGD", skipNetworth = false) =>
  req<DashboardSummary>(`/dashboard/summary?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}${compare ? `&compare=${encodeURIComponent(compare)}` : ""}${skipNetworth ? "&skip_networth=true" : ""}`),
  stockHoldingsSummary: (month: string, baseCurrency = "SGD") =>
    req<StockHoldingsSummary>(`/dashboard/stock-holdings?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  dataHubSummary: () => req<DataHubSummary>("/dashboard/data-hub-summary"),
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
  creditCardSummary: (month: string, baseCurrency = "SGD") =>
    req<CreditCardSummary>(`/spending/credit-cards?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  creditCardTransactions: (month: string, baseCurrency = "SGD") =>
    req<CreditCardDetail>(`/spending/credit-card-transactions?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  ingestUpload: async (accountId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
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
      throw new Error(`Unable to reach API at ${API_BASE}: ${reason}`);
    }
    if (!res.ok) {
      const text = await res.text();
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
      throw new Error(`Unable to reach API at ${API_BASE}: ${reason}`);
    }
    if (!res.ok) {
      const text = await res.text();
      throw new Error(formatHttpError(res.status, text));
    }
    return res.json() as Promise<Record<string, unknown>>;
  },
  ingestJobs: () => req<ImportJobListItem[]>("/ingest/jobs"),
  ingestJob: (jobId: number) => req<ImportJobDetail>(`/ingest/jobs/${jobId}`),
  registerIngestSignature: (jobId: number, parserKey: string) =>
    req<Record<string, unknown>>(`/ingest/jobs/${jobId}/register`, {
      method: "POST",
      body: JSON.stringify({ parser_key: parserKey }),
    }),
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
  cryptoRefreshNow: (adminKey?: string) =>
    req<Record<string, unknown>>("/crypto/refresh-now", {
      method: "POST",
      headers: adminKey ? { "X-Admin-Key": adminKey } : undefined,
    }),
  cryptoAllowlist: () => req<CryptoAllowlistItem[]>("/crypto/allowlist"),
  cryptoAllowlistAdd: (payload: { chain: string; contract_address: string }) =>
    req<CryptoAllowlistItem>("/crypto/allowlist", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  marketDataStatus: () => req<{ status: MarketDataExchangeStatus[] }>("/market-data/status"),
  marketDataRuns: (limit = 50) =>
    req<{ runs: MarketDataRun[] }>(`/market-data/runs?limit=${encodeURIComponent(String(limit))}`),
  marketDataRefreshNow: (adminKey?: string) =>
    req<{ status: string; exchanges: Array<Record<string, unknown>> }>("/market-data/refresh-now", {
      method: "POST",
      headers: adminKey ? { "X-Admin-Key": adminKey } : undefined,
    }),
  uploadReminders: (month?: string) =>
    req<UploadReminder[]>(`/alerts/upload-reminders${month ? `?month=${encodeURIComponent(month)}` : ""}`),
  uploadReminderCount: (month?: string) =>
    req<UploadReminderCount>(`/alerts/upload-reminders/count${month ? `?month=${encodeURIComponent(month)}` : ""}`),
  alertNotifications: (month?: string) =>
    req<UnifiedAlertsResponse>(`/alerts/notifications${month ? `?month=${encodeURIComponent(month)}` : ""}`),
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
  ragRetrieve: (payload: { query: string; top_k?: number; author_id?: string; domains?: string[]; expertise_tags?: string[] }) =>
    req<RagQueryResult>("/rag/retrieve", { method: "POST", body: JSON.stringify(payload) }),
  ragQuery: (payload: { query: string; top_k?: number; author_id?: string; domains?: string[]; expertise_tags?: string[] }) =>
    req<RagQueryResult>("/rag/query", { method: "POST", body: JSON.stringify(payload) }),
  ragCompanyContext: (payload: { company: string; question: string; top_k?: number }) =>
    req<RagCompanyContextResult>("/rag/analyze/company-context", { method: "POST", body: JSON.stringify(payload) }),
  aiSageQuery: (payload: { query: string; top_k?: number }) =>
    req<ConceptQueryResult>("/ai-sage/query", { method: "POST", body: JSON.stringify(payload) }),
  aiSageChats: (limit = 30, offset = 0) =>
    req<AISageChatList>(`/ai-sage/chats?limit=${encodeURIComponent(String(limit))}&offset=${encodeURIComponent(String(offset))}`),
  aiSageCreateChat: (payload: { title?: string | null } = {}) =>
    req<AISageChatDetail>("/ai-sage/chats", { method: "POST", body: JSON.stringify(payload) }),
  aiSageGetChat: (chatId: string) =>
    req<AISageChatDetail>(`/ai-sage/chats/${encodeURIComponent(chatId)}`),
  aiSageUpdateChat: (chatId: string, payload: { title?: string; pinned?: boolean }) =>
    req<AISageChatDetail>(`/ai-sage/chats/${encodeURIComponent(chatId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  aiSageDeleteChat: (chatId: string) =>
    req<{ status: string }>(`/ai-sage/chats/${encodeURIComponent(chatId)}`, { method: "DELETE" }),
  aiSageSearchChats: (query: string, limit = 20) =>
    req<AISageChatSearchResults>(`/ai-sage/chats/search?query=${encodeURIComponent(query)}&limit=${encodeURIComponent(String(limit))}`),
  aiSageAddMessage: (chatId: string, payload: { content: string }) =>
    req<AISageChatTurn>(`/ai-sage/chats/${encodeURIComponent(chatId)}/messages`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  aiSageRetryMessage: (chatId: string, messageId: string) =>
    req<AISageChatTurn>(`/ai-sage/chats/${encodeURIComponent(chatId)}/messages/${encodeURIComponent(messageId)}/retry`, {
      method: "POST",
    }),
  ragAuthors: (enabledOnly = false) =>
    req<RagAuthor[]>(`/rag/authors${enabledOnly ? "?enabled_only=true" : ""}`),
  ragCreateAuthor: (payload: RagAuthorCreate) =>
    req<RagAuthor>("/rag/authors", { method: "POST", body: JSON.stringify(payload) }),
  ragSources: (authorId?: string, status?: string) =>
    req<RagSourceRecord[]>(
      `/rag/sources${authorId ? `?author_id=${encodeURIComponent(authorId)}` : ""}${status ? `${authorId ? "&" : "?"}status=${encodeURIComponent(status)}` : ""}`
    ),
  ragIngestUrls: (
    authorId: string,
    payload: {
      urls: string[];
      source_type: string;
      selective_ingestion?: SelectiveIngestionOptions | null;
      ingestion_config?: RagIngestionConfigInput | null;
    }
  ) =>
    req<IngestUrlsBatchResult>(`/rag/authors/${encodeURIComponent(authorId)}/ingest-urls`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  ragPreviewFanout: (payload: {
    author_id: string;
    source_title?: string | null;
    source_published_at?: string | null;
    ingestion_config?: RagIngestionConfigInput | null;
  }) =>
    req<RagFanoutPreview>("/rag/fanout/preview", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  ragUpdateSourceIngestionConfig: (sourceId: string, ingestion_config: RagIngestionConfigInput | null) =>
    req<RagSourceRecord>(`/rag/sources/${encodeURIComponent(sourceId)}/ingestion-config`, {
      method: "PATCH",
      body: JSON.stringify({ ingestion_config }),
    }),
  ragIngestionJobs: (params?: { author_id?: string; source_id?: string; status?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.author_id) qs.set("author_id", params.author_id);
    if (params?.source_id) qs.set("source_id", params.source_id);
    if (params?.status) qs.set("status", params.status);
    if (params?.limit != null) qs.set("limit", String(params.limit));
    const query = qs.toString();
    return req<RagIngestionJobRecord[]>(`/rag/ingest/jobs${query ? `?${query}` : ""}`);
  },
  ragIngestionActivity: (authorId?: string, limit = 100) => {
    const qs = new URLSearchParams();
    if (authorId) qs.set("author_id", authorId);
    qs.set("limit", String(limit));
    return req<RagIngestionActivity>(`/rag/ingest/activity?${qs.toString()}`);
  },
  ragLibraryAuthors: () => req<RagLibraryAuthor[]>("/rag/library/authors"),
  ragAuthorLibrary: (authorId: string) =>
    req<RagAuthorLibrary>(`/rag/library/authors/${encodeURIComponent(authorId)}`),
  ragLibraryDocument: (documentId: string) =>
    req<RagLibraryDocumentDetail>(`/rag/library/documents/${encodeURIComponent(documentId)}`),
  ragRetryIngestion: (sourceId: string) =>
    req<RagIngestionJobRecord>(`/rag/ingest/retry/${encodeURIComponent(sourceId)}`, { method: "POST" }),
};

export async function streamAiSageChatMessage(
  chatId: string,
  payload: { content: string },
  onEvent: (event: AISageStreamEvent) => void,
  options?: { signal?: AbortSignal },
): Promise<void> {
  const response = await rawRequest(`/ai-sage/chats/${encodeURIComponent(chatId)}/messages/stream`, {
    method: "POST",
    body: JSON.stringify(payload),
    signal: options?.signal,
  });
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("Streaming response body unavailable.");
  }

  const decoder = new TextDecoder();
  let buffer = "";

  const flushFrames = (final = false) => {
    const normalized = buffer.replace(/\r\n/g, "\n");
    const frames = normalized.split("\n\n");
    buffer = frames.pop() ?? "";
    if (final && buffer.trim()) {
      frames.push(buffer);
      buffer = "";
    }
    for (const frame of frames) {
      let eventName = "message";
      const dataLines: string[] = [];
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trim());
        }
      }
      if (!dataLines.length) continue;
      const payload = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
      onEvent({ type: eventName as AISageStreamEvent["type"], ...(payload as object) } as AISageStreamEvent);
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    flushFrames();
  }
  buffer += decoder.decode();
  flushFrames(true);
}
