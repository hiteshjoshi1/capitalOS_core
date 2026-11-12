// #409 (U15, D-113): the month against the same month last year, and the savings-rate line.
import type { CashFlowCategoryDeltaItem, CashFlowTrendPoint, CashFlowYearOverYear } from "./api";
import * as fmt from "./format";

/** "Nov 2025", or "1–12 Nov 2025" when the open month is compared day for day. */
export function yearAgoLabel(yoy: CashFlowYearOverYear): string {
  const month = fmt.formatMonth(yoy.prior_year_month);
  if (yoy.basis !== "month_to_date") return month;
  const lastDay = Number(yoy.prior_end.slice(8, 10));
  return `1–${lastDay} ${month}`;
}

/** The categories that moved most against last year, either way, biggest move first. Categories
 * that are zero in both months and moves under a cent are left out. */
export function yearOverYearMovers(
  items: CashFlowCategoryDeltaItem[] | undefined,
  limit = 8,
): CashFlowCategoryDeltaItem[] {
  return (items ?? [])
    .filter((item) => Math.abs(item.delta_amount) >= 0.01)
    .sort((a, b) => Math.abs(b.delta_amount) - Math.abs(a.delta_amount) || a.label.localeCompare(b.label))
    .slice(0, limit);
}

export type SavingsRatePoint = {
  month: string;
  /** Percent (e.g. 32.5), or null for a month with no income. */
  percent: number | null;
  /** The bar's height: the rate clipped to ±100 %, so one month with almost no income (where
   * the rate can read −6,000 %) doesn't flatten every other bar. */
  barPercent: number | null;
};

const BAR_LIMIT = 100;

/** The savings-rate line's points: a rate as a percent, null where there was no income. */
export function savingsRatePoints(trend: CashFlowTrendPoint[] | undefined): SavingsRatePoint[] {
  return (trend ?? []).map((point) => {
    const percent = point.savings_rate == null ? null : point.savings_rate * 100;
    return {
      month: point.month,
      percent,
      barPercent: percent == null ? null : Math.max(-BAR_LIMIT, Math.min(BAR_LIMIT, percent)),
    };
  });
}

/** The bar's label: the rate, or "below −100%" when it was clipped. */
export function savingsRateLabel(point: SavingsRatePoint): string {
  if (point.percent == null) return "no income";
  if (point.percent < -BAR_LIMIT) return "below −100%";
  return fmt.formatPercent(point.percent, { scale: "points", decimals: 0 });
}

/** The savings rate over the whole span: total saved over total income (percent), so a month
 * with almost no income counts for what it is, not as a −6,000 % outlier. Null without income. */
export function averageSavingsRate(trend: CashFlowTrendPoint[] | undefined): number | null {
  const inflows = (trend ?? []).reduce((sum, p) => sum + (p.inflows ?? 0), 0);
  if (inflows <= 0) return null;
  const net = (trend ?? []).reduce((sum, p) => sum + (p.net ?? 0), 0);
  return (net / inflows) * 100;
}
