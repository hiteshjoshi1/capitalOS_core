import { describe, expect, it } from "vitest";

import type { CashFlowComparison, CashFlowDetail } from "../lib/api";
import {
  cashFlowNarrative,
  cashFlowPeriodView,
  monthToDateLabel,
  periodEyebrow,
  priorRangeLabel,
} from "../lib/cashFlowPeriod";

// Synthetic figures only (#243).
const comparison: CashFlowComparison = {
  basis: "month_to_date",
  month: "2026-11",
  month_days: 30,
  through_day: 6,
  prior_month: "2026-10",
  prior_month_days: 31,
  prior_through_day: 6,
  prior_start: "2026-10-01",
  prior_end: "2026-10-06",
  inflows: 42987,
  outflows: 61558,
  net: -18571,
  savings_rate: -18571 / 42987,
  prior_inflows: 40000,
  prior_outflows: 30000,
  prior_net: 10000,
  prior_savings_rate: 0.25,
  inflows_change: 2987,
  outflows_change: 31558,
  net_change: -28571,
  outflow_category_deltas: [],
  deterioration_drivers: [],
};

function detailWith(c: CashFlowComparison | null, overrides: Partial<CashFlowDetail["analytics"]> = {}): CashFlowDetail {
  return {
    month: c?.month ?? "2026-09",
    base_currency: "SGD",
    income_total: 42987,
    expense_total: 61558,
    net: -18571,
    savings_rate: -18571 / 42987,
    calculation: "",
    fx_incomplete: false,
    fx_missing_currencies: [],
    fx_stale_currencies: [],
    analytics: {
      burn_rate: 61558 / 42987,
      prior_month: "2026-08",
      prior_month_net: 5000,
      free_cash_flow_change_vs_prior_month: -23571,
      outflow_categories: [],
      inflow_categories: [],
      outflow_recurring_split: [],
      inflow_recurring_split: [],
      outflow_fixed_variable_split: [],
      inflow_source_mix: [],
      top_outflow_merchants: [],
      largest_inflow_drivers: [],
      outflow_category_deltas: [],
      deterioration_drivers: [],
      trend: [],
      waterfall: {
        starting_cash: null,
        snapshot_start_as_of: null,
        snapshot_start_boundary_at: null,
        inflows: 0,
        outflows: 0,
        transfers_and_funding: null,
        investment_and_fx_effects: null,
        other_cash_movements: null,
        snapshot_end_as_of: null,
        snapshot_end_boundary_at: null,
        boundary_exact: false,
        availability_message: null,
        ending_cash: null,
      },
      answers: [],
      comparison: c,
      ...overrides,
    },
    income: { total: 0, transaction_count: 0, included_types: [], transactions: [] },
    expenses: { total: 0, transaction_count: 0, included_types: [], transactions: [] },
  };
}

describe("cash flow period labels (#243)", () => {
  it("labels the open month as month to date", () => {
    expect(monthToDateLabel(6, 30)).toBe("month to date (day 6 of 30)");
    const view = cashFlowPeriodView(detailWith(comparison));
    expect(view.monthToDate).toBe(true);
    expect(periodEyebrow("Net cash flow", view)).toBe("Net cash flow, month to date (day 6 of 30)");
    expect(view.priorLabel).toBe("1–6 Oct");
  });

  it("names the prior period, clamped to the whole prior month", () => {
    expect(priorRangeLabel("2026-10", 6, 31)).toBe("1–6 Oct");
    expect(priorRangeLabel("2026-10", 1, 31)).toBe("1 Oct");
    // 31 Dec vs November, 30 or 31 Mar vs February: the whole prior month.
    expect(priorRangeLabel("2026-11", 30, 30)).toBe("all of November");
    expect(priorRangeLabel("2026-02", 28, 28)).toBe("all of February");
    // 30 Nov vs October is 1-30 Oct, not all of it.
    expect(priorRangeLabel("2026-10", 30, 31)).toBe("1–30 Oct");
  });

  it("keeps a past month whole month vs whole month", () => {
    const past: CashFlowComparison = {
      ...comparison,
      basis: "full_month",
      month: "2026-09",
      month_days: 30,
      through_day: 30,
      prior_month: "2026-08",
      prior_through_day: 31,
      prior_end: "2026-08-31",
    };
    const view = cashFlowPeriodView(detailWith(past));
    expect(view.monthToDate).toBe(false);
    expect(view.periodLabel).toBeNull();
    expect(periodEyebrow("Net cash flow", view)).toBe("Net cash flow this month");
    expect(view.priorLabel).toBe("August");
  });

  it("falls back to the full-month fields without a comparison", () => {
    const view = cashFlowPeriodView(detailWith(null));
    expect(view.monthToDate).toBe(false);
    expect(view.priorLabel).toBe("August");
    expect(view.netChange).toBe(-23571);
    expect(view.priorInflows).toBeNull();
  });
});

describe("cash flow narrative (#243)", () => {
  it("formats the month-to-date sentence with the shared money formatter", () => {
    const text = cashFlowNarrative(cashFlowPeriodView(detailWith(comparison)), "2026-11", "SGD");
    expect(text).toBe(
      "Net cash flow is -S$ 18,571 so far (day 6 of 30), versus +S$ 10,000 over 1–6 Oct: a -S$ 28,571 change. " +
        "Inflows changed by +S$ 2,987 and outflows by +S$ 31,558 over the same days. " +
        "Savings rate moved from 25.0% to -43.2%.",
    );
    // No raw numbers (the review's "42987 … -18571").
    expect(text).not.toMatch(/\b18571\b|\b42987\b/);
  });

  it("formats a past month's sentence", () => {
    const past: CashFlowComparison = { ...comparison, basis: "full_month", month: "2026-09", prior_month: "2026-08" };
    const text = cashFlowNarrative(cashFlowPeriodView(detailWith(past)), "2026-09", "USD");
    expect(text).toBe(
      "Net cash flow was -USD 18,571 in September versus +USD 10,000 in August: a -USD 28,571 change. " +
        "Inflows changed by +USD 2,987 and outflows by +USD 31,558. Savings rate moved from 25.0% to -43.2%.",
    );
  });

  it("says when a savings rate can't be compared", () => {
    const noIncome: CashFlowComparison = { ...comparison, prior_inflows: 0, prior_savings_rate: null };
    const text = cashFlowNarrative(cashFlowPeriodView(detailWith(noIncome)), "2026-11", "SGD");
    expect(text).toMatch(/Savings rate can't be compared: one of the periods has no recorded inflows\.$/);
  });
});
