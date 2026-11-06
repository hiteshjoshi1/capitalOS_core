import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import WealthRisk from "../routes/WealthRisk";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";
import type { GeographyExposure, RiskSummary } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    riskSummary: vi.fn(),
    dashboardGeographyExposure: vi.fn(),
  },
}));

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
    expect(screen.getByText("15.0%")).toBeInTheDocument();
    expect(screen.getByText("AAPL — 22.0%")).toBeInTheDocument();
    expect(screen.getByText("Where the top positions sit")).toBeInTheDocument();
    expect(screen.getByText("STOCK · S$ 22,000")).toBeInTheDocument();
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

    expect(await screen.findByText("Concentration signals and geographic exposure · Live.")).toBeInTheDocument();
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
      await screen.findByText("Concentration signals and geographic exposure · As of 31 Oct 2026 close."),
    ).toBeInTheDocument();
    expect(screen.getByText("15.0%")).toBeInTheDocument();
    expect(screen.getByText("AAPL — 22.0%")).toBeInTheDocument();
    expect(screen.getByText("As of 6 Feb 2026")).toBeInTheDocument();
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
