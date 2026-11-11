// Credit cards: response and request types (split out of lib/api.ts, #368).
import type { FxStatus } from "./common";

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
    /** #352: printed or configured; null = unknown (never guessed). */
    due_date: string | null;
    current_due: number;
    utilization: number | null;
    due_source?: CardDueSource | null;
    due_status?: CardDueStatus | null;
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
  /** #352: printed or configured; null = unknown (never guessed). */
  due_date: string | null;
  due_source?: CardDueSource | null;
  due_status?: CardDueStatus | null;
};

/** Where a card's due date came from (#352, D-94). */
export type CardDueSource = "statement" | "manual" | "configured";
/** Where the newest statement's payment stands (#352). */
export type CardDueStatus = "paid" | "overdue" | "due_soon" | "upcoming";

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
  // #352, D-94: the newest statement's payment due, card currency.
  due_source?: CardDueSource | null;
  due_statement_date?: string | null;
  amount_due?: number | null;
  minimum_due?: number | null;
  paid_toward_due?: number | null;
  remaining_due?: number | null;
  due_status?: CardDueStatus | null;
  minimum_paid?: boolean | null;
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
