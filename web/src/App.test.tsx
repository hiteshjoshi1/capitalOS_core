import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import { ThemeProvider } from "./context/ThemeContext";
import { api } from "./lib/api";
import type { DashboardSummary } from "./lib/api";

// Mock the API module
vi.mock("./lib/api", () => ({
  api: {
    health: vi.fn(),
    dashboardSummary: vi.fn(),
    cashDeposits: vi.fn(),
    platformAllocation: vi.fn(),
    stockExposure: vi.fn(),
    spendingSummary: vi.fn(),
    creditCardSummary: vi.fn(),
    cryptoSummary: vi.fn(),
    accountOptions: vi.fn(),
    platformOptions: vi.fn(),
    currencies: vi.fn(),
    unmappedTransactions: vi.fn(),
  },
}));

describe("App", () => {
  it("should pass cash_percent to RiskCard and render it in first KPI row", async () => {
    const mockSummary: DashboardSummary = {
      as_of_month: "2026-02",
      base_currency: "SGD",
      net_worth: {
        total: 100000,
        cash: 25000,
        stocks_funds: 50000,
        crypto: 25000,
        liabilities: 0,
      },
      geography: [],
      cash_flow: {
        income: 5000,
        expenses: 3000,
        net: 2000,
        savings_rate: 0.4,
      },
      top_holdings: [],
      cash_balances: [],
      snapshot_day: 6,
      net_worth_as_of: "2026-02-06",
      net_worth_change: null,
      cash_percent: 25.0,
    };

    // Mock API responses
    vi.mocked(api.health).mockResolvedValue({ status: "ok" });
    vi.mocked(api.dashboardSummary).mockResolvedValue(mockSummary);
    vi.mocked(api.cashDeposits).mockResolvedValue({ total: 25000, items: [] });
    vi.mocked(api.platformAllocation).mockResolvedValue({ as_of: "2026-02-06", total: 100000, items: [] });
    vi.mocked(api.stockExposure).mockResolvedValue({
      as_of: "2026-02-06",
      base_currency: "SGD",
      total: 50000,
      by_country: [],
      by_platform: [],
    });
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
    vi.mocked(api.creditCardSummary).mockResolvedValue({
      month: "2026-02",
      base_currency: "SGD",
      total_spend: 1000,
      cards: [],
    });
    vi.mocked(api.cryptoSummary).mockResolvedValue({
      total_crypto_usd: 25000,
      total_crypto_base: 25000,
      base_currency: "SGD",
      eth: { balance: 0, value_usd: 0, value_base: 0 },
      sol: { balance: 0, value_usd: 0, value_base: 0 },
      top5_holdings: [],
      top_holdings: [],
      last_refreshed_at: null,
      is_stale: false,
      refresh_triggered: false,
    });
    vi.mocked(api.accountOptions).mockResolvedValue({
      account_types: [],
      currencies: [],
      countries: [],
      currency_pattern: "",
    });
    vi.mocked(api.platformOptions).mockResolvedValue({
      platform_types: [],
      countries: [],
      country_pattern: "",
    });
    vi.mocked(api.currencies).mockResolvedValue([]);
    vi.mocked(api.unmappedTransactions).mockResolvedValue([]);

    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/"]}>
          <App />
        </MemoryRouter>
      </ThemeProvider>
    );

    // Wait for the component to load data and render
    // RiskCard should display cash_percent as first KPI
    const riskHeading = await screen.findByRole("heading", { name: "Risk" });
    const riskCard = riskHeading.parentElement;
    expect(riskCard).not.toBeNull();
    const riskCardScope = within(riskCard as HTMLElement);
    expect(riskCardScope.getByText("Cash")).toBeInTheDocument();
    expect(riskCardScope.getByText("25.0%")).toBeInTheDocument();

    // Verify the descriptive text
    expect(riskCardScope.getByText("% of net worth")).toBeInTheDocument();
  });
});
