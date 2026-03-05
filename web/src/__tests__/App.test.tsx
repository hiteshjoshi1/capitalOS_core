import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import App from "../App";
import { api } from "../lib/api";
import type { DashboardSummary, PlatformAllocation, SpendingSummary, CreditCardSummary, CryptoSummary, StockExposure } from "../lib/api";

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
  geography: [],
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
});

describe("App", () => {
  it("renders the happy path dashboard data", async () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>
    );

    expect(await screen.findByText("Net Worth")).toBeInTheDocument();
    expect(screen.getByText("CapitalOS — Dashboard")).toBeInTheDocument();

    expect(screen.getByLabelText("Month")).toBeInTheDocument();

    expect(screen.getByText(/S\$ 742,180/)).toBeInTheDocument();
    expect(screen.getByText("Cash Flow — 2026-02")).toBeInTheDocument();
    expect(screen.getByText(/S\$ 12,480/)).toBeInTheDocument();
    expect(screen.getByText(/S\$ 8,710/)).toBeInTheDocument();
    expect(screen.getByText(/30%/)).toBeInTheDocument();

    expect(screen.getByText("Expenses — Credit Cards")).toBeInTheDocument();
    expect(screen.getByText("DBS Altitude")).toBeInTheDocument();
    expect(screen.getByText("Stock Exposure")).toBeInTheDocument();
    expect(screen.getByText("Cash Exposure")).toBeInTheDocument();
    expect(screen.getByText("Crypto Exposure")).toBeInTheDocument();
    expect(screen.getByText("Total ETH")).toBeInTheDocument();
    expect(screen.getByText("Total SOL")).toBeInTheDocument();
    expect(screen.getByText("Stock Exposure")).toBeInTheDocument();
    expect(screen.getByText("By country")).toBeInTheDocument();
    expect(screen.getByText("By platform")).toBeInTheDocument();
    expect(screen.getByText("Expense Breakdown")).toBeInTheDocument();
    expect(screen.getByText("Allocation by Geography")).toBeInTheDocument();
    expect(screen.getByText("Allocation by Platform")).toBeInTheDocument();
    expect(screen.getAllByText("IBKR").length).toBeGreaterThan(0);
    expect(screen.getByText(/70.0%/)).toBeInTheDocument();
    expect(screen.getByText("TSLA — 24.3%")).toBeInTheDocument();
    expect(screen.getByText("80.8%")).toBeInTheDocument();
    expect(screen.queryByText(/Mocked: risk analysis/i)).not.toBeInTheDocument();
    expect(screen.getByText("Trends (Monthly)")).toBeInTheDocument();
  });

  it("renders API error state when requests fail", async () => {
    mockApi.health.mockRejectedValueOnce(new Error("Network down"));

    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>
    );

    expect(await screen.findByText("API error")).toBeInTheDocument();
    expect(screen.getByText(/Network down/)).toBeInTheDocument();
  });
});
