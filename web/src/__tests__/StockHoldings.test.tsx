import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
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
const STOCK_COLUMN_STORAGE_KEY = "capitalos.stockHoldings.visibleColumns";

const summaryFixture: StockHoldingsSummary = {
  as_of_month: "2026-02",
  base_currency: "SGD",
  snapshot_day: 6,
  is_live: false,
  compare_month: "2026-01",
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
  trend: [
    { month: "2026-01", value: 175000 },
    { month: "2026-02", value: 185000 },
    { month: "2026-03", value: 210000 },
  ],
  top_holdings: [
    {
      asset_id: 1,
      symbol: "700",
      name: "Tencent Holdings",
      asset_class: "STOCK",
      value: 120000,
      percent_of_networth: 24,
      quantity: 10.5,
      avg_cost: 123.45,
      latest_price: 150.12,
      quote_currency: "HKD",
      geo: "HK",
      platform: "IBKR",
      exchange_code: "HKEX",
      latest_trade_date: "2026-03-01",
      quote_freshness_status: "fresh",
      price_provider: "eodhd",
    },
    {
      asset_id: 2,
      symbol: "INFY",
      name: "Infosys",
      asset_class: "STOCK",
      value: 90000,
      percent_of_networth: 18,
      quantity: 20,
      avg_cost: null,
      latest_price: null,
      quote_currency: "INR",
      geo: "IN",
      platform: "IBKR",
      exchange_code: "NSE",
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
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    Object.defineProperty(window, "innerWidth", { value: 1024, configurable: true, writable: true });
  });

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
    const trendHeading = screen.getByText("Six-Month Stock Trend");
    const geographyHeading = screen.getByText("Geography Breakdown");
    const platformHeading = screen.getByText("Platform Breakdown");
    expect(trendHeading).toBeInTheDocument();
    expect(screen.getByLabelText("Six-month stock trend")).toBeInTheDocument();
    expect(screen.getAllByText("Jan '26").length).toBeGreaterThan(0);
    expect(screen.getAllByText("S$ 175,000").length).toBeGreaterThan(0);
    expect(geographyHeading.compareDocumentPosition(trendHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(platformHeading.compareDocumentPosition(trendHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByLabelText("Stock geography exposure pie chart")).toBeInTheDocument();
    expect(screen.getByLabelText("Stock platform exposure pie chart")).toBeInTheDocument();
    expect(screen.queryByText("Dividends")).not.toBeInTheDocument();

    expect(screen.getByLabelText("Base currency")).toBeInTheDocument();
    expect(screen.getByLabelText("Month")).toBeInTheDocument();

    expect(screen.getByRole("columnheader", { name: "Shares" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Purchase Price" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Current Price" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Profit & Loss" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Quote freshness" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "% NW" })).toBeInTheDocument();
    const columnHeaders = screen.getAllByRole("columnheader").map((header) => header.textContent);
    expect(columnHeaders.at(-1)).toBe("Quote freshness");
    expect(screen.queryByText("Quote Freshness")).not.toBeInTheDocument();

    const hkRow = screen.getByText("700").closest("tr");
    expect(hkRow).not.toBeNull();
    if (hkRow) {
      const scoped = within(hkRow);
      expect(scoped.getByText("10.5")).toBeInTheDocument();
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
      expect(scoped.getByText("20")).toBeInTheDocument();
      expect(scoped.getAllByText("—").length).toBeGreaterThanOrEqual(2);
      expect(scoped.getByText("stale")).toBeInTheDocument();
    }

    expect(screen.getAllByText("HK").length).toBeGreaterThan(0);
    expect(screen.getAllByText("IN").length).toBeGreaterThan(0);
  });

  it("renders top holdings as succinct responsive summary rows on mobile", async () => {
    Object.defineProperty(window, "innerWidth", { value: 480, configurable: true, writable: true });
    mockApi.stockHoldingsSummary.mockResolvedValueOnce(summaryFixture);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("Top Holdings")).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Shares" })).not.toBeInTheDocument();

    const hkCard = screen.getByText("Tencent Holdings").closest(".stockHoldingsMobileCard");
    expect(hkCard).not.toBeNull();
    if (hkCard) {
      const scoped = within(hkCard as HTMLElement);
      expect(scoped.getByText("Tencent Holdings")).toBeInTheDocument();
      expect(scoped.getByText("HKEX")).toBeInTheDocument();
      expect(scoped.getByText("IBKR · Hong Kong")).toBeInTheDocument();
      expect(scoped.getByText("Fresh")).toBeInTheDocument();
      expect(scoped.getByText("S$ 120,000")).toBeInTheDocument();
      expect(scoped.getByText("24.0% NW")).toBeInTheDocument();
      expect(scoped.getByText("+S$ 21,319")).toBeInTheDocument();
      expect(scoped.getByText("+21.6%")).toBeInTheDocument();
      expect(scoped.queryByText("Shares")).not.toBeInTheDocument();
      expect(scoped.queryByText("Purchase Price")).not.toBeInTheDocument();
    }
  });

  it("stores stock table column visibility in browser storage", async () => {
    mockApi.stockHoldingsSummary.mockResolvedValueOnce(summaryFixture);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByRole("columnheader", { name: "Current Price" })).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Current Price"));

    expect(screen.queryByRole("columnheader", { name: "Current Price" })).not.toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem(STOCK_COLUMN_STORAGE_KEY) ?? "{}")).toMatchObject({
      currentPrice: false,
    });
  });

  it("refreshes market data before reloading stock holdings", async () => {
    // Refresh only makes sense for the live/current month — a disabled button on a
    // historical month is covered separately below.
    const liveFixture: StockHoldingsSummary = { ...summaryFixture, is_live: true };
    mockApi.marketDataRefreshNow.mockResolvedValueOnce({ status: "ok", exchanges: [] });
    mockApi.stockHoldingsSummary.mockResolvedValueOnce(liveFixture);
    mockApi.stockHoldingsSummary.mockResolvedValueOnce({
      ...liveFixture,
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

    expect(await screen.findByText("Top Holdings")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh quotes" }));

    expect(await screen.findByText("Refreshing...")).toBeInTheDocument();
    await waitFor(() => {
      expect(mockApi.marketDataRefreshNow).toHaveBeenCalledTimes(1);
      expect(mockApi.stockHoldingsSummary).toHaveBeenCalledTimes(2);
    });
  });

  it("disables refresh quotes when viewing a historical (non-live) month", async () => {
    mockApi.stockHoldingsSummary.mockResolvedValueOnce({ ...summaryFixture, is_live: false });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("Top Holdings")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh quotes" })).toBeDisabled();
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

    expect(await screen.findByText("20 of 25 positions")).toBeInTheDocument();
    expect(screen.getByText("POS20")).toBeInTheDocument();
    expect(screen.queryByText("POS21")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("25 of 25 positions")).toBeInTheDocument();
    expect(screen.getByText("POS25")).toBeInTheDocument();
  });

  it("renders geography performance for the live period, separate from the allocation pie", async () => {
    const liveFixture: StockHoldingsSummary = {
      ...summaryFixture,
      is_live: true,
      geography_performance: [
        { geography: "US", current_value: 50000, snapshot_value: 48000, delta_abs: 2000, delta_pct: 2000 / 48000 },
        { geography: "HK", current_value: 120000, snapshot_value: 122000, delta_abs: -2000, delta_pct: -2000 / 122000 },
      ],
      geography_performance_as_of: "2026-03-01T09:00:00+00:00",
    };
    mockApi.stockHoldingsSummary.mockResolvedValueOnce(liveFixture);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("Geography Performance")).toBeInTheDocument();
    expect(screen.getByText("United States")).toBeInTheDocument();
    expect(screen.getByText("+S$ 2,000")).toBeInTheDocument();
    expect(screen.getByText("Hong Kong")).toBeInTheDocument();
    expect(screen.getByText("-S$ 2,000")).toBeInTheDocument();
  });

  it("shows a fallback message for geography performance on a historical (non-live) month", async () => {
    mockApi.stockHoldingsSummary.mockResolvedValueOnce({ ...summaryFixture, is_live: false });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("Geography Performance")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Geography performance is only available for the current, live period — pick the current month to see it.",
      ),
    ).toBeInTheDocument();
  });
});
