/**
 * What period the Cash Flow figures cover and what they are compared with (#243, D-63).
 *
 * The open month is month to date: "month to date (day 6 of 30)", compared with the
 * previous month up to the same day ("1–6 Oct"), clamped to that month's length
 * ("all of February" on 30 or 31 March). A past month is whole month vs whole month.
 * The API sends this as `analytics.comparison`; without it (an older API) the page falls
 * back to the full-month fields it always had. Money and percentages go through
 * `lib/format.ts` (#150).
 */
import type { CashFlowCategoryDeltaItem, CashFlowDetail } from "./api";
import * as fmt from "./format";

export type CashFlowPeriodView = {
  monthToDate: boolean;
  /** "month to date (day 6 of 30)", or null for a whole month. */
  periodLabel: string | null;
  /** What the figures are compared with: "1–6 Oct", "all of February", "October". */
  priorLabel: string | null;
  throughDay: number | null;
  monthDays: number | null;
  net: number;
  priorNet: number | null;
  netChange: number | null;
  priorInflows: number | null;
  priorOutflows: number | null;
  inflowsChange: number | null;
  outflowsChange: number | null;
  savingsRate: number | null;
  priorSavingsRate: number | null;
  outflowCategoryDeltas: CashFlowCategoryDeltaItem[];
  deteriorationDrivers: CashFlowCategoryDeltaItem[];
};

/** `October` for `2026-10`. */
function monthName(month: string): string {
  return fmt.formatMonth(month).replace(/ \d{4}$/, "");
}

/** `Oct` for `2026-10`. */
function monthShort(month: string): string {
  return fmt.formatMonth(month, "medium").replace(/ \d{4}$/, "");
}

/** "month to date (day 6 of 30)". */
export function monthToDateLabel(throughDay: number, monthDays: number): string {
  return `month to date (day ${throughDay} of ${monthDays})`;
}

/** The prior period of a same-day comparison: "1 Oct", "1–6 Oct", or "all of February" when clamped to its whole month. */
export function priorRangeLabel(priorMonth: string, priorThroughDay: number, priorMonthDays: number): string {
  if (priorThroughDay >= priorMonthDays) return `all of ${monthName(priorMonth)}`;
  if (priorThroughDay <= 1) return `1 ${monthShort(priorMonth)}`;
  return `1–${priorThroughDay} ${monthShort(priorMonth)}`;
}

export function cashFlowPeriodView(detail: CashFlowDetail): CashFlowPeriodView {
  const c = detail.analytics.comparison;
  if (c) {
    const monthToDate = c.basis === "month_to_date";
    return {
      monthToDate,
      periodLabel: monthToDate ? monthToDateLabel(c.through_day, c.month_days) : null,
      priorLabel: monthToDate
        ? priorRangeLabel(c.prior_month, c.prior_through_day, c.prior_month_days)
        : monthName(c.prior_month),
      throughDay: c.through_day,
      monthDays: c.month_days,
      net: c.net,
      priorNet: c.prior_net,
      netChange: c.net_change,
      priorInflows: c.prior_inflows,
      priorOutflows: c.prior_outflows,
      inflowsChange: c.inflows_change,
      outflowsChange: c.outflows_change,
      savingsRate: c.savings_rate,
      priorSavingsRate: c.prior_savings_rate,
      outflowCategoryDeltas: c.outflow_category_deltas,
      deteriorationDrivers: c.deterioration_drivers,
    };
  }
  const a = detail.analytics;
  return {
    monthToDate: false,
    periodLabel: null,
    priorLabel: a.prior_month ? monthName(a.prior_month) : null,
    throughDay: null,
    monthDays: null,
    net: detail.net,
    priorNet: a.prior_month_net,
    netChange: a.free_cash_flow_change_vs_prior_month,
    priorInflows: null,
    priorOutflows: null,
    inflowsChange: null,
    outflowsChange: null,
    savingsRate: detail.savings_rate,
    priorSavingsRate: null,
    outflowCategoryDeltas: a.outflow_category_deltas,
    deteriorationDrivers: a.deterioration_drivers,
  };
}

/** "Net cash flow this month" / "Net cash flow, month to date (day 6 of 30)". */
export function periodEyebrow(subject: string, view: CashFlowPeriodView): string {
  return view.periodLabel ? `${subject}, ${view.periodLabel}` : `${subject} this month`;
}

/**
 * The "What changed" sentence, formatted with the shared formatter (the API's own
 * answer prints raw numbers and compares a partial month with a full one).
 */
export function cashFlowNarrative(view: CashFlowPeriodView, month: string, currency: string): string {
  const money = (value: number | null) => fmt.formatSignedMoney(value, currency);
  const parts: string[] = [];
  if (view.priorNet == null || view.netChange == null || !view.priorLabel) {
    parts.push(
      view.monthToDate
        ? `Net cash flow is ${money(view.net)} so far (day ${view.throughDay} of ${view.monthDays}).`
        : `Net cash flow was ${money(view.net)} in ${monthName(month)}.`,
    );
    return parts.join(" ");
  }
  if (view.monthToDate) {
    parts.push(
      `Net cash flow is ${money(view.net)} so far (day ${view.throughDay} of ${view.monthDays}), ` +
        `versus ${money(view.priorNet)} over ${view.priorLabel}: a ${money(view.netChange)} change.`,
    );
  } else {
    parts.push(
      `Net cash flow was ${money(view.net)} in ${monthName(month)} versus ${money(view.priorNet)} in ${view.priorLabel}: ` +
        `a ${money(view.netChange)} change.`,
    );
  }
  if (view.inflowsChange != null && view.outflowsChange != null) {
    parts.push(
      `Inflows changed by ${money(view.inflowsChange)} and outflows by ${money(view.outflowsChange)}` +
        (view.monthToDate ? " over the same days." : "."),
    );
  }
  if (view.savingsRate != null && view.priorSavingsRate != null) {
    parts.push(`Savings rate moved from ${fmt.formatPercent(view.priorSavingsRate)} to ${fmt.formatPercent(view.savingsRate)}.`);
  } else if (view.inflowsChange != null) {
    parts.push("Savings rate can't be compared: one of the periods has no recorded inflows.");
  }
  return parts.join(" ");
}
