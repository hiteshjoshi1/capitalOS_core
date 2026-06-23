import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import StockHoldings from "../routes/StockHoldings";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";
import type { StockHoldingsSummary } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    stockHoldingsSummary: vi.fn(),
    marketDataRefreshNow: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

const summaryFixture: StockHoldingsSummary = {
  as_of_month: "2026-02",
  base_currency: "SGD",
  snapshot_day: 6,
  current_holdings_as_of: "2026-03-01T00:00:00+00:00",
  net_worth_as_of: "2026-03-01T00:00:00+00:00",
  net_worth_snapshot_as_of: "2026-02-06T00:00:00+00:00",
  net_worth_boundary_at: "2026-03-01T00:00:00+00:00",
  net_worth_boundary_exact: false,
  net_worth_freshness_status: "synthetic",
  quote_freshness_summary: {
    fresh: 1,
    stale: 1,
    missing: 0,
  },
  geography_breakdown: [
    { geography: "HK", current_value: 120000, snapshot_value: 100000, delta_abs: 20000, delta_pct: 0.2 },
    { geography: "IN", current_value: 90000, snapshot_value: 85000, delta_abs: 5000, delta_pct: 5000 / 85000 },
  ],
  platform_breakdown: [
    { key: "IBKR", current_value: 210000, snapshot_value: 185000, delta_abs: 25000, delta_pct: 25000 / 185000, percent: 100 },
  ],
  stock_current_total: 210000,
  stock_snapshot_total: 185000,
  top_holdings: [
    {
      asset_id: 1,
      symbol: "700",
      asset_class: "STOCK",
      value: 120000,
      percent_of_networth: 24,
      quantity: 10.5,
      avg_cost: 123.45,
      latest_price: 150.12,
      quote_currency: "HKD",
      geo: "HK",
      platform: "IBKR",
      latest_trade_date: "2026-03-01",
      quote_freshness_status: "fresh",
      price_provider: "eodhd",
    },
    {
      asset_id: 2,
      symbol: "INFY",
      asset_class: "STOCK",
      value: 90000,
      percent_of_networth: 18,
      quantity: 20,
      avg_cost: null,
      latest_price: null,
      quote_currency: "INR",
      geo: "IN",
      platform: "IBKR",
      latest_trade_date: "2026-02-27",
      quote_freshness_status: "stale",
      price_provider: "yahoo_finance",
    },
    {
      asset_id: 3,
      symbol: "USD",
      asset_class: "CASH",
      value: 50000,
      percent_of_networth: 10,
      quantity: 1,
      avg_cost: null,
      latest_price: null,
      quote_currency: "USD",
      geo: "US",
      platform: "DBS",
    },
  ],
};

describe("StockHoldings", () => {
  it("renders dashboard-style header nav and native-currency detail columns", async () => {
    mockApi.stockHoldingsSummary.mockResolvedValueOnce(summaryFixture);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("Top Holdings")).toBeInTheDocument();
    expect(screen.getByText("Quote Freshness")).toBeInTheDocument();
    expect(screen.getByText("Geography Breakdown")).toBeInTheDocument();
    expect(screen.getByText("Platform Breakdown")).toBeInTheDocument();
    expect(screen.getByLabelText("Stock geography exposure pie chart")).toBeInTheDocument();
    expect(screen.getByLabelText("Stock platform exposure pie chart")).toBeInTheDocument();
    expect(screen.queryByText("Dividends")).not.toBeInTheDocument();

    expect(screen.getByLabelText("Base currency")).toBeInTheDocument();
    expect(screen.getByLabelText("Month")).toBeInTheDocument();

    expect(screen.getByRole("columnheader", { name: "Purchase Price" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Current Price" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Profit & Loss" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Quote freshness" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "% NW" })).toBeInTheDocument();
    expect(screen.getByText("Fresh")).toBeInTheDocument();
    expect(screen.getByText("Stale")).toBeInTheDocument();

    const hkRow = screen.getByText("700").closest("tr");
    expect(hkRow).not.toBeNull();
    if (hkRow) {
      const scoped = within(hkRow);
      expect(scoped.getByText("10.5 shares")).toBeInTheDocument();
      expect(scoped.getByText("HKD 123.45")).toBeInTheDocument();
      expect(scoped.getByText("HKD 150.12")).toBeInTheDocument();
      expect(scoped.getByText("+HKD 280.04")).toBeInTheDocument();
      expect(scoped.getByText("+21.6%")).toBeInTheDocument();
      expect(scoped.getByText("fresh")).toBeInTheDocument();
      expect(scoped.getByText(/2026-03-01 · eodhd/)).toBeInTheDocument();
      expect(scoped.getByText("24.0%")).toBeInTheDocument();
    }

    const inRow = screen.getByText("INFY").closest("tr");
    expect(inRow).not.toBeNull();
    if (inRow) {
      const scoped = within(inRow);
      expect(scoped.getByText("20 shares")).toBeInTheDocument();
      expect(scoped.getAllByText("—").length).toBeGreaterThanOrEqual(2);
      expect(scoped.getByText("stale")).toBeInTheDocument();
    }

    expect(screen.getAllByText("HK").length).toBeGreaterThan(0);
    expect(screen.getAllByText("IN").length).toBeGreaterThan(0);
  });

  it("refreshes market data before reloading stock holdings", async () => {
    mockApi.marketDataRefreshNow.mockResolvedValueOnce({ status: "ok", exchanges: [] });
    mockApi.stockHoldingsSummary.mockResolvedValueOnce(summaryFixture);
    mockApi.stockHoldingsSummary.mockResolvedValueOnce({
      ...summaryFixture,
      quote_freshness_summary: {
        fresh: 2,
        stale: 0,
        missing: 0,
      },
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("Stale")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh now" }));

    expect(await screen.findByText("Refreshing...")).toBeInTheDocument();
    await waitFor(() => {
      expect(mockApi.marketDataRefreshNow).toHaveBeenCalledTimes(1);
      expect(mockApi.stockHoldingsSummary).toHaveBeenCalledTimes(3);
    });
  });

  it("shows top 20 positions first and reveals more on Next", async () => {
    const manyHoldings: StockHoldingsSummary = {
      ...summaryFixture,
      top_holdings: Array.from({ length: 25 }, (_, idx) => ({
        asset_id: idx + 100,
        symbol: `POS${idx + 1}`,
        asset_class: "STOCK" as const,
        value: 100000 - idx * 1000,
        percent_of_networth: 10 - idx * 0.1,
        quantity: idx + 1,
        avg_cost: 100 + idx,
        latest_price: 110 + idx,
        quote_currency: "USD",
        geo: "US",
        platform: "IBKR",
      })),
    };

    mockApi.stockHoldingsSummary.mockResolvedValueOnce(manyHoldings);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("Showing 20 of 25 positions")).toBeInTheDocument();
    expect(screen.getByText("POS20")).toBeInTheDocument();
    expect(screen.queryByText("POS21")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("Showing 25 of 25 positions")).toBeInTheDocument();
    expect(screen.getByText("POS25")).toBeInTheDocument();
  });
});
