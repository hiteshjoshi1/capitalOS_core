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
    asset_id: number;
    symbol: string;
    asset_class: string;
    value: number;
    percent_of_networth: number;
  }>;
  snapshot_day: number;
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


export type Health = { status: string };

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

export const api = {
  health: () => req<Health>("/health"),
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
  dashboardSummary: (month: string, compare?: string) =>
  req<DashboardSummary>(`/dashboard/summary?month=${encodeURIComponent(month)}${compare ? `&compare=${encodeURIComponent(compare)}` : ""}`),
  platformAllocation: (month: string) =>
    req<PlatformAllocation>(`/dashboard/platform-allocation?month=${encodeURIComponent(month)}`),
  spendingSummary: (month: string, baseCurrency = "SGD") =>
    req<SpendingSummary>(`/spending/summary?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  creditCardSummary: (month: string, baseCurrency = "SGD") =>
    req<CreditCardSummary>(`/spending/credit-cards?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),

};
