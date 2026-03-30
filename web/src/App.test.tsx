import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import { ThemeProvider } from "./context/ThemeContext";
import { api } from "./lib/api";
import type { DashboardBootstrap } from "./lib/api";

// Mock the API module
vi.mock("./lib/api", () => ({
  api: {
    dashboardBootstrap: vi.fn(),
    dashboardNetWorthChange: vi.fn(),
    spendingSummary: vi.fn(),
    unmappedTransactions: vi.fn(),
  },
}));

describe("App (thin Dashboard smoke)", () => {
  it("renders net worth hero and action queue without dashboard unmapped fetches; RiskCard is NOT rendered", async () => {
    const mockBootstrap: DashboardBootstrap = {
      as_of_month: "2026-02",
      base_currency: "SGD",
      snapshot_day: null,
      net_worth_as_of: "2026-02-06",
      net_worth: {
        total: 100000,
        cash: 25000,
        stocks_funds: 50000,
        crypto: 25000,
        liabilities: 0,
      },
      stock_exposure_total: 50000,
      crypto_exposure_total: 25000,
      cash_percent: 25.0,
    };

    vi.mocked(api.dashboardBootstrap).mockResolvedValue(mockBootstrap);
    vi.mocked(api.spendingSummary).mockResolvedValue({
      month: "2026-02",
      base_currency: "SGD",
      income_total: 5000,
      expense_total: 3000,
      net: 2000,
      savings_rate: 0.4,
      income_categories: [],
      expense_categories: [],
    });
    vi.mocked(api.dashboardNetWorthChange).mockResolvedValue({
      as_of_month: "2026-02",
      base_currency: "SGD",
      net_worth_as_of: "2026-02-06",
      net_worth_change: null,
    });
    vi.mocked(api.unmappedTransactions).mockResolvedValue([]);

    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/"]}>
          <App />
        </MemoryRouter>
      </ThemeProvider>
    );

    // Net worth hero renders
    expect(await screen.findByText("Net Worth")).toBeInTheDocument();

    // Action queue renders (thin dashboard)
    expect(await screen.findByLabelText("Action queue")).toBeInTheDocument();

    // Action queue is kept as a lightweight placeholder without dashboard unmapped fetch
    expect(vi.mocked(api.unmappedTransactions)).not.toHaveBeenCalled();

    // RiskCard is NOT on the thin dashboard
    expect(screen.queryByRole("heading", { name: "Risk" })).not.toBeInTheDocument();

    // Geography / platform allocation are NOT on thin dashboard
    expect(screen.queryByText("Allocation by Geography")).not.toBeInTheDocument();
    expect(screen.queryByText("Allocation by Platform")).not.toBeInTheDocument();
  });
});
