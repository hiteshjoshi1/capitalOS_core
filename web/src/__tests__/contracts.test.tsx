import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import App from "../App";
import AppShell from "../components/AppShell";
import Sidebar from "../components/Sidebar";
import { ThemeProvider } from "../context/ThemeContext";
import { api } from "../lib/api";
import WealthOverview from "../routes/WealthOverview";
import WealthRisk from "../routes/WealthRisk";

vi.mock("../lib/api", () => ({
  api: {
    dashboardSummary: vi.fn(),
    dashboardGeographyExposure: vi.fn(),
    spendingSummary: vi.fn(),
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

function renderSidebar(initialPath = "/wealth") {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[initialPath]}>
        <Sidebar />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

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
    net_worth_as_of: "2026-02-06",
    net_worth_change: {
      vs_prev_month: {
        abs: 1500,
        pct: 0.015,
        current_as_of: "2026-02-06",
        compare_as_of: "2026-01-06",
        compare_month: "2026-01",
      },
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

  it("renders the app shell with the four primary sections and without Dashboard", () => {
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
    expect(screen.getByRole("link", { name: "Wealth" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Liabilities" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Operations" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Intelligence" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Dashboard" })).not.toBeInTheDocument();
    expect(screen.getByText("Wealth Content")).toBeInTheDocument();
  });

  it("keeps section tabs visible for Wealth and exposes the Risk tab", () => {
    renderSidebar("/risk");
    expect(screen.getByRole("link", { name: "Wealth" })).toHaveClass("sidebarLinkActive");
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

    expect(await screen.findByText("Portfolio Composition")).toBeInTheDocument();
    expect(screen.getByText("50.0%")).toBeInTheDocument();
    expect(screen.getAllByText("25.0%").length).toBeGreaterThan(0);
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

    expect(await screen.findByRole("heading", { name: "Risk" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Geographic Exposure" })).toBeInTheDocument();
  });
});
