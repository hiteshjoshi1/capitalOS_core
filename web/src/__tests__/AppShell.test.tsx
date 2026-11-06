import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../lib/api";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { lazy, type ReactElement } from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { ThemeProvider } from "../context/ThemeContext";
import AppShell from "../components/AppShell";
import CashFlowDetail from "../routes/CashFlowDetail";
import WealthOverview from "../routes/WealthOverview";
import WealthRisk from "../routes/WealthRisk";
import LiabilitiesOverview from "../routes/LiabilitiesOverview";
import OperationsOverview from "../routes/OperationsOverview";

vi.mock("../lib/api", () => ({
  api: {
    dashboardBootstrap: vi.fn().mockResolvedValue({
      as_of_month: "2026-02",
      base_currency: "SGD",
      snapshot_day: null,
      current_net_worth_as_of: "2026-03-01T00:00:00+00:00",
      current_net_worth: {
        total: 100000,
        cash: 25000,
        stocks_funds: 50000,
        crypto: 25000,
        liabilities: -10000,
      },
      current_net_worth_freshness: {
        stocks: { most_recent_at: "2026-03-01T00:00:00+00:00", most_recent_label: "AAPL", stalest_at: "2026-03-01T00:00:00+00:00", stalest_label: "AAPL" },
        crypto: { most_recent_at: "2026-03-01", most_recent_label: "Wallet", stalest_at: "2026-03-01", stalest_label: "Wallet" },
        cash: { most_recent_at: "2026-03-01", most_recent_label: "DBS", stalest_at: "2026-03-01", stalest_label: "DBS" },
      },
      net_worth_as_of: "2026-03-01T00:00:00+00:00",
      net_worth_snapshot_as_of: "2026-02-06T00:00:00+00:00",
      net_worth_boundary_at: "2026-03-01T00:00:00+00:00",
      net_worth_boundary_exact: false,
      net_worth_freshness_status: "synthetic",
      net_worth: {
        total: 100000,
        cash: 25000,
        stocks_funds: 50000,
        crypto: 25000,
        liabilities: -10000,
      },
      stock_exposure_total: 50000,
      crypto_exposure_total: 25000,
      cash_percent: 25,
    }),
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
    alertNotificationsCount: vi.fn().mockResolvedValue({ total_count: 0 }),
    alertNotifications: vi.fn().mockResolvedValue({
      upload_reminders: [],
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

  it("renders no sub-tabs on the merged liabilities page", () => {
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/liabilities"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/liabilities" element={<div>Liabilities</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(screen.queryByRole("link", { name: "Credit Cards" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Loans" })).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Liabilities tabs" })).toBeEmptyDOMElement();
  });

  it("renders the wealth page month and currency controls inside the shell top bar", async () => {
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
    expect(screen.getByLabelText("Base currency")).toBeInTheDocument();
    // #223: Wealth Overview follows the shared selected month, with the month pill.
    expect(screen.getByLabelText("Month")).toBeInTheDocument();
  });

  it("keeps sidebar width at 248px for shell layout stability", () => {
    const appCss = readFileSync(resolve(process.cwd(), "src/App.css"), "utf8");
    expect(appCss).toContain(".sidebar {");
    expect(appCss).toContain("width: 248px;");
    expect(appCss).toContain("min-width: 248px;");
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

  it("keeps the shell on screen with a loading card while a lazy route loads (#145)", async () => {
    let resolveRoute: (mod: { default: () => ReactElement }) => void = () => {};
    const LazyPage = lazy(
      () =>
        new Promise<{ default: () => ReactElement }>((resolve) => {
          resolveRoute = resolve;
        }),
    );
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/lazy-page"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/lazy-page" element={<LazyPage />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    const main = screen.getByRole("main");
    expect(screen.getByRole("complementary", { name: "Main navigation" })).toBeInTheDocument();
    expect(main).toContainElement(screen.getByText("Loading…"));

    await act(async () => {
      resolveRoute({ default: () => <div>Lazy Page Content</div> });
    });
    expect(await screen.findByText("Lazy Page Content")).toBeInTheDocument();
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
  });
});

describe("AppShell route content (#148)", () => {
  it("keeps Cash Flow mounted across its tabs: no refetch, same data", async () => {
    vi.mocked(api.cashFlowDetail).mockClear();
    vi.mocked(api.categories).mockClear();
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/cash-flow"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/cash-flow" element={<CashFlowDetail />} />
              <Route path="/cash-flow/income" element={<CashFlowDetail />} />
              <Route path="/cash-flow/expenses" element={<CashFlowDetail />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );
    expect(await screen.findByRole("heading", { name: "Cash Flow Overview" })).toBeInTheDocument();
    expect(await screen.findByText("Net cash flow this month")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("link", { name: "Income" }));
    expect(await screen.findByRole("heading", { name: "Income" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Expenses" }));
    expect(await screen.findByRole("heading", { name: "Expenses" })).toBeInTheDocument();

    expect(api.cashFlowDetail).toHaveBeenCalledTimes(1);
    expect(api.categories).toHaveBeenCalledTimes(1);
  });
});

describe("AppShell accessibility (#151)", () => {
  function renderShell(child: ReactElement = <div>Overview Content</div>) {
    return render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/wealth"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/wealth" element={child} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );
  }

  it("has a skip link to the page content", () => {
    renderShell();
    const skip = screen.getByRole("link", { name: "Skip to content" });
    expect(skip).toHaveAttribute("href", "#main-content");
    expect(document.getElementById("main-content")).toContainElement(screen.getByText("Overview Content"));
  });

  it("marks the active theme with aria-pressed", async () => {
    renderShell();
    const group = screen.getByRole("group", { name: "Theme" });
    const light = within(group).getByRole("button", { name: "Light" });
    const dark = within(group).getByRole("button", { name: "Dark" });
    await userEvent.click(light);
    expect(light).toHaveAttribute("aria-pressed", "true");
    expect(dark).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(dark);
    expect(dark).toHaveAttribute("aria-pressed", "true");
    expect(light).toHaveAttribute("aria-pressed", "false");
  });

  it("a page that throws while rendering shows an error card, not a blank app", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    function Broken(): ReactElement {
      throw new Error("boom");
    }
    renderShell(<Broken />);
    expect(screen.getByRole("alert")).toHaveTextContent("This page failed to load");
    expect(screen.getByRole("complementary", { name: "Main navigation" })).toBeInTheDocument();
    spy.mockRestore();
  });
});

describe("AppShell on a phone-width screen (#239)", () => {
  const originalMatchMedia = window.matchMedia;

  beforeEach(() => {
    // Only the shell's narrow query matches, as on a 375px phone.
    window.matchMedia = ((query: string) => ({
      matches: query === "(max-width: 980px)",
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
  });

  afterEach(() => {
    window.matchMedia = originalMatchMedia;
  });

  function renderPhoneShell(path: string, child: ReactElement) {
    return render(
      <ThemeProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path={path} element={child} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );
  }

  it("puts the page's month and currency controls under its title, not in the top bar", async () => {
    const { container } = renderPhoneShell("/wealth", <WealthOverview />);
    const month = await screen.findByLabelText("Month");
    expect(screen.getAllByLabelText("Month")).toHaveLength(1);
    const topbar = container.querySelector(".appShellTopbar") as HTMLElement;
    expect(topbar).not.toContainElement(month);
    const pageHeader = container.querySelector(".pageShellWrap .dashboardHeader") as HTMLElement;
    expect(pageHeader).toContainElement(month);
    expect(pageHeader).toContainElement(screen.getByLabelText("Base currency"));
  });

  it("moves the theme switch into the account menu", async () => {
    renderPhoneShell("/wealth", <div>Overview Content</div>);
    expect(screen.queryByRole("group", { name: "Theme" })).not.toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: /^(Dark|Light) mode$/ });
    const before = document.documentElement.getAttribute("data-theme");
    await userEvent.click(toggle);
    expect(document.documentElement.getAttribute("data-theme")).not.toBe(before);
    // The account pill keeps its name for screen readers while the label is hidden.
    expect(screen.getByText("User")).toBeInTheDocument();
  });

  it("labels the Cash Flow bottom tab Flow, so it doesn't clash with Wealth → Cash", () => {
    renderPhoneShell("/wealth", <div>Overview Content</div>);
    const nav = screen.getByRole("navigation", { name: "Mobile navigation" });
    expect(within(nav).getByRole("link", { name: "Flow" })).toHaveAttribute("href", "/cash-flow");
    expect(within(nav).queryByRole("link", { name: "Cash" })).not.toBeInTheDocument();
  });
});

describe("Placeholder route smoke tests", () => {
  const routes: { path: string; component: ReactElement; heading: string }[] = [
    { path: "/wealth", component: <WealthOverview />, heading: "Wealth Overview" },
    { path: "/cash-flow", component: <CashFlowDetail />, heading: "Cash Flow Overview" },
    { path: "/risk", component: <WealthRisk />, heading: "Wealth Risk" },
    { path: "/liabilities", component: <LiabilitiesOverview />, heading: "Liabilities" },
    { path: "/operations", component: <OperationsOverview />, heading: "Data Hub" },
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
