// #409: Cash Flow vs last year (U15), expected-dividend method (U16), risk vs last month (U18).
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CashFlowYearOverYear, ExpectedDividendsOverview } from "../lib/api";
import { SavingsRateTrend, YearOverYearSection } from "../components/CashFlowYearOverYear";
import { averageSavingsRate, savingsRateLabel, savingsRatePoints, yearAgoLabel, yearOverYearMovers } from "../lib/yearOverYear";
import { expectedMethodText, projectedHoldingCount } from "../lib/dividendProjection";
import { riskChange } from "../lib/risk";

const money = (value?: number | null) => `S$ ${Math.round(value ?? 0).toLocaleString("en-US")}`;

function yoy(overrides: Partial<CashFlowYearOverYear> = {}): CashFlowYearOverYear {
  return {
    basis: "month_to_date",
    month: "2026-03",
    prior_year_month: "2025-03",
    through_day: 18,
    prior_start: "2025-03-01",
    prior_end: "2025-03-18",
    has_prior_year_data: true,
    inflows: 5000,
    outflows: 2500,
    net: 2500,
    savings_rate: 0.5,
    prior_inflows: 4000,
    prior_outflows: 1700,
    prior_net: 2300,
    prior_savings_rate: 0.575,
    outflow_category_deltas: [
      { label: "Rent", current_amount: 2000, prior_amount: 1500, delta_amount: 500, delta_percent: 0.33, direction: "deteriorated" },
      { label: "Groceries", current_amount: 100, prior_amount: 200, delta_amount: -100, delta_percent: -0.5, direction: "improved" },
      { label: "Flat", current_amount: 10, prior_amount: 10, delta_amount: 0, delta_percent: 0, direction: "flat" },
    ],
    ...overrides,
  };
}

describe("year over year (U15)", () => {
  it("labels a day-for-day comparison with its days, a whole month by name", () => {
    expect(yearAgoLabel(yoy())).toMatch(/^1–18 /);
    expect(yearAgoLabel(yoy({ basis: "full_month", prior_end: "2025-03-31" }))).not.toMatch(/^1–/);
  });

  it("keeps the biggest moves either way and drops flat categories", () => {
    expect(yearOverYearMovers(yoy().outflow_category_deltas).map((i) => i.label)).toEqual(["Rent", "Groceries"]);
  });

  it("shows spending against last year with each category's move", () => {
    render(<YearOverYearSection yoy={yoy()} formatMoney={money} />);
    expect(screen.getByRole("heading", { name: /Vs\. 1–18/ })).toBeInTheDocument();
    expect(screen.getByText(/Spent S\$ 2,500 vs S\$ 1,700/)).toBeInTheDocument();
    expect(screen.getByText("Rent")).toBeInTheDocument();
    expect(screen.getByText("+S$ 500")).toBeInTheDocument();
    expect(screen.getByText("−S$ 100")).toBeInTheDocument();
  });

  it("says when last year has no data instead of showing zero spending", () => {
    render(<YearOverYearSection yoy={yoy({ has_prior_year_data: false })} formatMoney={money} />);
    expect(screen.getByText(/No transactions recorded for/)).toBeInTheDocument();
    expect(screen.queryByText("Rent")).not.toBeInTheDocument();
  });

  it("draws the savings rate with months without income marked, and averages the rest", () => {
    const trend = [
      { month: "2026-01", inflows: 0, outflows: 100, net: -100, savings_rate: null, burn_rate: null },
      { month: "2026-02", inflows: 1000, outflows: 600, net: 400, savings_rate: 0.4, burn_rate: null },
      { month: "2026-03", inflows: 1000, outflows: 800, net: 200, savings_rate: 0.2, burn_rate: null },
    ];
    expect(savingsRatePoints(trend).map((p) => p.percent)).toEqual([null, 40, 20]);
    // Over the span: (−100 + 400 + 200) / 2,000 income = 25 %.
    expect(averageSavingsRate(trend)).toBeCloseTo(25);
    render(<SavingsRateTrend trend={trend} month="2026-03" />);
    expect(screen.getByRole("heading", { name: "Savings rate, twelve months" })).toBeInTheDocument();
    expect(screen.getByText(/25\.0% of income saved overall/)).toBeInTheDocument();
    expect(screen.getByText("no income")).toBeInTheDocument();
  });

  it("clips a month with almost no income instead of letting it flatten the chart", () => {
    const [point] = savingsRatePoints([{ month: "2026-04", inflows: 10, outflows: 677, net: -667, savings_rate: -66.7, burn_rate: null }]);
    expect(point.percent).toBeCloseTo(-6670);
    expect(point.barPercent).toBe(-100);
    expect(savingsRateLabel(point)).toBe("below −100%");
  });
});

describe("expected dividends method (U16)", () => {
  const base = { companies: [] } as unknown as ExpectedDividendsOverview;
  it("names the method used", () => {
    expect(expectedMethodText({ ...base, companies_by_yield: 2, companies_by_past_payments: 0 })).toMatch(/stored yields/);
    expect(expectedMethodText({ ...base, companies_by_yield: 0, companies_by_past_payments: 3 })).toMatch(/last 12 months' payments/);
    expect(expectedMethodText({ ...base, companies_by_yield: 1, companies_by_past_payments: 1 })).toMatch(/stored yields for 1 and the last 12 months' payments for 1 holding$/);
    expect(projectedHoldingCount({ ...base, companies_by_yield: 1, companies_by_past_payments: 2 })).toBe(3);
  });
});

describe("risk vs last month (U18)", () => {
  it("shows a concentration rise as worse, a fall as better, in points", () => {
    expect(riskChange(25.3, 24.1, { higherIsWorse: true, hasPrior: true })).toMatchObject({ text: "+1.2 pts", tone: "bad" });
    expect(riskChange(20, 22.5, { higherIsWorse: true, hasPrior: true })).toMatchObject({ text: "−2.5 pts", tone: "good" });
  });

  it("keeps the cash buffer neutral, and says nothing without last month", () => {
    expect(riskChange(30, 20, { higherIsWorse: false, hasPrior: true })).toMatchObject({ tone: "neutral" });
    expect(riskChange(30, null, { higherIsWorse: true, hasPrior: true }).text).toBeNull();
    expect(riskChange(30, 20, { higherIsWorse: true, hasPrior: false }).text).toBeNull();
    expect(riskChange(30, 30.01, { higherIsWorse: true, hasPrior: true }).text).toBe("no change");
  });
});
