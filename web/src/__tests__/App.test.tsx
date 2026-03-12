import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";

import App from "../App";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";
import type {
  CreditCardSummary,
  CryptoSummary,
  DashboardSummary,
  PlatformAllocation,
  SpendingSummary,
  StockExposure,
} from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    health: vi.fn(),
    dashboardSummary: vi.fn(),
    platformAllocation: vi.fn(),
    spendingSummary: vi.fn(),
    creditCardSummary: vi.fn(),
    cryptoSummary: vi.fn(),
    stockExposure: vi.fn(),
    accountOptions: vi.fn(),
    createAccount: vi.fn(),
    platformOptions: vi.fn(),
    createPlatform: vi.fn(),
    currencies: vi.fn(),
    createCurrency: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

const summaryFixture: DashboardSummary = {
  as_of_month: "2026-02",
  base_currency: "SGD",
  snapshot_day: 6,
  net_worth_as_of: "2026-02-06T00:00:00+00:00",
  net_worth_change: {
    vs_prev_month: {
      abs: 10000,
      pct: 0.1,
      current_as_of: "2026-02-06T00:00:00+00:00",
      compare_as_of: "2026-01-06T00:00:00+00:00",
      compare_month: "2026-01",
    },
    vs_prev_year: {
      abs: 50000,
      pct: 0.5,
      current_as_of: "2026-02-06T00:00:00+00:00",
      compare_as_of: "2025-02-06T00:00:00+00:00",
      compare_month: "2025-02",
    },
  },
  net_worth: {
    total: 742180,
    cash: 118400,
    stocks_funds: 512300,
    crypto: 136900,
    liabilities: 0,
  },
  geography: [
    { country: "US", value: 700000, percent: 70 },
    { country: "SG", value: 300000, percent: 30 },
  ],
  cash_flow: {
    income: 8200,
    expenses: 5300,
    net: 2900,
    savings_rate: 0.35,
  },
  top_holdings: [
    { asset_id: 1, symbol: "TSLA", asset_class: "STOCK", value: 180000, percent_of_networth: 24.25, geo: "US", platform: "IBKR" },
    { asset_id: 2, symbol: "AAPL", asset_class: "STOCK", value: 150000, percent_of_networth: 20.21, geo: "US", platform: "IBKR" },
    { asset_id: 3, symbol: "NVDA", asset_class: "STOCK", value: 120000, percent_of_networth: 16.17, geo: "US", platform: "IBKR" },
    { asset_id: 4, symbol: "MSFT", asset_class: "STOCK", value: 90000, percent_of_networth: 12.13, geo: "US", platform: "IBKR" },
    { asset_id: 5, symbol: "USD", asset_class: "CASH", value: 60000, percent_of_networth: 8.08, geo: "SG", platform: "DBS" },
  ],
  cash_balances: [
    { currency: "USD", value: 60000 },
    { currency: "SGD", value: 58400 },
  ],
};

const platformAllocationFixture: PlatformAllocation = {
  as_of: "2026-02-06T00:00:00+00:00",
  total: 100000,
  items: [
    { platform: "IBKR", platform_type: "BROKER", country: "US", value: 70000, percent: 70 },
    { platform: "DBS", platform_type: "BANK", country: "SG", value: 30000, percent: 30 },
  ],
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

const creditCardSummaryFixture: CreditCardSummary = {
  month: "2026-02",
  base_currency: "SGD",
  total_spend: 2990,
  cards: [
    {
      account_id: 11,
      account_name: "DBS Credit Card",
      card_name: "DBS Altitude",
      issuer: "DBS",
      credit_limit: 20000,
      statement_day: 20,
      due_day: 25,
      due_date: "2026-02-25",
      current_due: 2990,
      utilization: 0.1495,
    },
  ],
};

const cryptoSummaryFixture: CryptoSummary = {
  total_crypto_usd: 8400,
  total_crypto_base: 8400,
  base_currency: "SGD",
  eth: { balance: 1.2345, value_usd: 8000, value_base: 8000 },
  sol: { balance: 10, value_usd: 400, value_base: 400 },
  top5_holdings: [
    { symbol: "ETH", chain: "ethereum", amount: 1.2345, value_usd: 8000, value_base: 8000 },
    { symbol: "SOL", chain: "solana", amount: 10, value_usd: 400, value_base: 400 },
  ],
  top_holdings: [
    { symbol: "ETH", chain: "ethereum", amount: 1.2345, value_usd: 8000, value_base: 8000, asset_class: "CRYPTO" },
  ],
  last_refreshed_at: "2026-02-06T00:00:00+00:00",
  is_stale: false,
  refresh_triggered: false,
};

const stockExposureFixture: StockExposure = {
  as_of: "2026-02-06T00:00:00+00:00",
  base_currency: "SGD",
  total: 90000,
  by_country: [
    { key: "US", value: 60000, percent: 66.7 },
    { key: "IN", value: 30000, percent: 33.3 },
  ],
  by_platform: [
    { key: "IBKR", value: 70000, percent: 77.8 },
    { key: "DBS", value: 20000, percent: 22.2 },
  ],
};

beforeEach(() => {
  vi.useRealTimers();
  vi.setSystemTime(new Date("2026-02-17T00:00:00Z"));
  window.localStorage.clear();
  mockApi.health.mockResolvedValue({ status: "ok" });
  mockApi.dashboardSummary.mockResolvedValue(summaryFixture);
  mockApi.platformAllocation.mockResolvedValue(platformAllocationFixture);
  mockApi.spendingSummary.mockResolvedValue(spendingSummaryFixture);
  mockApi.creditCardSummary.mockResolvedValue(creditCardSummaryFixture);
  mockApi.cryptoSummary.mockResolvedValue(cryptoSummaryFixture);
  mockApi.stockExposure.mockResolvedValue(stockExposureFixture);
});

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
  window.localStorage.clear();
});

describe("App", () => {
  function renderApp() {
    return render(
      <ThemeProvider>
        <MemoryRouter>
          <App />
        </MemoryRouter>
      </ThemeProvider>,
    );
  }

  it("renders refreshed dashboard structure with user menu and exposure links", async () => {
    const user = userEvent.setup();
    renderApp();

    expect(await screen.findByText("Net Worth")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "CapitalOS Dashboard" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Primary navigation" });
    expect(within(nav).queryByRole("link", { name: "Dashboard" })).not.toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Ingest" })).toHaveAttribute("href", "/ingest");
    expect(within(nav).queryByRole("link", { name: "Market Data" })).not.toBeInTheDocument();
    expect(screen.getByText("vs 2026-01")).toBeInTheDocument();
    expect(screen.getByText("+S$ 10,000 (+10.0%)")).toBeInTheDocument();
    expect(screen.getByText("vs 2025-02")).toBeInTheDocument();
    expect(screen.getByText("+S$ 50,000 (+50.0%)")).toBeInTheDocument();

    await user.click(screen.getByLabelText("User menu"));
    expect(screen.getByText("Manage")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(screen.getByText("API: ok")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add Account" })).toHaveAttribute("href", "/accounts/new");
    expect(screen.getByRole("link", { name: "Market Data" })).toHaveAttribute("href", "/market-data");
    expect(screen.getByLabelText("Base currency")).toBeInTheDocument();
    expect(screen.getByLabelText("Month")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Theme: Dark" })).toBeInTheDocument();

    expect(screen.getByRole("link", { name: "Stock Exposure details" })).toHaveAttribute("href", "/holdings");
    expect(screen.getByRole("link", { name: "Crypto Exposure details" })).toHaveAttribute("href", "/crypto/holdings");
    expect(screen.getByRole("link", { name: "Cash Exposure details" })).toHaveAttribute("href", "/cash");

    expect(screen.getByText("Cash Flow — 2026-02")).toBeInTheDocument();
    expect(screen.getByText("Expenses — Credit Cards")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Credit cards details" })).toHaveAttribute("href", "/credit-cards");
    expect(screen.getByText("Expense Breakdown")).toBeInTheDocument();
    expect(screen.getByText("Trends (Monthly)")).toBeInTheDocument();
    expect(screen.getAllByText("Snapshot")).toHaveLength(2);
  });

  it("toggles and persists dashboard theme", async () => {
    const user = userEvent.setup();
    const { unmount } = renderApp();

    expect(await screen.findByText("Net Worth")).toBeInTheDocument();
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");

    await user.click(screen.getByLabelText("User menu"));
    await user.click(screen.getByRole("button", { name: "Theme: Dark" }));

    await waitFor(() => {
      expect(document.documentElement).toHaveAttribute("data-theme", "light");
    });
    expect(window.localStorage.getItem("capitalos.theme")).toBe("light");

    unmount();
    renderApp();

    expect(await screen.findByText("Net Worth")).toBeInTheDocument();
    await waitFor(() => {
      expect(document.documentElement).toHaveAttribute("data-theme", "light");
    });
  });

  it("closes the user menu on outside click", async () => {
    const user = userEvent.setup();
    renderApp();

    expect(await screen.findByText("Net Worth")).toBeInTheDocument();
    const userMenuSummary = screen.getByLabelText("User menu");
    const userMenu = userMenuSummary.closest("details");
    expect(userMenu).not.toHaveAttribute("open");

    await user.click(userMenuSummary);
    expect(userMenu).toHaveAttribute("open");

    await user.click(document.body);
    await waitFor(() => {
      expect(userMenu).not.toHaveAttribute("open");
    });
  });

  it("closes the user menu on Escape key", async () => {
    const user = userEvent.setup();
    renderApp();

    expect(await screen.findByText("Net Worth")).toBeInTheDocument();
    const userMenuSummary = screen.getByLabelText("User menu");
    const userMenu = userMenuSummary.closest("details");

    await user.click(userMenuSummary);
    expect(userMenu).toHaveAttribute("open");

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(userMenu).not.toHaveAttribute("open");
    });
  });

  it("keeps risk card top N interactions functional", async () => {
    const user = userEvent.setup();
    renderApp();

    expect(await screen.findByText("Risk")).toBeInTheDocument();
    expect(screen.getByText("TSLA — 24.3%")).toBeInTheDocument();
    expect(screen.getByText("80.8%")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Top 5" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Top 3" })).toHaveAttribute("aria-pressed", "false");

    const riskTable = screen.getByTestId("risk-distribution-table");
    expect(within(riskTable).getAllByRole("row")).toHaveLength(6);

    await user.click(screen.getByRole("button", { name: "Top 3" }));
    expect(screen.getByRole("button", { name: "Top 3" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("60.6%")).toBeInTheDocument();
    expect(within(riskTable).getAllByRole("row")).toHaveLength(4);
  });

  it("shows helper text when fewer holdings than selected top N are available", async () => {
    mockApi.dashboardSummary.mockResolvedValueOnce({
      ...summaryFixture,
      top_holdings: summaryFixture.top_holdings.slice(0, 4),
    });

    renderApp();

    expect(await screen.findByText("Showing 4 of requested 5 positions.")).toBeInTheDocument();
  });

  it("shows no-data state when holdings are missing or net worth is invalid", async () => {
    mockApi.dashboardSummary.mockResolvedValueOnce({
      ...summaryFixture,
      net_worth: {
        ...summaryFixture.net_worth,
        total: 0,
      },
      top_holdings: [],
    });

    renderApp();

    expect(await screen.findByText("No holdings concentration data for this month or net worth is not positive.")).toBeInTheDocument();
    expect(screen.getByText("Insufficient holdings data for full risk concentration analysis.")).toBeInTheDocument();
  });

  it("renders API error state when requests fail", async () => {
    mockApi.health.mockRejectedValueOnce(new Error("Network down"));

    renderApp();

    expect(await screen.findByText("API error")).toBeInTheDocument();
    expect(screen.getByText(/Network down/)).toBeInTheDocument();
  });
});
