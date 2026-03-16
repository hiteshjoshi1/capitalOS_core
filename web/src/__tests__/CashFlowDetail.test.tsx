import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

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
  calculation: "Net = income_total - expense_total using month-scoped transactions with types INCOME, EXPENSE, FEE, TAX, INTEREST, excluding rows resolved under Transfer.",
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
    transaction_count: 1,
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
    ],
  },
};

const updatedDetailFixture: CashFlowDetailResponse = {
  ...detailFixture,
  income_total: 0,
  net: -8710,
  savings_rate: null,
  calculation: "Net = income_total - expense_total using month-scoped transactions with types INCOME, EXPENSE, FEE, TAX, INTEREST, excluding rows resolved under Transfer.",
  income: {
    ...detailFixture.income,
    total: 0,
    transaction_count: 0,
    transactions: [],
  },
};

function renderRoute() {
  return render(
    <ThemeProvider>
      <MemoryRouter>
        <CashFlowDetail />
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

  it("renders calculation context, edit steps, and contributing transactions", async () => {
    renderRoute();

    expect(await screen.findByRole("heading", { level: 1, name: "Cash Flow" })).toBeInTheDocument();
    expect(screen.getByText("Verify how income, expenses, and net were derived for the selected month.")).toBeInTheDocument();
    expect(screen.getByText("Net = income_total - expense_total using month-scoped transactions with types INCOME, EXPENSE, FEE, TAX, INTEREST, excluding rows resolved under Transfer.")).toBeInTheDocument();
    expect(screen.getByText("To correct a row here: choose a category in the table and click Save.")).toBeInTheDocument();
    expect(screen.getByText("Rows saved to a Transfer category are excluded from income, expenses, and net as soon as this page refreshes.")).toBeInTheDocument();
    expect(screen.getByText("Other category edits keep the row in its current income or expense bucket and update the label only.")).toBeInTheDocument();
    expect(screen.getByText("UOB One")).toBeInTheDocument();
    expect(screen.getByText("Landlord")).toBeInTheDocument();
    expect(screen.getByText("Income transactions (1)")).toBeInTheDocument();
    expect(screen.getByText("Expense transactions (1)")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Salary")).toBeInTheDocument();
  });

  it("posts an override from the detail table and refreshes the row", async () => {
    const user = userEvent.setup();
    mockApi.cashFlowDetail.mockResolvedValueOnce(detailFixture).mockResolvedValueOnce(updatedDetailFixture);

    renderRoute();

    expect(await screen.findByRole("heading", { level: 1, name: "Cash Flow" })).toBeInTheDocument();

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
    expect(screen.getByText("S$ -8,710")).toBeInTheDocument();
  });
});
