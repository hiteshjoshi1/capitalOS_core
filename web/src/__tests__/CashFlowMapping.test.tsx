import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import CashFlowMapping from "../routes/CashFlowMapping";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";
import type { CategoryTaxonomy, UnmappedTransaction } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    categories: vi.fn(),
    unmappedTransactions: vi.fn(),
    categoryOverride: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

const categoryFixture: CategoryTaxonomy[] = [
  { id: 1, code: "food_dining", name: "Food & Dining", parent_id: null, display_order: 30 },
  { id: 2, code: "food_dining_groceries", name: "Groceries", parent_id: 1, display_order: 31 },
  { id: 3, code: "transportation", name: "Transportation", parent_id: null, display_order: 40 },
  { id: 4, code: "transportation_rideshare", name: "Rideshare", parent_id: 3, display_order: 42 },
];

const unmappedFixture: UnmappedTransaction[] = [
  {
    transaction_id: 9001,
    ts: "2026-02-10T09:30:00+00:00",
    account_id: 7,
    account_name: "DBS Savings",
    amount: -24.5,
    currency: "SGD",
    type: "EXPENSE",
    raw_category: null,
    merchant_counterparty: "NTUC FairPrice",
    notes: null,
  },
];

function renderRoute() {
  return render(
    <ThemeProvider>
      <MemoryRouter>
        <CashFlowMapping />
      </MemoryRouter>
    </ThemeProvider>
  );
}

describe("CashFlowMapping route", () => {
  beforeEach(() => {
    vi.setSystemTime(new Date("2026-02-17T00:00:00Z"));
    window.localStorage.clear();
    mockApi.categories.mockResolvedValue(categoryFixture);
    mockApi.unmappedTransactions.mockResolvedValue(unmappedFixture);
    mockApi.categoryOverride.mockResolvedValue({
      transaction_id: 9001,
      raw_category: null,
      override_category: "Groceries",
      resolved_category: "Groceries",
      source: "manual",
      rule_id: null,
      rule_name: null,
    });
  });

  it("renders the unmapped queue with month-scoped transactions", async () => {
    renderRoute();

    expect(await screen.findByText("Unmapped queue")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Map Transactions" })).toBeInTheDocument();
    expect(screen.getByLabelText("Base currency")).toBeInTheDocument();
    expect(screen.getByText("DBS Savings")).toBeInTheDocument();
    expect(screen.getByText("NTUC FairPrice")).toBeInTheDocument();
  });

  it("shows loading state while category and queue data are still in flight", async () => {
    mockApi.categories.mockReturnValue(new Promise(() => {}));
    mockApi.unmappedTransactions.mockReturnValue(new Promise(() => {}));

    renderRoute();

    expect(await screen.findByText("Loading…")).toBeInTheDocument();
  });

  it("shows the empty state when the selected month has no unmapped transactions", async () => {
    mockApi.unmappedTransactions.mockResolvedValue([]);

    renderRoute();

    expect(await screen.findByText("All transactions mapped for 2026-02.")).toBeInTheDocument();
  });

  it("posts an override and removes the row after success", async () => {
    const user = userEvent.setup();
    renderRoute();

    expect(await screen.findByText("NTUC FairPrice")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Override category for transaction 9001"), "2");

    await waitFor(() => {
      expect(mockApi.categoryOverride).toHaveBeenCalledWith({ transaction_id: 9001, category_id: 2 });
    });
    await waitFor(() => {
      expect(screen.queryByText("NTUC FairPrice")).not.toBeInTheDocument();
    });
  });
});
