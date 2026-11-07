import type { CreditCardRecurringPayment, CreditCardTransaction } from "./api";

/** A purchase bigger than this (base currency) is "notable" (#266: the Notable filter). */
export const NOTABLE_THRESHOLD = 50;

/** The one transaction list's filters (#266), replacing the Notable / Recurring / Transactions
 *  sections and the Fees & charges card. */
export type TransactionFilter = "all" | "notable" | "recurring" | "charges";

export const TRANSACTION_FILTERS: { key: TransactionFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "notable", label: "Notable" },
  { key: "recurring", label: "Recurring" },
  { key: "charges", label: "Fees & charges" },
];

function merchantKey(accountId: number, merchant: string | null | undefined): string {
  return `${accountId}|${(merchant ?? "").trim().toLowerCase()}`;
}

/** The recurring payments by card + merchant, so a transaction can be matched to its repeat. */
export function recurringIndex(payments: CreditCardRecurringPayment[]): Map<string, CreditCardRecurringPayment> {
  return new Map(payments.map((p) => [merchantKey(p.account_id, p.merchant_counterparty), p]));
}

/** The repeat a transaction belongs to: a purchase whose card + merchant the API found to be a
 *  real repeat (`detect_recurring_cadence`, #266). Null for anything else. */
export function recurringFor(
  tx: CreditCardTransaction,
  index: Map<string, CreditCardRecurringPayment>,
): CreditCardRecurringPayment | null {
  if (tx.type !== "EXPENSE" || !tx.merchant_counterparty?.trim()) return null;
  return index.get(merchantKey(tx.account_id, tx.merchant_counterparty)) ?? null;
}

/** A fee, interest or tax line (anything that isn't a purchase). */
export function isCharge(tx: CreditCardTransaction): boolean {
  return tx.type !== "EXPENSE";
}

export function isNotable(tx: CreditCardTransaction, threshold = NOTABLE_THRESHOLD): boolean {
  return tx.type === "EXPENSE" && Math.abs(tx.amount) > threshold;
}

export function matchesFilter(
  tx: CreditCardTransaction,
  filter: TransactionFilter,
  index: Map<string, CreditCardRecurringPayment>,
): boolean {
  switch (filter) {
    case "notable":
      return isNotable(tx);
    case "recurring":
      return recurringFor(tx, index) != null;
    case "charges":
      return isCharge(tx);
    default:
      return true;
  }
}

/** The rows a filter shows: newest first, except Notable, which leads with the biggest. */
export function filterTransactions(
  rows: CreditCardTransaction[],
  filter: TransactionFilter,
  index: Map<string, CreditCardRecurringPayment>,
): CreditCardTransaction[] {
  const shown = rows.filter((tx) => matchesFilter(tx, filter, index));
  return filter === "notable"
    ? [...shown].sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount))
    : [...shown].sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0));
}

export function filterCounts(
  rows: CreditCardTransaction[],
  index: Map<string, CreditCardRecurringPayment>,
): Record<TransactionFilter, number> {
  const counts: Record<TransactionFilter, number> = { all: 0, notable: 0, recurring: 0, charges: 0 };
  for (const tx of rows) {
    for (const { key } of TRANSACTION_FILTERS) {
      if (matchesFilter(tx, key, index)) counts[key] += 1;
    }
  }
  return counts;
}
