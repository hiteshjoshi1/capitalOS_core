import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import type { ReactElement } from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { ThemeProvider } from "../context/ThemeContext";
import AppShell from "../components/AppShell";
import CashFlowDetail from "../routes/CashFlowDetail";
import WealthOverview from "../routes/WealthOverview";
import WealthRisk from "../routes/WealthRisk";
import LiabilitiesOverview from "../routes/LiabilitiesOverview";
import OperationsOverview from "../routes/OperationsOverview";
import IntelligenceOverview from "../routes/IntelligenceOverview";

vi.mock("../lib/api", () => ({
  api: {
    dashboardSummary: vi.fn().mockResolvedValue({
      as_of_month: "2026-02",
      base_currency: "SGD",
      snapshot_day: null,
      net_worth_as_of: "2026-03-01T00:00:00+00:00",
      net_worth_snapshot_as_of: "2026-02-06T00:00:00+00:00",
      net_worth_boundary_at: "2026-03-01T00:00:00+00:00",
      net_worth_boundary_exact: false,
      net_worth_freshness_status: "synthetic",
      net_worth_change: null,
      cash_percent: 25,
      net_worth: {
        total: 100000,
        cash: 25000,
        stocks_funds: 50000,
        crypto: 25000,
        liabilities: -10000,
      },
      geography: [],
      cash_flow: { income: 0, expenses: 0, net: 0, savings_rate: null },
      top_holdings: [],
      cash_balances: [],
    }),
    dashboardGeographyExposure: vi.fn().mockResolvedValue({
      as_of: "2026-02-06",
      base_currency: "SGD",
      total: 100000,
      items: [],
    }),
    platformAllocation: vi.fn().mockResolvedValue({
      as_of: "2026-03-01T00:00:00+00:00",
      total: 100000,
      items: [],
    }),
    spendingSummary: vi.fn().mockResolvedValue({
      month: "2026-02",
      base_currency: "SGD",
      income_total: 0,
      expense_total: 0,
      net: 0,
      savings_rate: null,
      income_categories: [],
      expense_categories: [],
    }),
    categories: vi.fn().mockResolvedValue([
      { id: 100, code: "income", name: "Income", parent_id: null, display_order: 10 },
      { id: 101, code: "income_salary", name: "Salary", parent_id: 100, display_order: 11 },
    ]),
    cashFlowDetail: vi.fn().mockResolvedValue({
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
    }),
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

describe("AppShell", () => {
  it("renders sidebar alongside outlet content", () => {
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/wealth"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/wealth" element={<div>Overview Content</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(screen.getByRole("complementary", { name: "Main navigation" })).toBeInTheDocument();
    expect(screen.getByText("Overview Content")).toBeInTheDocument();
  });

  it("renders shell tabs for the active section", () => {
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/wealth"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/wealth" element={<div>Overview Content</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(screen.getByRole("link", { name: "Overview" })).toHaveClass("appShellTabActive");
    expect(screen.getByRole("link", { name: "Stocks" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Risk" })).toBeInTheDocument();
  });

  it("renders cash-flow tabs for the dedicated cash-flow section", () => {
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/cash-flow"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/cash-flow" element={<div>Cash Flow Content</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(screen.getByRole("link", { name: "Overview" })).toHaveClass("appShellTabActive");
    expect(screen.getByRole("link", { name: "Income" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Expenses" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Map Transactions" })).toBeInTheDocument();
  });

  it("renders liabilities tabs on liabilities routes", () => {
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/credit-cards"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/credit-cards" element={<div>Cards</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(screen.getByRole("link", { name: "Credit Cards" })).toHaveClass("appShellTabActive");
    expect(screen.getByRole("link", { name: "Loans" })).toBeInTheDocument();
  });

  it("renders wealth page controls inside the shell top bar", async () => {
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/wealth"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/wealth" element={<WealthOverview />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByRole("link", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByLabelText("Month")).toBeInTheDocument();
    expect(screen.getByLabelText("Base currency")).toBeInTheDocument();
  });

  it("keeps sidebar width at 272px for shell layout stability", () => {
    const appCss = readFileSync(resolve(process.cwd(), "src/App.css"), "utf8");
    expect(appCss).toContain(".sidebar {");
    expect(appCss).toContain("width: 272px;");
    expect(appCss).toContain("min-width: 272px;");
  });

  it("renders content inside appShellMain alongside sidebar", () => {
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/some-page"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/some-page" element={<div data-testid="page-content">Page</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(screen.getByTestId("page-content")).toBeInTheDocument();
    const main = screen.getByRole("main");
    expect(main).toBeInTheDocument();
    expect(main).toContainElement(screen.getByTestId("page-content"));
  });
});

describe("Placeholder route smoke tests", () => {
  const routes: { path: string; component: ReactElement; heading: string }[] = [
    { path: "/wealth", component: <WealthOverview />, heading: "Wealth Overview" },
    { path: "/cash-flow", component: <CashFlowDetail />, heading: "Cash Flow Overview" },
    { path: "/risk", component: <WealthRisk />, heading: "Wealth Risk" },
    { path: "/liabilities", component: <LiabilitiesOverview />, heading: "Liabilities" },
    { path: "/operations", component: <OperationsOverview />, heading: "Data Hub" },
    { path: "/intelligence", component: <IntelligenceOverview />, heading: "Research" },
  ];

  routes.forEach(({ path, component, heading }) => {
    it(`renders ${heading} at ${path} without throwing`, () => {
      render(
        <ThemeProvider>
          <MemoryRouter initialEntries={[path]}>
            <Routes>
              <Route element={<AppShell />}>
                <Route path={path} element={component} />
              </Route>
            </Routes>
          </MemoryRouter>
        </ThemeProvider>,
      );

      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    });
  });
});
