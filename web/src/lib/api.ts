const API_BASE = import.meta.env.VITE_API_BASE as string;

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
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
    asset_class: string;
    value: number;
    percent_of_networth: number;
    quantity?: number;
    avg_cost?: number | null;
    latest_price?: number | null;
    quote_currency?: string;
    geo?: string;
    platform?: string;
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
cash_percent: number;
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

export type CashFlowDetail = {
  month: string;
  base_currency: string;
  income_total: number;
  expense_total: number;
  net: number;
  savings_rate: number | null;
  calculation: string;
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

export type CashDeposits = {
  total: number;
  items: Array<{
    source: string;
    value: number;
    percent: number;
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
  total_crypto_usd: number;
  total_crypto_base: number;
  base_currency: string;
  eth_exposure_usd?: number;
  eth_exposure_base?: number;
  token_exposure_usd?: number;
  token_exposure_base?: number;
  token_count?: number;
  priced_token_count?: number;
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
  }>;
  wallet_exposure?: Array<{
    wallet_id: string;
    label?: string | null;
    address: string;
    chain_type: string;
    chain: string;
    total_usd: number;
    total_base: number;
  }>;
  wallet_chain_exposure?: Array<{
    wallet_id: string;
    chain: string;
    total_usd: number;
    total_base: number;
  }>;
  last_refreshed_at: string | null;
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

export type DashboardBootstrap = {
  as_of_month: string;
  base_currency: string;
  snapshot_day: number | null;
  net_worth_as_of: string | null;
  net_worth: {
    total: number;
    cash: number;
    stocks_funds: number;
    crypto: number;
    liabilities: number;
  };
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

export const api = {
  health: () => req<Health>("/health"),
  dashboardBootstrap: (month: string, baseCurrency = "SGD") =>
    req<DashboardBootstrap>(`/dashboard/bootstrap?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
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
  cashDeposits: (month: string, baseCurrency = "SGD") =>
    req<CashDeposits>(`/dashboard/cash-deposits?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  platformAllocation: (month: string, baseCurrency = "SGD") =>
    req<PlatformAllocation>(`/dashboard/platform-allocation?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
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
    const res = await fetch(`${API_BASE}/ingest/upload?account_id=${accountId}`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`API ${res.status}: ${text}`);
    }
    return res.json() as Promise<Record<string, unknown>>;
  },
  ingestIbkr: async (accountId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/ingest/ibkr?account_id=${accountId}`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`API ${res.status}: ${text}`);
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
  cryptoSummary: (baseCurrency = "USD") =>
    req<CryptoSummary>(`/crypto/summary?base_currency=${encodeURIComponent(baseCurrency)}`),
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
  marketDataStatus: () => req<{ status: MarketDataRun[] }>("/market-data/status"),
  marketDataRuns: (limit = 50) =>
    req<{ runs: MarketDataRun[] }>(`/market-data/runs?limit=${encodeURIComponent(String(limit))}`),
  marketDataRefreshNow: (adminKey?: string) =>
    req<{ status: string; exchanges: Array<Record<string, unknown>> }>("/market-data/refresh-now", {
      method: "POST",
      headers: adminKey ? { "X-Admin-Key": adminKey } : undefined,
    }),
  uploadReminders: () => req<UploadReminder[]>("/alerts/upload-reminders"),
  uploadReminderCount: () => req<UploadReminderCount>("/alerts/upload-reminders/count"),

};
