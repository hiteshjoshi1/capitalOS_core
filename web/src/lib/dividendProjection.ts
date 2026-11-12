// #409 (U16, D-113): which method the expected-dividends projection used, in plain words.
import type { ExpectedDividendsOverview } from "./api";

/** "based on stored yields", "based on the last 12 months' payments", or both with counts. */
export function expectedMethodText(overview: ExpectedDividendsOverview | null | undefined): string {
  const byYield = overview?.companies_by_yield ?? 0;
  const byPast = overview?.companies_by_past_payments ?? 0;
  if (byYield > 0 && byPast > 0) {
    return `based on stored yields for ${byYield} and the last 12 months' payments for ${byPast} holding${byPast === 1 ? "" : "s"}`;
  }
  if (byPast > 0) return "based on the last 12 months' payments (no yields stored)";
  if (byYield > 0) return "based on current holdings and stored yields";
  return "no yields stored and no payments in the last 12 months";
}

/** Holdings the projection covers by either method. */
export function projectedHoldingCount(overview: ExpectedDividendsOverview | null | undefined): number {
  return (overview?.companies_by_yield ?? 0) + (overview?.companies_by_past_payments ?? 0);
}
