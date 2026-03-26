import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import App from "../App";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";
import type { DashboardBootstrap, SpendingSummary } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    dashboardBootstrap: vi.fn(),
    spendingSummary: vi.fn(),
    unmappedTransactions: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

const bootstrapFixture: DashboardBootstrap = {
  as_of_month: "2026-02",
  base_currency: "SGD",
  snapshot_day: null,
  net_worth_as_of: "2026-02-06T00:00:00+00:00",
  net_worth: {
    total: 742180,
    cash: 118400,
    stocks_funds: 512300,
    crypto: 136900,
    liabilities: -25000,
  },
  stock_exposure_total: 90000,
  crypto_exposure_total: 136900,
  cash_percent: 15.96,
};

const spendingSummaryFixture: SpendingSummary = {
  month: "2026-02",
  base_currency: "SGD",
  income_total: 12480,
  expense_total: 8710,
  net: 3770,
  savings_rate: 0.3,
  income_categories: [
    { category: "Salary", amount: 12000 },
    { category: "Dividends", amount: 480 },
  ],
  expense_categories: [
    { category: "Rent", amount: 3200 },
    { category: "Groceries", amount: 1210 },
  ],
};

beforeEach(() => {
  vi.useRealTimers();
  vi.setSystemTime(new Date("2026-02-17T00:00:00Z"));
  window.localStorage.clear();
  mockApi.dashboardBootstrap.mockResolvedValue(bootstrapFixture);
  mockApi.spendingSummary.mockResolvedValue(spendingSummaryFixture);
  mockApi.unmappedTransactions.mockResolvedValue([]);
});

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
  window.localStorage.clear();
});

describe("App (thin Dashboard)", () => {
  function renderApp() {
    return render(
      <ThemeProvider>
        <MemoryRouter>
          <App />
        </MemoryRouter>
      </ThemeProvider>,
    );
  }

  it("renders net worth hero from bootstrap data", async () => {
    renderApp();
    expect(await screen.findByText("Net Worth")).toBeInTheDocument();
    expect(screen.getByText("S$ 742,180")).toBeInTheDocument();
  });

  it("renders exposure cards for stocks, crypto, cash, and liabilities", async () => {
    renderApp();
    expect(await screen.findByRole("link", { name: "Stocks & Funds details" })).toHaveAttribute("href", "/holdings");
    expect(screen.getByRole("link", { name: "Crypto details" })).toHaveAttribute("href", "/crypto/holdings");
    expect(screen.getByRole("link", { name: "Cash details" })).toHaveAttribute("href", "/cash");
    expect(screen.getByRole("link", { name: "Liabilities details" })).toHaveAttribute("href", "/credit-cards");
  });

  it("renders cash flow summary card linking to /cash-flow", async () => {
    renderApp();
    expect(await screen.findByRole("link", { name: "Cash Flow details" })).toHaveAttribute("href", "/cash-flow");
  });

  it("renders action queue placeholder", async () => {
    renderApp();
    expect(await screen.findByLabelText("Action queue")).toBeInTheDocument();
  });

  it("shows 'No pending actions' in action queue when all transactions are mapped", async () => {
    renderApp();
    await waitFor(() => {
      expect(screen.getByText("No pending actions")).toBeInTheDocument();
    });
  });

  it("shows unmapped transaction count in action queue", async () => {
    mockApi.unmappedTransactions.mockResolvedValue([
      {
        transaction_id: 1,
        ts: "2026-02-01",
        account_id: 1,
        account_name: "DBS",
        amount: -10,
        currency: "SGD",
        type: "EXPENSE",
        raw_category: null,
        merchant_counterparty: null,
        notes: null,
      },
      {
        transaction_id: 2,
        ts: "2026-02-02",
        account_id: 1,
        account_name: "DBS",
        amount: -20,
        currency: "SGD",
        type: "EXPENSE",
        raw_category: null,
        merchant_counterparty: null,
        notes: null,
      },
    ]);
    renderApp();
    await waitFor(() => {
      expect(screen.getByText("Unmapped transactions need categorization")).toBeInTheDocument();
    });
  });

  it("does NOT render RiskCard, geography AllocationCard, or platform AllocationCard", async () => {
    renderApp();
    expect(await screen.findByText("Net Worth")).toBeInTheDocument();
    expect(screen.queryByText("Risk")).not.toBeInTheDocument();
    expect(screen.queryByText("Allocation by Geography")).not.toBeInTheDocument();
    expect(screen.queryByText("Allocation by Platform")).not.toBeInTheDocument();
  });

  it("does NOT render Expense Breakdown or Trends placeholder cards", async () => {
    renderApp();
    expect(await screen.findByText("Net Worth")).toBeInTheDocument();
    expect(screen.queryByText("Expense Breakdown")).not.toBeInTheDocument();
    expect(screen.queryByText("Trends (Monthly)")).not.toBeInTheDocument();
  });

  it("only calls dashboardBootstrap and spendingSummary; not dashboardSummary, platformAllocation, creditCardSummary, or cryptoSummary", async () => {
    renderApp();

    await waitFor(() => {
      expect(mockApi.dashboardBootstrap).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(mockApi.spendingSummary).toHaveBeenCalledTimes(1);
    });

    expect(mockApi.dashboardBootstrap).toHaveBeenCalledWith("2026-02", "SGD");
    expect(mockApi.spendingSummary).toHaveBeenCalledWith("2026-02", "SGD");
  });

  it("renders API error state when bootstrap fails", async () => {
    mockApi.dashboardBootstrap.mockRejectedValueOnce(new Error("Network down"));
    renderApp();
    expect(await screen.findByText("API error")).toBeInTheDocument();
    expect(screen.getByText(/Network down/)).toBeInTheDocument();
  });

  it("persists the selected month for other pages", async () => {
    renderApp();
    expect(await screen.findByText("Net Worth")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Month"), { target: { value: "2026-01" } });

    await waitFor(() => {
      expect(mockApi.dashboardBootstrap).toHaveBeenCalledWith("2026-01", "SGD");
    });
    expect(window.localStorage.getItem("capitalos.selectedMonth")).toBe("2026-01");
  });

  it("unmappedTransactions is not called before bootstrapState is ready", async () => {
    let resolveBootstrap!: (v: typeof bootstrapFixture) => void;
    const pendingBootstrap = new Promise<typeof bootstrapFixture>((res) => {
      resolveBootstrap = res;
    });
    // Use mockReturnValue (not Once) so all bootstrap calls return pending
    mockApi.dashboardBootstrap.mockReturnValue(pendingBootstrap);

    renderApp();

    // Drain any microtasks / leaked effects from prior tests, then reset call counts
    await act(async () => {});
    mockApi.unmappedTransactions.mockClear();

    expect(mockApi.unmappedTransactions).not.toHaveBeenCalled();

    resolveBootstrap(bootstrapFixture);

    await waitFor(() => {
      expect(mockApi.unmappedTransactions).toHaveBeenCalled();
    });
  });

  it("spendingSummary is not called before bootstrapState is ready", async () => {
    let resolveBootstrap!: (v: typeof bootstrapFixture) => void;
    const pendingBootstrap = new Promise<typeof bootstrapFixture>((res) => {
      resolveBootstrap = res;
    });
    mockApi.dashboardBootstrap.mockReturnValueOnce(pendingBootstrap);

    renderApp();

    expect(mockApi.spendingSummary).not.toHaveBeenCalled();

    resolveBootstrap(bootstrapFixture);

    await waitFor(() => {
      expect(mockApi.spendingSummary).toHaveBeenCalledTimes(1);
    });
  });

  it("shows skeleton for cash flow while spending summary loads, then renders card", async () => {
    let resolveSpending!: (v: SpendingSummary) => void;
    const pendingSpending = new Promise<SpendingSummary>((res) => {
      resolveSpending = res;
    });
    mockApi.spendingSummary.mockReturnValueOnce(pendingSpending);

    renderApp();

    expect(await screen.findByText("Net Worth")).toBeInTheDocument();
    expect(screen.getByLabelText("Loading cash flow")).toBeInTheDocument();

    resolveSpending(spendingSummaryFixture);

    await waitFor(() => {
      expect(screen.queryByLabelText("Loading cash flow")).not.toBeInTheDocument();
    });
    expect(screen.getByRole("link", { name: "Cash Flow details" })).toBeInTheDocument();
  });

  it("bootstrap called exactly once on mount; spendingSummary not called before bootstrap resolves", async () => {
    let resolveBootstrap!: (v: typeof bootstrapFixture) => void;
    const pendingBootstrap = new Promise<typeof bootstrapFixture>((res) => {
      resolveBootstrap = res;
    });
    mockApi.dashboardBootstrap.mockReturnValueOnce(pendingBootstrap);

    renderApp();

    expect(mockApi.spendingSummary).not.toHaveBeenCalled();
    expect(mockApi.dashboardBootstrap).toHaveBeenCalledTimes(1);

    resolveBootstrap(bootstrapFixture);

    await waitFor(() => {
      expect(mockApi.spendingSummary).toHaveBeenCalledTimes(1);
    });
    expect(mockApi.dashboardBootstrap).toHaveBeenCalledTimes(1);
  });
});
