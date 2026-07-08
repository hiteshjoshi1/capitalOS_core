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
  {
    transaction_id: 9002,
    ts: "2026-02-12T09:30:00+00:00",
    account_id: 7,
    account_name: "DBS Savings",
    amount: -18.0,
    currency: "SGD",
    type: "EXPENSE",
    raw_category: null,
    merchant_counterparty: "NTUC FairPrice",
    notes: null,
  },
  {
    transaction_id: 9003,
    ts: "2026-02-14T09:30:00+00:00",
    account_id: 7,
    account_name: "DBS Savings",
    amount: -12.0,
    currency: "SGD",
    type: "EXPENSE",
    raw_category: null,
    merchant_counterparty: "Grab",
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

  it("renders the unmapped queue grouped by merchant", async () => {
    renderRoute();

    expect(await screen.findByRole("heading", { level: 1, name: "Map Transactions" })).toBeInTheDocument();
    expect(screen.getByLabelText("Base currency")).toBeInTheDocument();
    expect(screen.getByText("3 transactions across 2 merchants still need a category")).toBeInTheDocument();
    expect(screen.getByText("NTUC FairPrice")).toBeInTheDocument();
    expect(screen.getByText("Grab")).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.textContent === "2 transactions · S$ 42.5")).toBeInTheDocument();
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

  it("expands a merchant group to review individual transactions", async () => {
    const user = userEvent.setup();
    renderRoute();

    expect(await screen.findByText("NTUC FairPrice")).toBeInTheDocument();
    expect(screen.queryByText("DBS Savings")).not.toBeInTheDocument();

    const reviewButtons = screen.getAllByRole("button", { name: "Review" });
    await user.click(reviewButtons[0]);

    expect(await screen.findByText("Hide")).toBeInTheDocument();
    expect(screen.getAllByText("DBS Savings").length).toBeGreaterThan(0);
  });

  it("filters merchant groups via the search box", async () => {
    const user = userEvent.setup();
    renderRoute();

    expect(await screen.findByText("Grab")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Search merchant"), "grab");

    expect(screen.getByText("Grab")).toBeInTheDocument();
    expect(screen.queryByText("NTUC FairPrice")).not.toBeInTheDocument();
  });

  it("applies a category to every transaction in a merchant group and removes it from the queue", async () => {
    const user = userEvent.setup();
    renderRoute();

    expect(await screen.findByText("NTUC FairPrice")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Category for NTUC FairPrice"), "2");
    await user.click(screen.getByRole("button", { name: "Apply to all 2" }));

    await waitFor(() => {
      expect(mockApi.categoryOverride).toHaveBeenCalledWith({ transaction_id: 9001, category_id: 2 });
      expect(mockApi.categoryOverride).toHaveBeenCalledWith({ transaction_id: 9002, category_id: 2 });
    });
    await waitFor(() => {
      expect(screen.queryByText("NTUC FairPrice")).not.toBeInTheDocument();
    });
    expect(
      screen.getAllByText(
        (_, element) => element?.tagName === "SPAN" && element?.textContent === "1 transactions across 1 merchants still need a category",
      ).length,
    ).toBeGreaterThan(0);
  });
});
