// Income and dividends: response and request types (split out of lib/api.ts, #368).
import type { FxStatus } from "./common";
import type { NetWorthBreakdown, NetWorthFreshness } from "./wealth";

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
  /** #409 (U16): "yield" (stored yield x price x shares) or "past_payments" (no yield stored: what
   * it paid in the twelve months to the period's end). */
  method?: "yield" | "past_payments" | string;
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
  /** #409 (U16): held companies projected by each method. */
  companies_by_yield?: number;
  companies_by_past_payments?: number;
};
