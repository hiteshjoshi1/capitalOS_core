import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import type { ReactElement } from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { ThemeProvider } from "../context/ThemeContext";
import AppShell from "../components/AppShell";
import WealthOverview from "../routes/WealthOverview";
import Loans from "../routes/Loans";
import Companies from "../routes/Companies";
import AISage from "../routes/AISage";
import Settings from "../routes/Settings";
import Platforms from "../routes/Platforms";

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
        liabilities: 0,
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
    uploadReminderCount: vi.fn().mockResolvedValue({ count: 0 }),
    platforms: vi.fn().mockResolvedValue([]),
    platformOptions: vi.fn().mockResolvedValue({
      platform_types: ["BANK", "BROKER"],
      countries: ["SG", "US"],
      country_pattern: "^[A-Z]{2,3}$",
    }),
    createPlatform: vi.fn(),
  },
}));

describe("AppShell", () => {
  it("renders sidebar alongside outlet content", () => {
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

    // Sidebar present (aside = complementary role)
    expect(screen.getByRole("complementary", { name: "Main navigation" })).toBeInTheDocument();

    // Outlet content rendered
    expect(screen.getByText("Dashboard Content")).toBeInTheDocument();
  });

  it("renders sidebar nav with Dashboard link", () => {
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/" element={<div>Content</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("keeps sidebar width at 272px for dashboard mockup parity", () => {
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
    { path: "/loans", component: <Loans />, heading: "Loans" },
    { path: "/companies", component: <Companies />, heading: "Companies" },
    { path: "/ai-sage", component: <AISage />, heading: "Hello there" },
    { path: "/settings", component: <Settings />, heading: "Settings" },
    { path: "/platforms", component: <Platforms />, heading: "Platforms" },
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
