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
  account_type: string;  // BANK | BROKER | EXCHANGE | WALLET | CREDIT_CARD | LOAN
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
};



export type Health = { status: string };

export const api = {
  health: () => req<Health>("/health"),
  platforms: () => req<Platform[]>("/platforms"),
  accounts: () => req<Account[]>("/accounts"),
  dashboardSummary: (month: string) =>
    req<DashboardSummary>(`/dashboard/summary?month=${encodeURIComponent(month)}`),
};
