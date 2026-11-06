/**
 * Rules for showing a change against a baseline (#224, UX review #131 "Honest
 * comparisons"). `components/Delta.tsx` renders them; formatting itself stays in
 * `lib/format.ts` (#150).
 *
 * - A missing baseline is a sentence ("no comparison: no data for Oct 2026"), never a
 *   delta the size of the whole figure.
 * - The % is computed from the same currency as the amount: pass the baseline amount
 *   (`compareValue`) and the % is `abs / |compareValue|`.
 * - Direction is ▲/▼ as well as colour, and up/down use one colour pair everywhere.
 */
import { formatDate, formatMonth } from "./format";

export type DeltaDirection = "up" | "down" | "flat";

type Amount = number | null | undefined;

function isNumber(value: Amount): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function deltaDirection(abs: Amount): DeltaDirection {
  if (!isNumber(abs) || abs === 0) return "flat";
  return abs > 0 ? "up" : "down";
}

/**
 * The % (a fraction) of a change against its baseline amount, both in one currency.
 * No baseline, or a zero/negative one, has no meaningful %: `null`.
 */
export function deltaPercent(abs: Amount, compareValue: Amount): number | null {
  if (!isNumber(abs) || !isNumber(compareValue) || compareValue <= 0) return null;
  return abs / compareValue;
}

/** `no data for Oct 2026` for a `YYYY-MM` month, or for a date (`no data for 4 Nov 2026`). */
export function noDataFor(monthOrDate: string | null | undefined): string {
  if (!monthOrDate) return "no data for the comparison period";
  if (/^\d{4}-\d{2}$/.test(monthOrDate)) return `no data for ${formatMonth(monthOrDate, "medium")}`;
  const date = formatDate(monthOrDate);
  return date === "—" ? `no data for ${monthOrDate}` : `no data for ${date}`;
}

/** `no exchange rate for Oct 2026` (D-30: an FX gap, not a zero). */
export function noRateFor(month: string | null | undefined): string {
  return month ? `no exchange rate for ${formatMonth(month, "medium")}` : "no exchange rate for the comparison period";
}

/**
 * The missing-baseline sentence for a backend comparison, or null when it has a real
 * baseline. The backend says so explicitly (`baseline_missing`, #224); a zero baseline
 * on its own is never taken to mean "missing".
 */
export function missingBaselineReason(
  change: { baseline_missing?: boolean; compare_month?: string | null } | null | undefined,
): string | null {
  if (!change?.baseline_missing) return null;
  return noDataFor(change.compare_month);
}
