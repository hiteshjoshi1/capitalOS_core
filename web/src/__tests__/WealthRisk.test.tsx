import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import WealthRisk from "../routes/WealthRisk";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";
import type { DashboardSummary, GeographyExposure } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    dashboardSummary: vi.fn(),
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
} as unknown as DashboardSummary;

const geographyFixture: GeographyExposure = {
  as_of: "2026-02-06",
  base_currency: "SGD",
  total: 100000,
  items: [{ country: "US", stocks_funds: 40000, cash: 15000, crypto: 15000, total: 70000, percent: 70 }],
};

describe("WealthRisk route", () => {
  beforeEach(() => {
    mockApi.dashboardSummary.mockResolvedValue(summaryFixture);
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
    expect(screen.getByText("15.0%")).toBeInTheDocument();
    expect(screen.getByText("AAPL — 22.0%")).toBeInTheDocument();
    expect(screen.getByText("Where the top positions sit")).toBeInTheDocument();
    expect(screen.getByText("Where the wealth is booked")).toBeInTheDocument();
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

  it("shows API error state when fetch fails", async () => {
    mockApi.dashboardSummary.mockRejectedValueOnce(new Error("risk unavailable"));

    render(
      <ThemeProvider>
        <MemoryRouter>
          <WealthRisk />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("API error")).toBeInTheDocument();
    expect(screen.getByText("risk unavailable")).toBeInTheDocument();
  });
});
