import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import App from "../App";
import AppShell from "../components/AppShell";
import { ThemeProvider } from "../context/ThemeContext";
import { api } from "../lib/api";
import CashFlowDetail from "../routes/CashFlowDetail";
import WealthOverview from "../routes/WealthOverview";
import WealthRisk from "../routes/WealthRisk";

vi.mock("../lib/api", () => ({
  api: {
    dashboardSummary: vi.fn(),
    dashboardGeographyExposure: vi.fn(),
    platformAllocation: vi.fn(),
    spendingSummary: vi.fn(),
    categories: vi.fn(),
    cashFlowDetail: vi.fn(),
    categoryOverride: vi.fn(),
    uploadReminderCount: vi.fn().mockResolvedValue({ count: 0 }),
    alertNotifications: vi.fn().mockResolvedValue({
      upload_reminders: [],
      system_notifications: [],
      total_count: 0,
    }),
  },
}));

vi.mock("../lib/realtime", () => ({
  subscribeToRealtimeTopic: vi.fn().mockReturnValue(() => {}),
}));

function renderRootRedirect() {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<App />} />
          <Route path="/wealth" element={<div>Wealth landing</div>} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

function mockWealthApis() {
  vi.mocked(api.dashboardSummary).mockResolvedValue({
    as_of_month: "2026-02",
    base_currency: "SGD",
    snapshot_day: null,
    net_worth_as_of: "2026-03-01T00:00:00+00:00",
    net_worth_snapshot_as_of: "2026-02-06T00:00:00+00:00",
    net_worth_boundary_at: "2026-03-01T00:00:00+00:00",
    net_worth_boundary_exact: false,
    net_worth_freshness_status: "synthetic",
    net_worth_change: {
      vs_prev_month: {
        abs: 1500,
        pct: 0.015,
        current_as_of: "2026-03-01T00:00:00+00:00",
        compare_as_of: "2026-01-06",
        compare_month: "2026-01",
      },
    },
    net_worth_component_change: {
      cash: { abs: 500, pct: 0.02, current_as_of: "2026-03-01T00:00:00+00:00", compare_as_of: "2026-01-06", compare_month: "2026-01" },
      stocks_funds: { abs: 1000, pct: 0.02, current_as_of: "2026-03-01T00:00:00+00:00", compare_as_of: "2026-01-06", compare_month: "2026-01" },
      crypto: { abs: 0, pct: 0, current_as_of: "2026-03-01T00:00:00+00:00", compare_as_of: "2026-01-06", compare_month: "2026-01" },
    },
    top_movers: {
      compare_month: "2026-01",
      gainers: [
        {
          asset_id: 1,
          symbol: "AAPL",
          asset_class: "STOCK",
          current_value: 22000,
          previous_value: 20000,
          delta_abs: 2000,
          delta_pct: 0.1,
          compare_month: "2026-01",
        },
      ],
      detractors: [
        {
          asset_id: 2,
          symbol: "BTC",
          asset_class: "CRYPTO",
          current_value: 12000,
          previous_value: 15000,
          delta_abs: -3000,
          delta_pct: -0.2,
          compare_month: "2026-01",
        },
      ],
    },
    cash_percent: 25,
    net_worth: {
      total: 100000,
      cash: 25000,
      stocks_funds: 50000,
      crypto: 25000,
      liabilities: -5000,
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
      { asset_id: 2, symbol: "BTC", asset_class: "CRYPTO", value: 12000, percent_of_networth: 12 },
    ],
    cash_balances: [{ currency: "SGD", value: 25000 }],
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
  vi.mocked(api.dashboardGeographyExposure).mockResolvedValue({
    as_of: "2026-02-06",
    base_currency: "SGD",
    total: 100000,
    items: [
      { country: "US", stocks_funds: 50000, cash: 0, crypto: 15000, total: 65000, percent: 65 },
    ],
  });
  vi.mocked(api.platformAllocation).mockResolvedValue({
    as_of: "2026-03-01T00:00:00+00:00",
    total: 100000,
    items: [
      { platform: "IBKR", platform_type: "BROKER", country: "US", value: 50000, percent: 50 },
      { platform: "CRYPTO", platform_type: "WALLET_PROVIDER", country: null, value: 25000, percent: 25 },
      { platform: "DBS", platform_type: "BANK", country: "SG", value: 25000, percent: 25 },
    ],
  });
  vi.mocked(api.categories).mockResolvedValue([
    { id: 100, code: "income", name: "Income", parent_id: null, display_order: 10 },
    { id: 101, code: "income_salary", name: "Salary", parent_id: 100, display_order: 11 },
  ]);
  vi.mocked(api.cashFlowDetail).mockResolvedValue({
    month: "2026-02",
    base_currency: "SGD",
    income_total: 5000,
    expense_total: 3000,
    net: 2000,
    savings_rate: 0.4,
    calculation: "Net = income_total - expense_total using deterministic month-scoped transactions.",
    analytics: {
      burn_rate: 0.6,
      prior_month: "2026-01",
      prior_month_net: 1500,
      free_cash_flow_change_vs_prior_month: 500,
      outflow_categories: [{ label: "Rent", amount: 1800, percent: 0.6 }],
      inflow_categories: [{ label: "Salary", amount: 5000, percent: 1 }],
      outflow_recurring_split: [{ label: "Recurring", amount: 1800, percent: 0.6 }],
      inflow_recurring_split: [{ label: "Recurring", amount: 5000, percent: 1 }],
      outflow_fixed_variable_split: [{ label: "Fixed", amount: 1800, percent: 0.6 }],
      inflow_source_mix: [{ label: "Salary", amount: 5000, percent: 1 }],
      top_outflow_merchants: [{ merchant: "Landlord", amount: 1800, percent: 0.6, transaction_count: 1 }],
      largest_inflow_drivers: [{ label: "Salary", amount: 5000, percent: 1 }],
      outflow_category_deltas: [{ label: "Rent", current_amount: 1800, prior_amount: 1600, delta_amount: 200, delta_percent: 0.125, direction: "deteriorated" }],
      deterioration_drivers: [{ label: "Rent", current_amount: -1800, prior_amount: -1600, delta_amount: -200, delta_percent: 0.125, direction: "deteriorated" }],
      trend: [{ month: "2026-02", inflows: 5000, outflows: 3000, net: 2000, savings_rate: 0.4, burn_rate: 0.6 }],
      waterfall: {
        starting_cash: 10000,
        snapshot_start_as_of: "2026-01-31T00:00:00+00:00",
        inflows: 5000,
        outflows: 3000,
        transfers_and_funding: 0,
        investment_and_fx_effects: 0,
        other_cash_movements: 0,
        snapshot_end_as_of: "2026-02-28T00:00:00+00:00",
        snapshot_start_boundary_at: "2026-01-31T00:00:00+00:00",
        snapshot_end_boundary_at: "2026-02-28T00:00:00+00:00",
        boundary_exact: true,
        availability_message: null,
        ending_cash: 12000,
      },
      answers: [{ question: "Where did my money go this month?", answer: "Mostly to Rent." }],
    },
    income: { total: 5000, transaction_count: 1, included_types: ["INCOME"], transactions: [] },
    expenses: { total: 3000, transaction_count: 1, included_types: ["EXPENSE"], transactions: [] },
  });
}

describe("frontend contracts", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
    mockWealthApis();
  });

  it("redirects the root route to Wealth", async () => {
    renderRootRedirect();
    expect(await screen.findByText("Wealth landing")).toBeInTheDocument();
  });

  it("renders the app shell with the primary sections and without Dashboard", () => {
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/wealth"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/wealth" element={<div>Wealth Content</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(screen.getByRole("complementary", { name: "Main navigation" })).toBeInTheDocument();
    const sidebar = screen.getByRole("complementary", { name: "Main navigation" });
    expect(within(sidebar).getByRole("link", { name: "Wealth" })).toBeInTheDocument();
    expect(within(sidebar).getByRole("link", { name: "Cash Flow" })).toBeInTheDocument();
    expect(within(sidebar).getByRole("link", { name: "Liabilities" })).toBeInTheDocument();
    expect(within(sidebar).getByRole("link", { name: "Data Hub" })).toBeInTheDocument();
    expect(within(sidebar).getByRole("link", { name: "Research" })).toBeInTheDocument();
    expect(within(sidebar).queryByRole("link", { name: "Dashboard" })).not.toBeInTheDocument();
    expect(screen.getByText("Wealth Content")).toBeInTheDocument();
  });

  it("keeps wealth tabs visible without nesting Cash Flow inside Wealth", () => {
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/risk"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/risk" element={<div>Risk page</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    const sidebar = screen.getByRole("complementary", { name: "Main navigation" });
    expect(within(sidebar).getByRole("link", { name: "Wealth" })).toHaveClass("sidebarLinkActive");
    expect(within(screen.getByRole("navigation", { name: "Wealth tabs" })).queryByRole("link", { name: "Cash Flow" })).not.toBeInTheDocument();
  });

  it("renders Wealth Overview with composition percentages and without the action queue", async () => {
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/wealth"]}>
          <Routes>
            <Route path="/wealth" element={<WealthOverview />} />
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    // New allocation section
    expect(await screen.findByText("Where the money sits")).toBeInTheDocument();
    expect(screen.queryByText("Upload reminders")).not.toBeInTheDocument();
    expect(screen.queryByText("Statement coverage")).not.toBeInTheDocument();
    // Net worth change renders (vs_prev_month abs=1500)
    expect(screen.getAllByText(/\+S\$ 1,500/).length).toBeGreaterThan(0);
    // Holdings card shows positions
    expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
    expect(screen.getAllByText("BTC").length).toBeGreaterThan(0);
    // Platform allocation percentages (IBKR 50%, CRYPTO 25%)
    expect(screen.getAllByText("50.0%").length).toBeGreaterThan(0);
    expect(screen.getAllByText("25.0%").length).toBeGreaterThan(0);
    // Holdings/Movers toggle is present
    expect(screen.getByRole("group", { name: "Holdings view" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Action queue")).not.toBeInTheDocument();
  });

  it("renders Wealth Risk with risk and geographic exposure together", async () => {
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/risk"]}>
          <Routes>
            <Route path="/risk" element={<WealthRisk />} />
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByRole("heading", { name: "Largest position" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Where the wealth is booked" })).toBeInTheDocument();
  });

  it("renders Cash Flow as a dedicated workspace route", async () => {
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/cash-flow"]}>
          <Routes>
            <Route path="/cash-flow" element={<CashFlowDetail />} />
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("Net cash flow this month")).toBeInTheDocument();
    expect(screen.getByLabelText("Net cash flow trend by month")).toBeInTheDocument();
  });
});
