import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
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
        resolved_category: "Dining",
        resolved_category_id: null,
        category_source: "parser",
        merchant_counterparty: "Hawker Center",
        notes: null,
      },
    ],
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

  it("renders a high-level overview tab without cramming the audit tables into it", async () => {
    renderRoute("/cash-flow");

    expect(await screen.findByRole("heading", { level: 1, name: "Cash Flow Overview" })).toBeInTheDocument();
    expect(screen.getByText("High-level diagnostics for the selected month")).toBeInTheDocument();
    expect(screen.getByLabelText("Net cash flow trend by month")).toBeInTheDocument();
    expect(screen.getByLabelText("Compact inflow composition")).toBeInTheDocument();
    expect(screen.getByLabelText("Compact outflow composition")).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { name: "What changed versus last month?" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("heading", { name: "How much of my income was saved vs spent?" }).length).toBeGreaterThan(0);
    expect(screen.queryByText("Expense transactions (2)")).not.toBeInTheDocument();
  });

  it("renders the income tab with source composition and income transactions", async () => {
    renderRoute("/cash-flow/income");

    expect(await screen.findByRole("heading", { level: 1, name: "Income" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { name: "What percentage of inflows came from salary, dividends, and transfers?" }).length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Income source donut chart")).toBeInTheDocument();
    expect(screen.getByText("Income transactions (1)")).toBeInTheDocument();
    expect(screen.getByText("DBS Savings")).toBeInTheDocument();
  });

  it("renders the expenses tab with category, merchant, and audit diagnostics", async () => {
    renderRoute("/cash-flow/expenses");

    expect(await screen.findByRole("heading", { level: 1, name: "Expenses" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { name: "Where did my money go this month?" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("heading", { name: "Which recurring expenses are driving most of my outflows?" }).length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Top expense categories donut chart")).toBeInTheDocument();
    expect(screen.getByLabelText("Monthly spend by category chart")).toBeInTheDocument();
    expect(screen.getByLabelText("Top merchants chart")).toBeInTheDocument();
    expect(screen.getAllByText("Landlord").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Hawker Center").length).toBeGreaterThan(0);
    expect(screen.getByText("Expense transactions (2)")).toBeInTheDocument();

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
    expect(screen.getByText("Expense transactions (3)")).toBeInTheDocument();
    expect(screen.getByText("DBS Credit Card")).toBeInTheDocument();
    expect(screen.getByText("CREDIT_CARD")).toBeInTheDocument();
    expect(screen.getByText("SHENG SIONG")).toBeInTheDocument();
    expect(screen.getAllByText("CreditCard::Purchase").length).toBeGreaterThan(0);
    expect(screen.queryByText("GIRO PAYMENT DBS CREDIT CARD")).not.toBeInTheDocument();
  });

  it("degrades the reconciliation card when month-boundary snapshots are unavailable", async () => {
    mockApi.cashFlowDetail.mockResolvedValueOnce(staleBoundaryDetailFixture);

    renderRoute("/cash-flow");

    expect(await screen.findByRole("heading", { level: 1, name: "Cash Flow Overview" })).toBeInTheDocument();
    expect(screen.getByLabelText("Cash reconciliation unavailable")).toBeInTheDocument();
    expect(screen.getByText(/needs exact cash snapshots on 2026-01-31 and 2026-02-28/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Cash waterfall chart")).not.toBeInTheDocument();
  });

  it("posts an override from the income audit table and refreshes the diagnostics", async () => {
    const user = userEvent.setup();
    mockApi.cashFlowDetail.mockResolvedValueOnce(detailFixture).mockResolvedValueOnce(updatedDetailFixture);

    renderRoute("/cash-flow/income");

    expect(await screen.findByRole("heading", { level: 1, name: "Income" })).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Select category for transaction 2"), "151");
    await user.click(screen.getByLabelText("Save category for transaction 2"));

    await waitFor(() => {
      expect(mockApi.categoryOverride).toHaveBeenCalledWith({ transaction_id: 2, category_id: 151 });
    });
    await waitFor(() => {
      expect(mockApi.cashFlowDetail.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
    expect(await screen.findByText("Income transactions (0)")).toBeInTheDocument();
    expect(screen.getByText("No income transactions for 2026-02.")).toBeInTheDocument();
  });
});
