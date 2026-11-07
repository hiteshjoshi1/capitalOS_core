import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import CashFlowDetail from "../routes/CashFlowDetail";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";
import type { CashFlowDetail as CashFlowDetailResponse, CategoryTaxonomy } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    categories: vi.fn(),
    cashFlowDetail: vi.fn(),
    categoryOverride: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

const categoryFixture: CategoryTaxonomy[] = [
  { id: 100, code: "income", name: "Income", parent_id: null, display_order: 10 },
  { id: 101, code: "income_salary", name: "Salary", parent_id: 100, display_order: 11 },
  { id: 102, code: "income_dividends", name: "Dividends", parent_id: 100, display_order: 12 },
  { id: 110, code: "housing", name: "Housing", parent_id: null, display_order: 20 },
  { id: 111, code: "housing_rent", name: "Rent", parent_id: 110, display_order: 21 },
  { id: 150, code: "transfer", name: "Transfer", parent_id: null, display_order: 30 },
  { id: 151, code: "transfer_internal", name: "Internal Transfer", parent_id: 150, display_order: 31 },
];

const detailFixture: CashFlowDetailResponse = {
  month: "2026-02",
  base_currency: "SGD",
  income_total: 12480,
  expense_total: 8710,
  net: 3770,
  savings_rate: 0.3020833333,
  calculation: "Net = income_total - expense_total using month-scoped transactions with types INCOME, EXPENSE, FEE, TAX, INTEREST, TRANSFER. Rows resolved under Transfer categories or explicit source transfer categories are excluded.",
  analytics: {
    burn_rate: 0.6979166667,
    prior_month: "2026-01",
    prior_month_net: 6182,
    free_cash_flow_change_vs_prior_month: -2412,
    outflow_categories: [
      { label: "Rent", amount: 3200, percent: 3200 / 8710 },
      { label: "Dining", amount: 1780, percent: 1780 / 8710 },
      { label: "Groceries", amount: 1210, percent: 1210 / 8710 },
    ],
    inflow_categories: [
      { label: "Salary", amount: 12000, percent: 12000 / 12480 },
      { label: "Dividends", amount: 480, percent: 480 / 12480 },
    ],
    outflow_recurring_split: [
      { label: "Recurring", amount: 4410, percent: 4410 / 8710 },
      { label: "One-off", amount: 4300, percent: 4300 / 8710 },
    ],
    inflow_recurring_split: [
      { label: "Recurring", amount: 12480, percent: 1 },
    ],
    outflow_fixed_variable_split: [
      { label: "Fixed", amount: 4310, percent: 4310 / 8710 },
      { label: "Variable", amount: 4400, percent: 4400 / 8710 },
    ],
    inflow_source_mix: [
      { label: "Salary", amount: 12000, percent: 12000 / 12480 },
      { label: "Dividends", amount: 480, percent: 480 / 12480 },
      { label: "Transfers", amount: 0, percent: 0 },
    ],
    top_outflow_merchants: [
      { merchant: "Landlord", amount: 3200, percent: 3200 / 8710, transaction_count: 1 },
      { merchant: "Hawker Center", amount: 1780, percent: 1780 / 8710, transaction_count: 1 },
    ],
    largest_inflow_drivers: [
      { label: "Salary", amount: 12000, percent: 12000 / 12480 },
      { label: "Dividends", amount: 480, percent: 480 / 12480 },
    ],
    outflow_category_deltas: [
      { label: "Dining", current_amount: 1780, prior_amount: 0, delta_amount: 1780, delta_percent: null, direction: "deteriorated" },
      { label: "Rent", current_amount: 3200, prior_amount: 2800, delta_amount: 400, delta_percent: 400 / 2800, direction: "deteriorated" },
    ],
    deterioration_drivers: [
      { label: "Dining", current_amount: -1780, prior_amount: 0, delta_amount: -1780, delta_percent: null, direction: "deteriorated" },
      { label: "Rent", current_amount: -3200, prior_amount: -2800, delta_amount: -400, delta_percent: 400 / 2800, direction: "deteriorated" },
    ],
    trend: [
      { month: "2025-09", inflows: 0, outflows: 0, net: 0, savings_rate: null, burn_rate: null },
      { month: "2025-10", inflows: 0, outflows: 0, net: 0, savings_rate: null, burn_rate: null },
      { month: "2025-11", inflows: 0, outflows: 0, net: 0, savings_rate: null, burn_rate: null },
      { month: "2025-12", inflows: 0, outflows: 18, net: -18, savings_rate: null, burn_rate: null },
      { month: "2026-01", inflows: 10300, outflows: 4118, net: 6182, savings_rate: 0.6001941748, burn_rate: 0.3998058252 },
      { month: "2026-02", inflows: 12480, outflows: 8710, net: 3770, savings_rate: 0.3020833333, burn_rate: 0.6979166667 },
    ],
    waterfall: {
      starting_cash: 11000,
      snapshot_start_as_of: "2026-01-31T00:00:00+00:00",
      snapshot_start_boundary_at: "2026-01-31T00:00:00+00:00",
      inflows: 12480,
      outflows: 8710,
      transfers_and_funding: 0,
      investment_and_fx_effects: 230,
      other_cash_movements: 230,
      snapshot_end_as_of: "2026-02-28T00:00:00+00:00",
      snapshot_end_boundary_at: "2026-02-28T00:00:00+00:00",
      boundary_exact: true,
      availability_message: null,
      ending_cash: 15000,
    },
    answers: [
      { question: "Where did my money go this month?", answer: "Most outflows went to Rent (36.7% / 3200), Dining (20.4% / 1780), Groceries (13.9% / 1210)." },
      { question: "What were my top spending categories this month?", answer: "Rent at 3200, Dining at 1780, Groceries at 1210" },
      { question: "How much of my income was saved vs spent?", answer: "Saved 30.2% and spent 69.8% of inflows." },
      { question: "What changed versus last month?", answer: "Net cash flow was 3770 this month versus 6182 in 2026-01, a -2412 change. Inflows changed by +2180 and outflows changed by +4592. Savings rate moved from 60.0% to 30.2%." },
      { question: "Which recurring expenses are driving most of my outflows?", answer: "Rent (3200), Groceries (1210)" },
      { question: "What percentage of inflows came from salary, dividends, and transfers?", answer: "Salary 96.2%, dividends 3.8%, transfers 0.0%." },
      { question: "Which categories explain most of the deterioration in free cash flow?", answer: "Dining (-1780), Rent (-400)" },
    ],
    // A past month (#243): whole month vs whole month, the same figures as the fields above.
    comparison: {
      basis: "full_month",
      month: "2026-02",
      month_days: 28,
      through_day: 28,
      prior_month: "2026-01",
      prior_month_days: 31,
      prior_through_day: 31,
      prior_start: "2026-01-01",
      prior_end: "2026-01-31",
      inflows: 12480,
      outflows: 8710,
      net: 3770,
      savings_rate: 0.3020833333,
      prior_inflows: 10300,
      prior_outflows: 4118,
      prior_net: 6182,
      prior_savings_rate: 0.6001941748,
      inflows_change: 2180,
      outflows_change: 4592,
      net_change: -2412,
      outflow_category_deltas: [
        { label: "Dining", current_amount: 1780, prior_amount: 0, delta_amount: 1780, delta_percent: null, direction: "deteriorated" },
        { label: "Rent", current_amount: 3200, prior_amount: 2800, delta_amount: 400, delta_percent: 400 / 2800, direction: "deteriorated" },
      ],
      deterioration_drivers: [
        { label: "Dining", current_amount: -1780, prior_amount: 0, delta_amount: -1780, delta_percent: null, direction: "deteriorated" },
        { label: "Rent", current_amount: -3200, prior_amount: -2800, delta_amount: -400, delta_percent: 400 / 2800, direction: "deteriorated" },
      ],
    },
  },
  income: {
    total: 12480,
    transaction_count: 1,
    included_types: ["INCOME"],
    transactions: [
      {
        transaction_id: 2,
        ts: "2026-02-08T09:00:00+00:00",
        account_id: 10,
        account_name: "UOB One",
        account_type: "BANK",
        amount: 12480,
        currency: "SGD",
        base_amount: 12480,
        type: "INCOME",
        raw_category: "Salary",
        resolved_category: "Salary",
        resolved_category_id: 101,
        category_source: "rule",
        merchant_counterparty: "DBS Savings",
        notes: null,
      },
    ],
  },
  expenses: {
    total: 8710,
    transaction_count: 2,
    included_types: ["EXPENSE", "FEE", "TAX", "INTEREST"],
    transactions: [
      {
        transaction_id: 3,
        ts: "2026-02-10T12:00:00+00:00",
        account_id: 10,
        account_name: "DBS Savings",
        account_type: "BANK",
        amount: -3200,
        currency: "SGD",
        base_amount: -3200,
        type: "EXPENSE",
        raw_category: "Rent",
        resolved_category: "Rent",
        resolved_category_id: 111,
        category_source: "parser",
        merchant_counterparty: "Landlord",
        notes: null,
      },
      {
        transaction_id: 4,
        ts: "2026-02-14T19:30:00+00:00",
        account_id: 10,
        account_name: "DBS Savings",
        account_type: "BANK",
        amount: -1780,
        currency: "SGD",
        base_amount: -1780,
        type: "EXPENSE",
        raw_category: "Dining",
        resolved_category_id: null,
        resolved_category: "Dining",
        category_source: "parser",
        merchant_counterparty: "Hawker Center",
        notes: null,
      },
    ],
  },
};

// The open month (#243): day 17 of 28, compared with 1-17 January.
const monthToDateFixture: CashFlowDetailResponse = {
  ...detailFixture,
  analytics: {
    ...detailFixture.analytics,
    comparison: {
      basis: "month_to_date",
      month: "2026-02",
      month_days: 28,
      through_day: 17,
      prior_month: "2026-01",
      prior_month_days: 31,
      prior_through_day: 17,
      prior_start: "2026-01-01",
      prior_end: "2026-01-17",
      inflows: 12480,
      outflows: 8710,
      net: 3770,
      savings_rate: 0.3020833333,
      prior_inflows: 9000,
      prior_outflows: 2500,
      prior_net: 6500,
      prior_savings_rate: 6500 / 9000,
      inflows_change: 3480,
      outflows_change: 6210,
      net_change: -2730,
      outflow_category_deltas: [
        { label: "Dining", current_amount: 1780, prior_amount: 600, delta_amount: 1180, delta_percent: 1180 / 600, direction: "deteriorated" },
      ],
      deterioration_drivers: [
        { label: "Dining", current_amount: -1780, prior_amount: -600, delta_amount: -1180, delta_percent: -1180 / 600, direction: "deteriorated" },
      ],
    },
  },
};

const updatedDetailFixture: CashFlowDetailResponse = {
  ...detailFixture,
  income_total: 0,
  net: -8710,
  savings_rate: null,
  analytics: {
    ...detailFixture.analytics,
    burn_rate: null,
    prior_month_net: 6182,
    free_cash_flow_change_vs_prior_month: -14892,
    inflow_categories: [],
    inflow_recurring_split: [],
    inflow_source_mix: [{ label: "Transfers", amount: 0, percent: 0 }],
    largest_inflow_drivers: [],
    answers: detailFixture.analytics.answers.map((answer) => (
      answer.question === "How much of my income was saved vs spent?"
        ? {
            ...answer,
            answer: "Saved 0.0% of inflows and spent 100.0% of them. Outflows exceeded inflows by 8710, which had to come from existing cash or other funding sources.",
          }
        : answer
    )),
    waterfall: {
      starting_cash: 11000,
      snapshot_start_as_of: "2026-01-31T00:00:00+00:00",
      snapshot_start_boundary_at: "2026-01-31T00:00:00+00:00",
      inflows: 0,
      outflows: 8710,
      transfers_and_funding: 0,
      investment_and_fx_effects: 12710,
      other_cash_movements: 12710,
      snapshot_end_as_of: "2026-02-28T00:00:00+00:00",
      snapshot_end_boundary_at: "2026-02-28T00:00:00+00:00",
      boundary_exact: true,
      availability_message: null,
      ending_cash: 15000,
    },
    trend: detailFixture.analytics.trend.map((point) => (
      point.month === "2026-02"
        ? { ...point, inflows: 0, net: -8710, savings_rate: null, burn_rate: null }
        : point
    )),
  },
  income: {
    ...detailFixture.income,
    total: 0,
    transaction_count: 0,
    transactions: [],
  },
};

const staleBoundaryDetailFixture: CashFlowDetailResponse = {
  ...detailFixture,
  analytics: {
    ...detailFixture.analytics,
    waterfall: {
      ...detailFixture.analytics.waterfall,
      snapshot_start_as_of: "2026-01-27T00:00:00+00:00",
      snapshot_start_boundary_at: "2026-01-31T00:00:00+00:00",
      snapshot_end_as_of: "2026-02-22T00:00:00+00:00",
      snapshot_end_boundary_at: "2026-02-28T00:00:00+00:00",
      boundary_exact: false,
      availability_message: "Cash reconciliation needs exact cash snapshots on 2026-01-31 and 2026-02-28. Available snapshots are 2026-01-27 and 2026-02-22.",
    },
  },
};

function renderRoute(initialPath = "/cash-flow") {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/cash-flow" element={<CashFlowDetail />} />
          <Route path="/wealth/cash-flow" element={<CashFlowDetail />} />
          <Route path="/cash-flow/income" element={<CashFlowDetail />} />
          <Route path="/cash-flow/expenses" element={<CashFlowDetail />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe("CashFlowDetail route", () => {
  beforeEach(() => {
    vi.setSystemTime(new Date("2026-02-17T00:00:00Z"));
    window.localStorage.clear();
    mockApi.categories.mockResolvedValue(categoryFixture);
    mockApi.cashFlowDetail.mockResolvedValue(detailFixture);
    mockApi.categoryOverride.mockResolvedValue({
      transaction_id: 2,
      raw_category: "Salary",
      override_category: "Internal Transfer",
      resolved_category: "Internal Transfer",
      source: "manual",
      rule_id: null,
      rule_name: null,
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
    window.localStorage.clear();
    cleanup();
  });

  it("renders the overview tab with a hero, 6-month trend, drivers, and cash bridge — no audit table", async () => {
    renderRoute("/cash-flow");

    expect(await screen.findByRole("heading", { level: 1, name: "Cash Flow Overview" })).toBeInTheDocument();

    // Hero: value, delta chip, and the savings insight (no burn rate, #243)
    expect(await screen.findByText("Net cash flow this month")).toBeInTheDocument();
    expect(screen.getByText("+S$ 3,770")).toBeInTheDocument();
    // One <Delta> (#224): ▼ + the amount + its baseline, in the down colour.
    const chip = screen.getByText("-S$ 2,412").closest(".delta");
    expect(chip).toHaveClass("deltaChip", "delta--down");
    expect(chip).toHaveTextContent("▼-S$ 2,412vs January");
    expect(screen.getByText("Saved 30.2% of income")).toBeInTheDocument();

    // 3 KPI tiles, each with the previous month's figure; the Burn-rate tile is gone (#243)
    expect(screen.getByText("Total inflows")).toBeInTheDocument();
    expect(screen.getByText("Total outflows")).toBeInTheDocument();
    expect(screen.getByText("Savings rate")).toBeInTheDocument();
    expect(screen.queryByText("Burn rate")).not.toBeInTheDocument();
    expect(screen.queryByText(/Burn rate/)).not.toBeInTheDocument();
    expect(screen.getByText("January: S$ 10,300")).toBeInTheDocument();
    expect(screen.getByText("January: S$ 4,118")).toBeInTheDocument();
    expect(screen.getByText("January: 60.0%")).toBeInTheDocument();

    // Six-month trend chart
    expect(screen.getByLabelText("Net cash flow trend by month")).toBeInTheDocument();

    // Vs. last month narrative + driver rows
    expect(screen.getByRole("heading", { name: "Vs. last month" })).toBeInTheDocument();
    // A past month: whole month vs whole month, in the shared money format.
    expect(
      screen.getByText(
        "Net cash flow was +S$ 3,770 in February versus +S$ 6,182 in January: a -S$ 2,412 change. " +
          "Inflows changed by +S$ 2,180 and outflows by +S$ 4,592. Savings rate moved from 60.0% to 30.2%.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/\b3770\b|\b6182\b/)).not.toBeInTheDocument();
    const driversSection = screen.getByText("Vs. last month").closest("section") as HTMLElement;
    expect(within(driversSection).getByText("Dining")).toBeInTheDocument();
    expect(within(driversSection).getByText("+S$ 1,780")).toBeInTheDocument();

    // Cash bridge
    expect(screen.getByLabelText("Cash bridge chart")).toBeInTheDocument();
    expect(screen.getByText("Starting cash")).toBeInTheDocument();
    expect(screen.getByText("Ending cash")).toBeInTheDocument();

    // No audit trail on the overview tab
    expect(screen.queryByText("Expense transactions (2)")).not.toBeInTheDocument();
    expect(screen.queryByText("Income transactions (1)")).not.toBeInTheDocument();
  });

  it("labels the open month as month to date and compares it with the same days last month (#243)", async () => {
    mockApi.cashFlowDetail.mockResolvedValue(monthToDateFixture);
    renderRoute("/cash-flow");

    expect(await screen.findByText("Net cash flow, month to date (day 17 of 28)")).toBeInTheDocument();
    const chip = screen.getByText("-S$ 2,730").closest(".delta");
    expect(chip).toHaveTextContent("▼-S$ 2,730vs 1–17 Jan");
    // Not the full-month change against the whole of January.
    expect(screen.queryByText("-S$ 2,412")).not.toBeInTheDocument();

    expect(screen.getByText("Total inflows to date")).toBeInTheDocument();
    expect(screen.getByText("Total outflows to date")).toBeInTheDocument();
    expect(screen.getByText("1–17 Jan: S$ 9,000")).toBeInTheDocument();
    expect(screen.getByText("1–17 Jan: S$ 2,500")).toBeInTheDocument();
    expect(screen.queryByText(/Burn rate/)).not.toBeInTheDocument();

    expect(
      screen.getByText(
        "Net cash flow is +S$ 3,770 so far (day 17 of 28), versus +S$ 6,500 over 1–17 Jan: a -S$ 2,730 change. " +
          "Inflows changed by +S$ 3,480 and outflows by +S$ 6,210 over the same days. Savings rate moved from 72.2% to 30.2%.",
      ),
    ).toBeInTheDocument();
    // Drivers compare like for like: Dining 1,780 vs 600 by day 17.
    const driversSection = screen.getByText("Vs. last month").closest("section") as HTMLElement;
    expect(within(driversSection).getByText("+S$ 1,180")).toBeInTheDocument();
    expect(within(driversSection).queryByText("Rent")).not.toBeInTheDocument();
  });

  it("compares the expenses tab's categories like for like in the open month (#243)", async () => {
    mockApi.cashFlowDetail.mockResolvedValue(monthToDateFixture);
    renderRoute("/cash-flow/expenses");

    expect(await screen.findByText("Total outflows, month to date (day 17 of 28)")).toBeInTheDocument();
    const section = screen.getByRole("heading", { name: "Categories trending up" }).closest("section") as HTMLElement;
    expect(within(section).getByText("Compared with 1–17 Jan.")).toBeInTheDocument();
    expect(within(section).getByText("+S$ 1,180")).toBeInTheDocument();
  });

  it("notes currencies left out of the totals for lack of an FX rate (#170)", async () => {
    mockApi.cashFlowDetail.mockResolvedValue({
      ...detailFixture,
      fx_incomplete: true,
      fx_missing_currencies: ["XYZ"],
      fx_stale_currencies: [],
    });
    renderRoute("/cash-flow");

    expect(await screen.findByRole("note")).toHaveTextContent("Excludes amounts in XYZ");
  });

  it("shows no FX note when every rate is known", async () => {
    renderRoute("/cash-flow");

    expect(await screen.findByText("Net cash flow this month")).toBeInTheDocument();
    expect(screen.queryByTestId("fx-note")).not.toBeInTheDocument();
  });

  it("renders the income tab with a hero, source composition, recurring split, and income transactions", async () => {
    renderRoute("/cash-flow/income");

    expect(await screen.findByRole("heading", { level: 1, name: "Income" })).toBeInTheDocument();

    const hero = (await screen.findByText("Total inflows this month")).closest("article") as HTMLElement;
    expect(within(hero).getByText("S$ 12,480")).toBeInTheDocument();
    expect(screen.getByText("Inflows came from Salary S$ 12,000 (96.2%) and Dividends S$ 480.00 (3.8%).")).toBeInTheDocument();

    expect(screen.getByLabelText("Income source donut chart")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Recurring vs. one-off" })).toBeInTheDocument();

    expect(screen.getByText("Income transactions (1)")).toBeInTheDocument();
    expect(screen.getByText("DBS Savings")).toBeInTheDocument();
  });

  it("renders the expenses tab with category, split, merchant, and driver diagnostics", async () => {
    renderRoute("/cash-flow/expenses");

    expect(await screen.findByRole("heading", { level: 1, name: "Expenses" })).toBeInTheDocument();

    const hero = (await screen.findByText("Total outflows this month")).closest("article") as HTMLElement;
    expect(within(hero).getByText("S$ 8,710")).toBeInTheDocument();
    expect(screen.getByText(/Most outflows went to Rent/)).toBeInTheDocument();

    expect(screen.getByLabelText("Top expense categories donut chart")).toBeInTheDocument();

    expect(screen.getByRole("heading", { name: "How predictable is your spend" })).toBeInTheDocument();
    expect(screen.getByText("Recurring vs. non-recurring")).toBeInTheDocument();
    expect(screen.getByText("Fixed vs. variable")).toBeInTheDocument();

    expect(screen.getByLabelText("Top merchants chart")).toBeInTheDocument();
    expect(screen.getAllByText("Landlord").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Hawker Center").length).toBeGreaterThan(0);

    expect(screen.getByRole("heading", { name: "Categories trending up" })).toBeInTheDocument();

    expect(screen.getByText("Expense transactions (2)")).toBeInTheDocument();

    // The old boxed "recurring expenses driving outflows" answer card is dropped — no
    // equivalent section exists in the redesigned page.
    expect(screen.queryByText("Which recurring expenses are driving most of my outflows?")).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Dining" }));
    expect(await screen.findByLabelText("Top dining merchants chart")).toBeInTheDocument();
    expect(screen.getAllByText("Hawker Center").length).toBeGreaterThan(0);
  });

  it("renders visible DBS credit card expenses without payment transfers", async () => {
    mockApi.cashFlowDetail.mockResolvedValueOnce({
      ...detailFixture,
      expense_total: 8820,
      net: 3660,
      expenses: {
        ...detailFixture.expenses,
        total: 8820,
        transaction_count: 3,
        transactions: [
          ...detailFixture.expenses.transactions,
          {
            transaction_id: 44,
            ts: "2026-02-16T10:00:00+00:00",
            account_id: 11,
            account_name: "DBS Credit Card",
            account_type: "CREDIT_CARD",
            amount: -110,
            currency: "SGD",
            base_amount: -110,
            type: "EXPENSE",
            raw_category: "CreditCard::Purchase",
            resolved_category: "CreditCard::Purchase",
            resolved_category_id: null,
            category_source: "parser",
            merchant_counterparty: "SHENG SIONG",
            notes: "card_last4=2403",
          },
        ],
      },
    });

    renderRoute("/cash-flow/expenses");

    expect(await screen.findByRole("heading", { level: 1, name: "Expenses" })).toBeInTheDocument();
    expect(await screen.findByText("Expense transactions (3)")).toBeInTheDocument();
    expect(screen.getByText(/DBS Credit Card/)).toBeInTheDocument();
    expect(screen.getByText("SHENG SIONG")).toBeInTheDocument();
    expect(screen.getAllByText("CreditCard::Purchase").length).toBeGreaterThan(0);
    expect(screen.queryByText("GIRO PAYMENT DBS CREDIT CARD")).not.toBeInTheDocument();
  });

  it("degrades the cash bridge when month-boundary snapshots are unavailable", async () => {
    mockApi.cashFlowDetail.mockResolvedValueOnce(staleBoundaryDetailFixture);

    renderRoute("/cash-flow");

    expect(await screen.findByRole("heading", { level: 1, name: "Cash Flow Overview" })).toBeInTheDocument();
    expect(await screen.findByLabelText("Cash reconciliation unavailable")).toBeInTheDocument();
    expect(screen.getByText(/needs exact cash snapshots on 2026-01-31 and 2026-02-28/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Cash bridge chart")).not.toBeInTheDocument();
  });

  it("edits a category inline from the income transaction list and refreshes the diagnostics", async () => {
    const user = userEvent.setup();
    mockApi.cashFlowDetail.mockResolvedValueOnce(detailFixture).mockResolvedValueOnce(updatedDetailFixture);

    renderRoute("/cash-flow/income");

    expect(await screen.findByRole("heading", { level: 1, name: "Income" })).toBeInTheDocument();

    // Category tag is read-only-looking by default; clicking it reveals the editor.
    const editButton = await screen.findByRole("button", { name: "Edit category for transaction 2" });
    expect(screen.queryByLabelText("Select category for transaction 2")).not.toBeInTheDocument();
    await user.click(editButton);

    await user.selectOptions(screen.getByLabelText("Select category for transaction 2"), "151");
    await user.click(screen.getByLabelText("Save category for transaction 2"));

    await waitFor(() => {
      expect(mockApi.categoryOverride).toHaveBeenCalledWith({ transaction_id: 2, category_id: 151 });
    });
    await waitFor(() => {
      expect(mockApi.cashFlowDetail.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
    expect(await screen.findByText("Income transactions (0)")).toBeInTheDocument();
    expect(screen.getByText("No income transactions for February 2026.")).toBeInTheDocument();

    // The editor closes itself once the save succeeds.
    expect(screen.queryByLabelText("Select category for transaction 2")).not.toBeInTheDocument();
  });

  it("keeps the inline editor open and shows the error when a save fails", async () => {
    const user = userEvent.setup();
    mockApi.categoryOverride.mockRejectedValueOnce(new Error("Category save failed"));

    renderRoute("/cash-flow/income");

    expect(await screen.findByRole("heading", { level: 1, name: "Income" })).toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: "Edit category for transaction 2" }));
    await user.selectOptions(screen.getByLabelText("Select category for transaction 2"), "151");
    await user.click(screen.getByLabelText("Save category for transaction 2"));

    expect(await screen.findByText("Category save failed")).toBeInTheDocument();
    // Still open — the editor must not silently disappear on failure.
    expect(screen.getByLabelText("Select category for transaction 2")).toBeInTheDocument();
  });
});
