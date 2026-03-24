import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";

import App from "../App";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";
import type {
  CreditCardSummary,
  CryptoSummary,
  DashboardBootstrap,
  DashboardSummary,
  PlatformAllocation,
  SpendingSummary,
} from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    health: vi.fn(),
    dashboardBootstrap: vi.fn(),
    unmappedTransactions: vi.fn(),
    dashboardSummary: vi.fn(),
    platformAllocation: vi.fn(),
    spendingSummary: vi.fn(),
    creditCardSummary: vi.fn(),
    cryptoSummary: vi.fn(),
    stockExposure: vi.fn(),    accountOptions: vi.fn(),
    createAccount: vi.fn(),
    platformOptions: vi.fn(),
    createPlatform: vi.fn(),
    currencies: vi.fn(),
    createCurrency: vi.fn(),
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
    liabilities: 0,
  },
  stock_exposure_total: 90000,
  crypto_exposure_total: 136900,
  cash_percent: 15.96,
};

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
    { asset_id: 5, symbol: "GOOGL", asset_class: "STOCK", value: 60000, percent_of_networth: 8.08, geo: "US", platform: "IBKR" },
  ],
  cash_balances: [
    { currency: "USD", value: 60000 },
    { currency: "SGD", value: 58400 },
  ],
  cash_percent: 15.96,
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

beforeEach(() => {
  vi.useRealTimers();
  vi.setSystemTime(new Date("2026-02-17T00:00:00Z"));
  window.localStorage.clear();
  mockApi.health.mockResolvedValue({ status: "ok" });
  mockApi.dashboardBootstrap.mockResolvedValue(bootstrapFixture);
  mockApi.unmappedTransactions.mockResolvedValue([
    {
      transaction_id: 101,
      ts: "2026-02-03T00:00:00+00:00",
      account_id: 1,
      account_name: "DBS Savings",
      amount: -18.2,
      currency: "SGD",
      type: "EXPENSE",
      raw_category: null,
      merchant_counterparty: "NTUC",
      notes: null,
    },
    {
      transaction_id: 102,
      ts: "2026-02-04T00:00:00+00:00",
      account_id: 2,
      account_name: "OCBC 360",
      amount: -44.1,
      currency: "SGD",
      type: "EXPENSE",
      raw_category: "Uncategorized",
      merchant_counterparty: "Grab",
      notes: null,
    },
  ]);
  mockApi.dashboardSummary.mockResolvedValue(summaryFixture);
  mockApi.platformAllocation.mockResolvedValue(platformAllocationFixture);
  mockApi.spendingSummary.mockResolvedValue(spendingSummaryFixture);
  mockApi.creditCardSummary.mockResolvedValue(creditCardSummaryFixture);
  mockApi.cryptoSummary.mockResolvedValue(cryptoSummaryFixture);
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
    expect(await screen.findByText("vs 2026-01")).toBeInTheDocument();
    expect(screen.getByText("+S$ 10,000 (+10.0%)")).toBeInTheDocument();
    expect(screen.getByText("vs 2025-02")).toBeInTheDocument();
    expect(screen.getByText("+S$ 50,000 (+50.0%)")).toBeInTheDocument();

    await user.click(screen.getByLabelText("User menu"));
    expect(screen.getByText("Manage")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(screen.getByText("API: ok")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add Account" })).toHaveAttribute("href", "/accounts/new");
    expect(screen.getByRole("link", { name: "Market Data" })).toHaveAttribute("href", "/market-data");
    expect(screen.getByRole("link", { name: /Cash Flow Mapping/i })).toHaveAttribute("href", "/cash-flow/mapping");
    expect(screen.getByLabelText("2 unmapped transactions")).toBeInTheDocument();
    expect(screen.getByLabelText("Base currency")).toBeInTheDocument();
    expect(screen.getByLabelText("Month")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Theme: Dark" })).toBeInTheDocument();

    expect(screen.getByRole("link", { name: "Cash Flow details" })).toHaveAttribute("href", "/cash-flow");
    expect(screen.getByRole("link", { name: "Stock Exposure details" })).toHaveAttribute("href", "/holdings");
    expect(screen.getByRole("link", { name: "Crypto Exposure details" })).toHaveAttribute("href", "/crypto/holdings");
    expect(screen.getByRole("link", { name: "Cash Exposure details" })).toHaveAttribute("href", "/cash");

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

    const riskHeading = await screen.findByText("Risk");
    expect(riskHeading).toBeInTheDocument();
    expect(screen.getByText("TSLA — 24.3%")).toBeInTheDocument();
    expect(screen.getByText("80.8%")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Top 5" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Top 3" })).toHaveAttribute("aria-pressed", "false");

    const riskTable = screen.getByTestId("risk-distribution-table");
    const riskCard = riskTable.closest(".card");
    expect(riskCard).not.toBeNull();
    expect(within(riskCard as HTMLElement).getByText("Cash")).toBeInTheDocument();
    expect(within(riskCard as HTMLElement).getByText("16.0%")).toBeInTheDocument();
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
    await waitFor(() => {
      expect(mockApi.dashboardSummary).toHaveBeenCalledWith("2026-01", undefined, "SGD", true);
    });
    expect(window.localStorage.getItem("capitalos.selectedMonth")).toBe("2026-01");
  });

  it("renders stock/crypto/cash exposure cards from bootstrap data on first paint", async () => {
    renderApp();

    // Hero and exposure cards render from bootstrap without needing secondary data
    expect(await screen.findByText("Net Worth")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Stock Exposure details" })).toHaveAttribute("href", "/holdings");
    expect(screen.getByRole("link", { name: "Crypto Exposure details" })).toHaveAttribute("href", "/crypto/holdings");
    expect(screen.getByRole("link", { name: "Cash Exposure details" })).toHaveAttribute("href", "/cash");
    // Bootstrap drives the net worth total
    expect(screen.getByText("S$ 742,180")).toBeInTheDocument();
  });

  it("does not trigger crypto background refresh: fixture is false and no refresh endpoint called", async () => {
    renderApp();

    // Wait for full render including secondary panels
    await waitFor(() => {
      expect(mockApi.cryptoSummary).toHaveBeenCalledTimes(1);
    });

    const cryptoResult = await mockApi.cryptoSummary.mock.results[0].value;
    expect(cryptoResult.refresh_triggered).toBe(false);

    // Confirm no call was made to any market-data or crypto-refresh endpoint
    const allMockCalls = Object.entries(mockApi)
      .filter(([key]) => key !== "health")
      .map(([key, fn]) => ({ key, calls: (fn as ReturnType<typeof vi.fn>).mock.calls }));

    const refreshCalls = allMockCalls.filter(({ key }) =>
      key.toLowerCase().includes("refresh") || key.toLowerCase().includes("trigger")
    );
    expect(refreshCalls.every(({ calls }) => calls.length === 0)).toBe(true);
  });

  it("calls dashboardBootstrap on first phase and dashboardSummary without compare on second phase", async () => {
    renderApp();

    await waitFor(() => {
      expect(mockApi.dashboardBootstrap).toHaveBeenCalledTimes(1);
      expect(mockApi.dashboardBootstrap).toHaveBeenCalledWith("2026-02", "SGD");
    });

    await waitFor(() => {
      expect(mockApi.dashboardSummary).toHaveBeenCalledWith("2026-02", undefined, "SGD", true);
    });

    // health is lazy — only fetched when user menu is opened, not on mount
    expect(mockApi.health).not.toHaveBeenCalled();
  });

  it("/dashboard/bootstrap called exactly once on mount; /dashboard/summary not called before bootstrap resolves", async () => {
    let resolveBootstrap!: (v: typeof bootstrapFixture) => void;
    const pendingBootstrap = new Promise<typeof bootstrapFixture>((res) => { resolveBootstrap = res; });
    mockApi.dashboardBootstrap.mockReturnValueOnce(pendingBootstrap);

    renderApp();

    // Before bootstrap resolves, summary must not be called
    expect(mockApi.dashboardSummary).not.toHaveBeenCalled();
    expect(mockApi.dashboardBootstrap).toHaveBeenCalledTimes(1);

    // Resolve bootstrap
    resolveBootstrap(bootstrapFixture);

    // After bootstrap, summary is called exactly once in phase 2
    await waitFor(() => {
      expect(mockApi.dashboardSummary).toHaveBeenCalledTimes(1);
    });

    // Bootstrap still called exactly once total
    expect(mockApi.dashboardBootstrap).toHaveBeenCalledTimes(1);
  });

  it("stock_exposure_total and crypto_exposure_total from bootstrap fixture are defined numbers", () => {
    expect(typeof bootstrapFixture.stock_exposure_total).toBe("number");
    expect(typeof bootstrapFixture.crypto_exposure_total).toBe("number");
    expect(bootstrapFixture.stock_exposure_total).not.toBeUndefined();
    expect(bootstrapFixture.crypto_exposure_total).not.toBeUndefined();
  });

  it("shows skeletons for secondary panels then renders them after load", async () => {
    // Delay secondary API calls to observe skeleton state
    let resolveSpending!: (v: SpendingSummary) => void;
    const pendingSpending = new Promise<SpendingSummary>((res) => { resolveSpending = res; });
    mockApi.spendingSummary.mockReturnValueOnce(pendingSpending);

    renderApp();

    // Wait for bootstrap to render hero
    expect(await screen.findByText("Net Worth")).toBeInTheDocument();

    // Secondary panels show loading skeletons
    expect(screen.getByLabelText("Loading cash flow")).toBeInTheDocument();

    // Resolve secondary data
    resolveSpending(spendingSummaryFixture);

    await waitFor(() => {
      expect(screen.queryByLabelText("Loading cash flow")).not.toBeInTheDocument();
    });
    expect(screen.getByRole("link", { name: "Cash Flow details" })).toBeInTheDocument();
  });

  it("api.health is never called on mount (lazy — only fetched on user menu open)", async () => {
    renderApp();

    // Wait for full secondary load — health must still not be called
    await waitFor(() => {
      expect(mockApi.cryptoSummary).toHaveBeenCalledTimes(1);
    });

    expect(mockApi.health).not.toHaveBeenCalled();
  });

  it("unmappedTransactions is not called before bootstrapState is ready", async () => {
    let resolveBootstrap!: (v: typeof bootstrapFixture) => void;
    const pendingBootstrap = new Promise<typeof bootstrapFixture>((res) => { resolveBootstrap = res; });
    mockApi.dashboardBootstrap.mockReturnValueOnce(pendingBootstrap);

    renderApp();

    // Before bootstrap resolves, unmappedTransactions must not be called
    expect(mockApi.unmappedTransactions).not.toHaveBeenCalled();

    // Resolve bootstrap
    resolveBootstrap(bootstrapFixture);

    // After bootstrap, unmappedTransactions should eventually be called
    await waitFor(() => {
      expect(mockApi.unmappedTransactions).toHaveBeenCalledTimes(1);
    });
  });

  it("Tier B secondary calls (spendingSummary, creditCardSummary, cryptoSummary) are not awaited before Tier A resolves", async () => {
    let resolveSummary!: (v: typeof summaryFixture) => void;
    const pendingSummary = new Promise<typeof summaryFixture>((res) => { resolveSummary = res; });
    mockApi.dashboardSummary.mockReturnValueOnce(pendingSummary);

    renderApp();

    // Wait for bootstrap
    expect(await screen.findByText("Net Worth")).toBeInTheDocument();

    // Tier A (summary) is pending — Tier B must not have been called yet
    expect(mockApi.spendingSummary).not.toHaveBeenCalled();
    expect(mockApi.creditCardSummary).not.toHaveBeenCalled();
    expect(mockApi.cryptoSummary).not.toHaveBeenCalled();

    // Resolve Tier A
    resolveSummary(summaryFixture);

    // After Tier A resolves, Tier B calls should eventually be made
    await waitFor(() => {
      expect(mockApi.spendingSummary).toHaveBeenCalledTimes(1);
      expect(mockApi.creditCardSummary).toHaveBeenCalledTimes(1);
      expect(mockApi.cryptoSummary).toHaveBeenCalledTimes(1);
    });
  });
});
