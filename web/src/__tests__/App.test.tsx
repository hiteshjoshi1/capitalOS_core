import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import App from "../App";
import { api } from "../lib/api";
import type { DashboardSummary, PlatformAllocation, SpendingSummary, CreditCardSummary } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    health: vi.fn(),
    dashboardSummary: vi.fn(),
    platformAllocation: vi.fn(),
    spendingSummary: vi.fn(),
    creditCardSummary: vi.fn(),
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
    { asset_id: 1, symbol: "AAPL", asset_class: "STOCK", value: 50000, percent_of_networth: 6.7 },
    { asset_id: 2, symbol: "BTC", asset_class: "CRYPTO", value: 20000, percent_of_networth: 2.7 },
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

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-02-17T00:00:00Z"));
  mockApi.health.mockResolvedValue({ status: "ok" });
  mockApi.dashboardSummary.mockResolvedValue(summaryFixture);
  mockApi.platformAllocation.mockResolvedValue(platformAllocationFixture);
  mockApi.spendingSummary.mockResolvedValue(spendingSummaryFixture);
  mockApi.creditCardSummary.mockResolvedValue(creditCardSummaryFixture);
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

    const holdingsSection = screen.getByText("Top Holdings").closest(".card");
    expect(holdingsSection).not.toBeNull();
    if (holdingsSection) {
      const table = within(holdingsSection).getByRole("table");
      expect(within(table).getByText("AAPL")).toBeInTheDocument();
      expect(within(table).getByText("BTC")).toBeInTheDocument();
    }

    expect(screen.getByText("Expenses — Credit Cards")).toBeInTheDocument();
    expect(screen.getByText("DBS Altitude")).toBeInTheDocument();
    expect(screen.getByText("Expense Breakdown")).toBeInTheDocument();
    expect(screen.getByText("Allocation by Geography")).toBeInTheDocument();
    expect(screen.getByText("Allocation by Platform")).toBeInTheDocument();
    expect(screen.getByText("IBKR")).toBeInTheDocument();
    expect(screen.getByText(/70.0%/)).toBeInTheDocument();
    expect(screen.getByText("Trends (Monthly)")).toBeInTheDocument();
    expect(screen.getByText("Top Holdings (Overall)")).toBeInTheDocument();
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
