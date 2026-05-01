import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import type { ReactElement } from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { ThemeProvider } from "../context/ThemeContext";
import AppShell from "../components/AppShell";
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
      net_worth_as_of: "2026-02-06",
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

    expect(screen.getByRole("heading", { name: "Wealth" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Overview" })).toHaveClass("appShellTabActive");
    expect(screen.getByRole("link", { name: "Stocks" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Risk" })).toBeInTheDocument();
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

    expect(screen.getByRole("heading", { name: "Liabilities" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Credit Cards" })).toHaveClass("appShellTabActive");
    expect(screen.getByRole("link", { name: "Loans" })).toBeInTheDocument();
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
    { path: "/risk", component: <WealthRisk />, heading: "Wealth Risk" },
    { path: "/liabilities", component: <LiabilitiesOverview />, heading: "Liabilities Overview" },
    { path: "/operations", component: <OperationsOverview />, heading: "Operations Overview" },
    { path: "/intelligence", component: <IntelligenceOverview />, heading: "Intelligence Overview" },
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
