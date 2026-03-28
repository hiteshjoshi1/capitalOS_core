import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

  it("renders net worth card sections including cash flow and liabilities", async () => {
    renderApp();
    expect(await screen.findByText("Stocks / Funds")).toBeInTheDocument();
    expect(screen.getByText("Cash")).toBeInTheDocument();
    expect(screen.getByText("Crypto")).toBeInTheDocument();
    expect(screen.getByText("Cash Flow")).toBeInTheDocument();
    expect(screen.getByText("Liabilities")).toBeInTheDocument();
  });

  it("does not render separate exposure link cards on dashboard", async () => {
    window.localStorage.setItem("capitalos.theme", "light");
    renderApp();

    expect(await screen.findByText("Net Worth")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Stocks & Funds details" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Crypto details" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Cash details" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Cash Flow details" })).not.toBeInTheDocument();
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

  it("does not render cash mapping link on dashboard action queue", async () => {
    renderApp();
    await waitFor(() => {
      expect(screen.queryByText("Review cash mapping queue")).not.toBeInTheDocument();
      expect(screen.queryByRole("link", { name: "Review cash mapping queue" })).not.toBeInTheDocument();
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

  it("only calls dashboardBootstrap and spendingSummary; does not call unmappedTransactions or heavy APIs", async () => {
    renderApp();

    await waitFor(() => {
      expect(mockApi.dashboardBootstrap).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(mockApi.spendingSummary).toHaveBeenCalledTimes(1);
    });

    expect(mockApi.dashboardBootstrap).toHaveBeenCalledWith("2026-02", "SGD");
    expect(mockApi.spendingSummary).toHaveBeenCalledWith("2026-02", "SGD");
    expect(mockApi.unmappedTransactions).not.toHaveBeenCalled();
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

  it("does not call unmappedTransactions on dashboard load", async () => {
    let resolveBootstrap!: (v: typeof bootstrapFixture) => void;
    const pendingBootstrap = new Promise<typeof bootstrapFixture>((res) => {
      resolveBootstrap = res;
    });
    mockApi.dashboardBootstrap.mockReturnValue(pendingBootstrap);

    renderApp();

    expect(mockApi.unmappedTransactions).not.toHaveBeenCalled();

    resolveBootstrap(bootstrapFixture);

    await waitFor(() => {
      expect(mockApi.spendingSummary).toHaveBeenCalledTimes(1);
    });
    expect(mockApi.unmappedTransactions).not.toHaveBeenCalled();
  });

  it("spendingSummary is not called before bootstrapState is ready", async () => {
    let resolveBootstrap!: (v: typeof bootstrapFixture) => void;
    const pendingBootstrap = new Promise<typeof bootstrapFixture>((res) => {
      resolveBootstrap = res;
    });
    mockApi.dashboardBootstrap.mockReturnValue(pendingBootstrap);

    renderApp();
    mockApi.spendingSummary.mockClear();

    await Promise.resolve();
    expect(mockApi.spendingSummary).not.toHaveBeenCalled();

    resolveBootstrap(bootstrapFixture);

    await waitFor(() => {
      expect(mockApi.spendingSummary).toHaveBeenCalledTimes(1);
    });
  });

  it("renders cash flow section in net worth card once spending summary resolves", async () => {
    let resolveSpending!: (v: SpendingSummary) => void;
    const pendingSpending = new Promise<SpendingSummary>((res) => {
      resolveSpending = res;
    });
    mockApi.spendingSummary.mockReturnValueOnce(pendingSpending);

    renderApp();

    expect(await screen.findByText("Net Worth")).toBeInTheDocument();
    expect(screen.getByText("Cash Flow")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);

    resolveSpending(spendingSummaryFixture);

    await waitFor(() => {
      expect(screen.getByText("S$ 3,770")).toBeInTheDocument();
    });
    expect(screen.getByText("2026-02")).toBeInTheDocument();
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
