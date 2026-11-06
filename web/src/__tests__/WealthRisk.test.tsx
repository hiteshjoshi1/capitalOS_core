import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import WealthRisk from "../routes/WealthRisk";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";
import type { GeographyExposure, RiskSummary } from "../lib/api";
import { clearApiCache } from "../lib/useApiResource";

vi.mock("../lib/api", () => ({
  api: {
    riskSummary: vi.fn(),
    riskThresholds: vi.fn(),
    dashboardGeographyExposure: vi.fn(),
  },
}));

const NO_THRESHOLDS = { largest_position_warn_pct: null, top_n_warn_pct: null, platform_warn_pct: null };

const mockApi = vi.mocked(api, true);

const summaryFixture = {
  base_currency: "SGD",
  net_worth: { total: 100000, cash: 15000, stocks_funds: 70000, crypto: 15000, liabilities: 0 },
  top_holdings: [
    { symbol: "AAPL", asset_class: "STOCK", value: 22000, geo: "US", platform: "IBKR" },
    { symbol: "MSFT", asset_class: "STOCK", value: 10000, geo: "US", platform: "IBKR" },
    { symbol: "GOOGL", asset_class: "STOCK", value: 8000, geo: "US", platform: "IBKR" },
    { symbol: "BTC", asset_class: "CRYPTO", value: 15000, geo: "US", platform: "CRYPTO" },
  ],
} as unknown as RiskSummary;

const geographyFixture: GeographyExposure = {
  as_of: "2026-02-06",
  base_currency: "SGD",
  total: 100000,
  items: [{ country: "US", stocks_funds: 40000, cash: 15000, crypto: 15000, total: 70000, percent: 70 }],
};

describe("WealthRisk route", () => {
  beforeEach(() => {
    clearApiCache();
    mockApi.riskThresholds.mockResolvedValue(NO_THRESHOLDS);
    mockApi.riskSummary.mockResolvedValue(summaryFixture);
    mockApi.dashboardGeographyExposure.mockResolvedValue(geographyFixture);
  });

  it("renders cash buffer, largest position (flagged), and geography breakdown", async () => {
    render(
      <ThemeProvider>
        <MemoryRouter>
          <WealthRisk />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("Cash buffer")).toBeInTheDocument();
    expect(mockApi.riskSummary).toHaveBeenCalledWith(expect.stringMatching(/^\d{4}-\d{2}$/), "SGD");
    // The cash buffer (BTC, 15% of net worth, is a position too: #253).
    expect(screen.getByText("15.0%", { selector: ".big" })).toBeInTheDocument();
    expect(screen.getByText("AAPL — 22.0%")).toBeInTheDocument();
    expect(screen.getByText("Where the top positions sit")).toBeInTheDocument();
    // The largest-position card's caption and the first row of the top-positions list.
    expect(screen.getAllByText("STOCK · S$ 22,000")).toHaveLength(2);
    expect(screen.getByText("AAPL — 22.0%")).toHaveClass("warn");
    expect(screen.getAllByText("22.0%").length).toBeGreaterThan(0);
    expect(screen.getByText("Where the wealth is booked")).toBeInTheDocument();
    expect(screen.getByText("Mapped")).toBeInTheDocument();
    expect(screen.getByText("S$ 100K")).toBeInTheDocument();
    expect(screen.getByText("As of 6 Feb 2026")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Geographic exposure pie chart" })).toBeInTheDocument();
    expect(screen.getByText(/Stocks S\$ 40,000/)).toBeInTheDocument();
  });

  it("switches Top 3 / Top 5 concentration via the segmented toggle", async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <MemoryRouter>
          <WealthRisk />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("Top 5 concentration")).toBeInTheDocument();
    expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
    expect(screen.getAllByText("MSFT").length).toBeGreaterThan(0);
    expect(screen.getAllByText("GOOGL").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Top 3" }));
    expect(await screen.findByText("Top 3 concentration")).toBeInTheDocument();
  });

  it("redraws geography exposure after selecting a different month", async () => {
    mockApi.dashboardGeographyExposure
      .mockResolvedValueOnce(geographyFixture)
      .mockResolvedValueOnce({
        ...geographyFixture,
        total: 80000,
        items: [{ country: "SG", stocks_funds: 30000, cash: 20000, crypto: 0, total: 50000, percent: 62.5 }],
      });
    render(
      <ThemeProvider>
        <MemoryRouter>
          <WealthRisk />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText(/Stocks S\$ 40,000/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Month"), { target: { value: "2025-05" } });

    await waitFor(() => expect(mockApi.dashboardGeographyExposure).toHaveBeenLastCalledWith("2025-05", "SGD"));
    expect(await screen.findByText(/Stocks S\$ 30,000/)).toBeInTheDocument();
  });

  // #241: one point in time per month.
  it("open month: divides live positions by the live net worth and says Live", async () => {
    mockApi.riskSummary.mockResolvedValue({
      ...summaryFixture,
      is_live: true,
      basis: "live",
      // The month-end net worth stays in net_worth; the shares use the live one.
      view_net_worth: { total: 200000, cash: 50000, stocks_funds: 130000, crypto: 20000, liabilities: 0 },
      net_worth_boundary_at: "2026-11-06T10:00:00+08:00",
    } as RiskSummary);
    mockApi.dashboardGeographyExposure.mockResolvedValue({ ...geographyFixture, is_live: true });
    render(
      <ThemeProvider>
        <MemoryRouter>
          <WealthRisk />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("Concentration signals and exposure · Live.")).toBeInTheDocument();
    expect(screen.getByText("25.0%")).toBeInTheDocument();
    expect(screen.getByText("S$ 50,000 of S$ 200,000 net worth")).toBeInTheDocument();
    expect(screen.getByText("AAPL — 11.0%")).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
    expect(screen.queryByText(/current snapshot/)).not.toBeInTheDocument();
  });

  it("past month: states the month-end close it is taken at", async () => {
    mockApi.riskSummary.mockResolvedValue({
      ...summaryFixture,
      is_live: false,
      basis: "month_end",
      view_net_worth: summaryFixture.net_worth,
      net_worth_boundary_at: "2026-11-01T00:00:00+00:00",
    } as RiskSummary);
    mockApi.dashboardGeographyExposure.mockResolvedValue({ ...geographyFixture, is_live: false });
    render(
      <ThemeProvider>
        <MemoryRouter>
          <WealthRisk />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(
      await screen.findByText("Concentration signals and exposure · As of 31 Oct 2026 close."),
    ).toBeInTheDocument();
    // The cash buffer (BTC, 15% of net worth, is a position too: #253).
    expect(screen.getByText("15.0%", { selector: ".big" })).toBeInTheDocument();
    expect(screen.getByText("AAPL — 22.0%")).toBeInTheDocument();
    expect(screen.getByText("As of 6 Feb 2026")).toBeInTheDocument();
  });

  // #253: every asset class, only an upper threshold warns, user thresholds, and the
  // currency and platform cards.
  function renderRisk() {
    return render(
      <ThemeProvider>
        <MemoryRouter>
          <WealthRisk />
        </MemoryRouter>
      </ThemeProvider>,
    );
  }

  it("counts crypto as a position, like Overview's largest holdings", async () => {
    mockApi.riskSummary.mockResolvedValue({
      ...summaryFixture,
      top_holdings: [
        { asset_id: null, symbol: "ETH", asset_class: "CRYPTO", value: 30000, percent_of_networth: 30 },
        { asset_id: 1, symbol: "AAPL", asset_class: "STOCK", value: 22000, percent_of_networth: 22 },
      ],
    } as RiskSummary);
    renderRisk();

    expect(await screen.findByText("ETH — 30.0%")).toBeInTheDocument();
    // The card's caption and the first row of the top-positions list.
    expect(screen.getAllByText("CRYPTO · S$ 30,000")).toHaveLength(2);
    // ETH + AAPL: 52% of net worth, above the default 50%.
    expect(screen.getByText("52.0%")).toHaveClass("warn");
  });

  it("does not flag low concentration: only above the threshold is a warning", async () => {
    mockApi.riskSummary.mockResolvedValue({
      ...summaryFixture,
      top_holdings: [
        { asset_id: 1, symbol: "AAPL", asset_class: "STOCK", value: 8000 },
        { asset_id: 2, symbol: "MSFT", asset_class: "STOCK", value: 6000 },
      ],
    } as unknown as RiskSummary);
    renderRisk();

    const top = await screen.findByText("14.0%");
    expect(top).not.toHaveClass("bad");
    expect(top).not.toHaveClass("warn");
    expect(screen.getByText("AAPL — 8.0%")).not.toHaveClass("warn");
    expect(screen.getByText("Above 15%: concentrated")).toBeInTheDocument();
    expect(screen.getByText("Above 50%: concentrated", { selector: ".riskThresholdRule span" })).toBeInTheDocument();
    expect(screen.queryByText(/Target band/)).not.toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Change in Settings" })[0]).toHaveAttribute("href", "/settings");
  });

  it("uses the user's thresholds from Settings", async () => {
    mockApi.riskThresholds.mockResolvedValue({ largest_position_warn_pct: 25, top_n_warn_pct: 30, platform_warn_pct: null });
    renderRisk();

    expect(await screen.findByText("Above 25%: concentrated")).toBeInTheDocument();
    // AAPL 22% is below the user's 25%.
    expect(screen.getByText("AAPL — 22.0%")).not.toHaveClass("warn");
    // Top 5 (AAPL, BTC, MSFT, GOOGL) = 55% > 30%.
    expect(screen.getByText("55.0%")).toHaveClass("warn");
  });

  it("falls back to the default thresholds when they can't load", async () => {
    mockApi.riskThresholds.mockRejectedValue(new Error("offline"));
    renderRisk();

    expect(await screen.findByText("Above 15%: concentrated")).toBeInTheDocument();
    expect(screen.getByText("AAPL — 22.0%")).toHaveClass("warn");
    expect(screen.queryByText("Couldn't load risk")).not.toBeInTheDocument();
  });

  it("shows currency exposure and platform concentration at the page's point in time", async () => {
    mockApi.riskSummary.mockResolvedValue({
      ...summaryFixture,
      currency_exposure: {
        total: 100000,
        items: [
          { currency: "USD", cash: 5000, stocks_funds: 40000, stablecoins: 3000, crypto: 0, liabilities: 0, value: 48000, percent: 48 },
          { currency: "SGD", cash: 10000, stocks_funds: 30000, stablecoins: 0, crypto: 0, liabilities: 500, value: 39500, percent: 39.5 },
          { currency: "CRYPTO", cash: 0, stocks_funds: 0, stablecoins: 0, crypto: 12500, liabilities: 0, value: 12500, percent: 12.5 },
        ],
      },
      platform_concentration: {
        total: 100500,
        items: [
          { platform: "IBKR", platform_type: "BROKER", country: "US", value: 60000, percent: 59.7 },
          { platform: "DBS_VICKERS", platform_type: "BROKER", country: "SG", value: 25000, percent: 24.88 },
          { platform: "CRYPTO", platform_type: "WALLET_PROVIDER", country: null, value: 15500, percent: 15.42 },
        ],
      },
    } as RiskSummary);
    renderRisk();

    const currency = within(await screen.findByRole("region", { name: "Currency exposure" }));
    expect(currency.getByText("USD")).toBeInTheDocument();
    expect(currency.getByText("48.0%")).toBeInTheDocument();
    expect(currency.getByText("Stocks S$ 40,000 · Cash S$ 5,000 · Stablecoins S$ 3,000")).toBeInTheDocument();
    expect(currency.getByText("Stocks S$ 30,000 · Cash S$ 10,000 · Cards owed -S$ 500.00")).toBeInTheDocument();
    expect(currency.getByText("Crypto (not stablecoins)")).toBeInTheDocument();

    const platforms = within(screen.getByRole("region", { name: "Platform concentration" }));
    expect(platforms.getByText("DBS Vickers")).toBeInTheDocument();
    // Above the default 50%: a warning; the others are not flagged.
    expect(platforms.getByText("59.7%")).toHaveClass("warn");
    expect(platforms.getByText("24.9%")).not.toHaveClass("warn");
  });

  it("shows API error state when fetch fails", async () => {
    mockApi.riskSummary.mockRejectedValueOnce(new Error("risk unavailable"));

    render(
      <ThemeProvider>
        <MemoryRouter>
          <WealthRisk />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("Couldn't load risk")).toBeInTheDocument();
    expect(screen.getByText("risk unavailable")).toBeInTheDocument();
  });
});
