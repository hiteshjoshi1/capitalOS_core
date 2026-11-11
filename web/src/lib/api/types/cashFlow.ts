// Cash flow, spending and categories: response and request types (split out of lib/api.ts, #368).
import type { FxStatus } from "./common";

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
