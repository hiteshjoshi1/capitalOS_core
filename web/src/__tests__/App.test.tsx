import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import App from "../App";
import { api } from "../lib/api";
import type { Account, DashboardSummary, Platform } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    health: vi.fn(),
    platforms: vi.fn(),
    accounts: vi.fn(),
    dashboardSummary: vi.fn(),
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

const platformsFixture: Platform[] = [
  { id: 1, code: "DBS", name: "DBS Bank", platform_type: "BANK", country: "SG", website: null },
  { id: 2, code: "IBKR", name: "Interactive Brokers", platform_type: "BROKER", country: "US", website: null },
];

const accountsFixture: Account[] = [
  {
    id: 1,
    name: "DBS Savings",
    platform: "DBS",
    platform_id: 1,
    account_type: "BANK",
    currency: "SGD",
    country: "SG",
  },
];

beforeEach(() => {
  mockApi.health.mockResolvedValue({ status: "ok" });
  mockApi.platforms.mockResolvedValue(platformsFixture);
  mockApi.accounts.mockResolvedValue(accountsFixture);
  mockApi.dashboardSummary.mockResolvedValue(summaryFixture);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("App", () => {
  it("renders the happy path dashboard data", async () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>
    );

    expect(await screen.findByText("Net Worth")).toBeInTheDocument();
    expect(screen.getByText("CapitalOS")).toBeInTheDocument();

    expect(screen.getByLabelText("Month")).toBeInTheDocument();

    expect(screen.getByText(/S\$ 742,180/)).toBeInTheDocument();
    expect(screen.getByText(/Income: S\$ 8,200/)).toBeInTheDocument();
    expect(screen.getByText(/Expenses: S\$ 5,300/)).toBeInTheDocument();
    expect(screen.getByText(/Savings rate: 35%/)).toBeInTheDocument();

    const holdingsSection = screen.getByText("Top Holdings").closest(".card");
    expect(holdingsSection).not.toBeNull();
    if (holdingsSection) {
      const table = within(holdingsSection).getByRole("table");
      expect(within(table).getByText("AAPL")).toBeInTheDocument();
      expect(within(table).getByText("BTC")).toBeInTheDocument();
    }

    const platformsSection = screen.getByText("Platforms (Reference)").closest(".card");
    expect(platformsSection).not.toBeNull();
    if (platformsSection) {
      const table = within(platformsSection).getByRole("table");
      expect(within(table).getByText("DBS", { selector: "code" })).toBeInTheDocument();
      expect(within(table).getByText("IBKR", { selector: "code" })).toBeInTheDocument();
    }

    const accountsSection = screen.getByText("Accounts (Configured)").closest(".card");
    expect(accountsSection).not.toBeNull();
    if (accountsSection) {
      const table = within(accountsSection).getByRole("table");
      expect(within(table).getByText("DBS Savings", { selector: "td" })).toBeInTheDocument();
      expect(within(accountsSection).getByText("SGD")).toBeInTheDocument();
    }
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
