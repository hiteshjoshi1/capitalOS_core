import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import App from "../App";
import type { DashboardBootstrap, DashboardSummary } from "../lib/api";
import AppShell from "../components/AppShell";
import Sidebar from "../components/Sidebar";
import { ThemeProvider } from "../context/ThemeContext";
import { api } from "../lib/api";
import WealthOverview from "../routes/WealthOverview";

vi.mock("../lib/api", () => ({
  api: {
    dashboardBootstrap: vi.fn(),
    dashboardSummary: vi.fn(),
    dashboardGeographyExposure: vi.fn(),
    spendingSummary: vi.fn(),
    unmappedTransactions: vi.fn(),
    uploadReminderCount: vi.fn().mockResolvedValue({ count: 0 }),
  },
}));

function renderSidebar(initialPath = "/") {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[initialPath]}>
        <Sidebar />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

function renderDashboard() {
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
  vi.mocked(api.unmappedTransactions).mockResolvedValue([]);

  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

function renderWealthOverview() {
  const mockSummary: DashboardSummary = {
    as_of_month: "2026-02",
    base_currency: "SGD",
    snapshot_day: null,
    net_worth_as_of: "2026-02-06",
    net_worth_change: null,
    cash_percent: 25,
    net_worth: {
      total: 100000,
      cash: 25000,
      stocks_funds: 50000,
      crypto: 25000,
      liabilities: 0,
    },
    geography: [],
    cash_flow: {
      income: 0,
      expenses: 0,
      net: 0,
      savings_rate: null,
    },
    top_holdings: [
      { asset_id: 1, symbol: "AAPL", asset_class: "STOCK", value: 22000, percent_of_networth: 22 },
      { asset_id: 2, symbol: "TSLA", asset_class: "STOCK", value: 15000, percent_of_networth: 15 },
      { asset_id: 3, symbol: "ETH", asset_class: "CRYPTO", value: 12000, percent_of_networth: 12 },
    ],
    cash_balances: [{ currency: "SGD", value: 25000 }],
  };
  vi.mocked(api.dashboardSummary).mockResolvedValue(mockSummary);
  vi.mocked(api.dashboardGeographyExposure).mockResolvedValue({
    as_of: "2026-02-06",
    base_currency: "SGD",
    total: 100000,
    items: [
      { country: "US", stocks_funds: 50000, cash: 0, crypto: 25000, total: 75000, percent: 75 },
      { country: "SG", stocks_funds: 0, cash: 25000, crypto: 0, total: 25000, percent: 25 },
    ],
  });

  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={["/wealth"]}>
        <Routes>
          <Route path="/wealth" element={<WealthOverview />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe("frontend contracts", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
    vi.mocked(api.dashboardSummary).mockResolvedValue({
      as_of_month: "2026-02",
      base_currency: "SGD",
      snapshot_day: null,
      net_worth_as_of: "2026-02-06",
      net_worth_change: null,
      cash_percent: 25,
      net_worth: {
        total: 100000,
        cash: 25000,
        stocks_funds: 50000,
        crypto: 25000,
        liabilities: 0,
      },
      geography: [],
      cash_flow: { income: 0, expenses: 0, net: 0, savings_rate: null },
      top_holdings: [],
      cash_balances: [],
    });
    vi.mocked(api.dashboardGeographyExposure).mockResolvedValue({
      as_of: "2026-02-06",
      base_currency: "SGD",
      total: 100000,
      items: [],
    });
  });

  it("renders app shell with navigation landmark and dashboard link", () => {
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/" element={<div>Dashboard Content</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(screen.getByRole("complementary", { name: "Main navigation" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByText("Dashboard Content")).toBeInTheDocument();
  });

  it("keeps sidebar contracts stable for operations visibility and theme toggle naming", async () => {
    const user = userEvent.setup();
    renderSidebar("/");

    const operationsToggle = screen.getByRole("button", { name: /Operations/i });
    expect(operationsToggle).toHaveAttribute("aria-expanded", "false");

    await user.click(operationsToggle);
    expect(screen.getByRole("link", { name: "Accounts" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Platforms" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Crypto Wallets" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ingest" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Market Data" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Toggle theme" })).toBeInTheDocument();
  });

  it("keeps dashboard thin and action-oriented", async () => {
    renderDashboard();

    expect(await screen.findByText("Net Worth")).toBeInTheDocument();
    expect(screen.getByLabelText("Action queue")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Stocks & Funds details" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Crypto details" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Cash details" })).not.toBeInTheDocument();
  });

  it("shows stocks/crypto/cash cards and risk concentration in Wealth Overview", async () => {
    renderWealthOverview();

    expect(await screen.findByRole("link", { name: "Stocks & Funds details" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Crypto details" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Cash details" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Risk" })).toBeInTheDocument();
  });
});
