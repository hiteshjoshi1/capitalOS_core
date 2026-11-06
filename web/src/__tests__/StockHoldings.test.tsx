import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { controlledCalls } from "./raceHelpers";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import StockHoldings from "../routes/StockHoldings";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";
import type { StockHoldingsSummary, StockMonthChange } from "../lib/api";

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

  it("renders dashboard-style header nav and native-currency price columns", async () => {
    // The live month: freshness badges apply (#224).
    mockApi.stockHoldingsSummary.mockResolvedValueOnce({ ...summaryFixture, is_live: true });

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
      // P&L in the base currency, the local currency in the tooltip (#251).
      expect(scoped.getByText("+S$ 21,319").closest("td")).toHaveAttribute("title", "In HKD: +HKD 280.04");
      expect(scoped.getByText("+21.6%")).toBeInTheDocument();
      expect(scoped.getByText("fresh")).toBeInTheDocument();
      expect(scoped.getByText("price from 1 Mar 2026, EODHD")).toBeInTheDocument();
      expect(scoped.getByText("24.0%")).toBeInTheDocument();
    }

    const inRow = screen.getByText("INFY").closest("tr");
    expect(inRow).not.toBeNull();
    if (inRow) {
      const scoped = within(inRow);
      expect(scoped.getByText("20")).toBeInTheDocument();
      expect(scoped.getAllByText("—").length).toBeGreaterThanOrEqual(2);
      expect(scoped.getByText("stale")).toBeInTheDocument();
      expect(scoped.getByText(/^stale \(price from 27 Feb 2026, /)).toBeInTheDocument();
    }

    expect(screen.getAllByText("HK").length).toBeGreaterThan(0);
    expect(screen.getAllByText("IN").length).toBeGreaterThan(0);
  });

  it("renders top holdings as succinct responsive summary rows on mobile", async () => {
    Object.defineProperty(window, "innerWidth", { value: 480, configurable: true, writable: true });
    mockApi.stockHoldingsSummary.mockResolvedValueOnce({ ...summaryFixture, is_live: true });

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
      expect(scoped.getByText("price from 1 Mar 2026, EODHD")).toBeInTheDocument();
    }
  });

  // ── #224: price age per holding, freshness only on the live month ──────────
  const statementOnly = {
    asset_id: 4,
    symbol: "RELIANCE",
    name: "Reliance Industries",
    asset_class: "STOCK",
    value: 40000,
    percent_of_networth: 8,
    quantity: 12,
    avg_cost: 2500,
    latest_price: 2880,
    quote_currency: "INR",
    geo: "IN",
    platform: "SHAREKHAN",
    exchange_code: "NSE",
    latest_trade_date: "2026-01-15",
    quote_freshness_status: "stale",
    price_source: "canonical_snapshot",
    price_provider: "canonical",
    price_basis: "statement" as const,
    price_fallback_reason: "no_quote",
  };
  const liveFixture: StockHoldingsSummary = {
    ...summaryFixture,
    as_of_month: "2026-03",
    compare_month: "2026-02",
    is_live: true,
    quote_stale_days: 3,
    quote_freshness_summary: { fresh: 1, stale: 2, missing: 0, no_live_price: 2 },
    top_holdings: [
      { ...summaryFixture.top_holdings[0], price_basis: "quote" },
      { ...summaryFixture.top_holdings[1], price_basis: "quote" },
      statementOnly,
    ],
  };

  it.each([
    ["desktop table", 1024],
    ["375px cards", 375],
  ])("marks a statement-only price older than the stale window as stale (%s)", async (_label, width) => {
    Object.defineProperty(window, "innerWidth", { value: width, configurable: true, writable: true });
    mockApi.stockHoldingsSummary.mockResolvedValueOnce(liveFixture);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    const stale = await screen.findByText("stale (price from 15 Jan 2026, SHAREKHAN statement)");
    expect(stale).toHaveClass("priceAge--stale");
    // A fresh quote is dated and sourced, but not marked.
    const fresh = screen.getByText("price from 1 Mar 2026, EODHD");
    expect(fresh).not.toHaveClass("priceAge--stale");
  });

  it("counts holdings without a live price in the header and links to Data Hub", async () => {
    mockApi.stockHoldingsSummary.mockResolvedValueOnce(liveFixture);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    const line = await screen.findByTestId("stock-price-freshness");
    expect(line).toHaveTextContent("Prices: 1 fresh · 2 stale");
    expect(line).toHaveTextContent("2 holdings without a live price");
    expect(within(line).getByRole("link", { name: "Fix in Data Hub" })).toHaveAttribute("href", "/operations");
  });

  it("falls back to counting holdings when the API has no no_live_price yet", async () => {
    mockApi.stockHoldingsSummary.mockResolvedValueOnce({
      ...liveFixture,
      quote_freshness_summary: { fresh: 1, stale: 2, missing: 0 },
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByTestId("stock-price-freshness")).toHaveTextContent("2 holdings without a live price");
  });

  it.each([
    ["desktop table", 1024],
    ["375px cards", 375],
  ])("shows no freshness badges on a past month, only the price date (%s)", async (_label, width) => {
    Object.defineProperty(window, "innerWidth", { value: width, configurable: true, writable: true });
    mockApi.stockHoldingsSummary.mockResolvedValueOnce({
      ...liveFixture,
      as_of_month: "2026-02",
      compare_month: "2026-01",
      is_live: false,
      quote_freshness_summary: { fresh: 1, stale: 2, missing: 0, no_live_price: null },
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("price from 15 Jan 2026, SHAREKHAN statement")).not.toHaveClass("priceAge--stale");
    expect(screen.queryByTestId("stock-price-freshness")).not.toBeInTheDocument();
    expect(screen.queryByText(/without a live price/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^stale/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^fresh$/i)).not.toBeInTheDocument();
  });

  it("says there is no comparison when the compare month has no stock data", async () => {
    mockApi.stockHoldingsSummary.mockResolvedValueOnce({
      ...liveFixture,
      stock_snapshot_total: 0,
      stock_snapshot_missing: true,
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("no comparison: no data for Feb 2026")).toBeInTheDocument();
    // Never a delta the size of the whole holding.
    expect(screen.queryByText(/\+S\$ 210,000/)).not.toBeInTheDocument();
  });

  it("shows the header change with the % from the same currency, and ▲", async () => {
    mockApi.stockHoldingsSummary.mockResolvedValueOnce(liveFixture);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    // 210,000 vs 185,000: +25,000, +13.5%.
    const chip = (await screen.findByText("+13.5%")).closest(".delta");
    expect(chip).toHaveClass("deltaChip", "delta--up");
    expect(chip).toHaveTextContent("▲");
    expect(screen.getByText("+S$ 25,000 (+13.5%)")).toBeInTheDocument();
  });

  // #232: the previous figure names its month and the date of its holdings.
  it("dates the compare month's figure (#232)", async () => {
    mockApi.stockHoldingsSummary.mockResolvedValueOnce({ ...liveFixture, stock_snapshot_as_of: "2026-02-27" });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText(/vs Feb 2026 \(S\$ 185,000, holdings as of 27 Feb 2026\)/)).toBeInTheDocument();
  });

  it.each([
    ["desktop", 1024],
    ["mobile", 480],
  ])("explains an IBKR fallback price behind an i button (%s, #124)", async (_label, width) => {
    Object.defineProperty(window, "innerWidth", { value: width, configurable: true, writable: true });
    const [first, ...rest] = summaryFixture.top_holdings;
    mockApi.stockHoldingsSummary.mockResolvedValueOnce({
      ...summaryFixture,
      is_live: true,
      top_holdings: [
        { ...first, price_fallback_reason: "no_quote", latest_trade_date: "2026-10-30", quote_freshness_status: "stale" },
        ...rest,
      ],
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    const info = await screen.findByRole("button", { name: "Why is 700's price stale?" });
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    fireEvent.click(info);
    expect(screen.getByRole("note")).toHaveTextContent(
      "Stale price for 700: taken from IBKR's statement of 2026-10-30, because the price job couldn't fetch a quote for it.",
    );
    // Only the fallback holding gets one.
    expect(screen.getAllByRole("button", { name: /price stale\?/ })).toHaveLength(1);
  });

  // ── #251: change per holding vs the compare month-end, split; sales read as sales ──
  const change = (over: Partial<StockMonthChange>): StockMonthChange => ({
    abs: 0,
    pct: null,
    price_effect: 0,
    quantity_effect: 0,
    fx_effect: 0,
    unsplit: 0,
    compare_value: 0,
    end_value: 0,
    compare_month: "2026-02",
    baseline_missing: false,
    side: "held",
    ...over,
  });
  const changeFixture: StockHoldingsSummary = {
    ...liveFixture,
    compare_boundary_at: "2026-03-01T00:00:00+00:00",
    top_holdings: [
      {
        ...summaryFixture.top_holdings[0],
        month_change: change({
          abs: 3000, pct: 0.025641, price_effect: 3400, fx_effect: -400, compare_value: 117000, end_value: 120000,
          start_quantity: 10.5, end_quantity: 10.5, start_price: 140, end_price: 150.12, price_currency: "HKD",
          start_rate: 0.172, end_rate: 0.1717,
        }),
      },
      {
        ...summaryFixture.top_holdings[1],
        // Bought 5 more: most of the change is a purchase, not a gain.
        month_change: change({
          abs: 21000, pct: 0.3, price_effect: 1000, quantity_effect: 20000, compare_value: 70000, end_value: 90000,
          start_quantity: 15, end_quantity: 20, start_price: 1500, end_price: 1600, price_currency: "INR",
          start_rate: 0.016, end_rate: 0.016,
        }),
      },
    ],
    sold_holdings: [
      {
        asset_id: 9,
        symbol: "AAPL",
        name: "Apple",
        asset_class: "STOCK",
        value: 0,
        percent_of_networth: 0,
        quantity: 0,
        quote_currency: "USD",
        platform: "IBKR",
        month_change: change({
          abs: -5000, pct: -1, quantity_effect: -5000, compare_value: 5000, end_value: 0, side: "sold",
          start_quantity: 20, start_price: 190, price_currency: "USD", start_rate: 1.3157,
        }),
      },
    ],
  };

  const renderChange = async (width: number) => {
    Object.defineProperty(window, "innerWidth", { value: width, configurable: true, writable: true });
    mockApi.stockHoldingsSummary.mockResolvedValueOnce(changeFixture);
    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );
    expect(await screen.findByText("Top Holdings")).toBeInTheDocument();
  };

  it("shows each holding's change vs the month-end close, with its split on tap (#251)", async () => {
    await renderChange(1024);
    expect(screen.getByRole("columnheader", { name: "Δ vs 28 Feb 2026" })).toBeInTheDocument();
    const hkRow = within(screen.getByText("700").closest("tr") as HTMLElement);
    const delta = hkRow.getByText("+S$ 3,000 (+2.6%)").closest(".delta");
    expect(delta).toHaveClass("delta--up");
    const toggle = hkRow.getByRole("button", { name: /^700 since 28 Feb 2026: \+S\$ 3,000/ });
    expect(toggle).toHaveAttribute("title", expect.stringContaining("Price +S$ 3,400 (HKD 140.00 → HKD 150.12 (+HKD 106.26))"));
    expect(hkRow.queryByRole("note")).not.toBeInTheDocument();
    fireEvent.click(toggle);
    const note = hkRow.getByRole("note");
    expect(note).toHaveTextContent("Price+S$ 3,400HKD 140.00 → HKD 150.12 (+HKD 106.26)");
    expect(note).toHaveTextContent("Quantity");
    expect(note).toHaveTextContent("no shares added or sold");
    expect(note).toHaveTextContent("FX-S$ 400HKD -0.17% vs SGD");
    expect(note).toHaveTextContent("vs S$ 117,000 at 28 Feb 2026 close");
  });

  it("doesn't colour a purchase as a gain, and lists a sale as Sold, never a loss (#251)", async () => {
    await renderChange(1024);
    const boughtRow = screen.getByText("INFY").closest("tr") as HTMLElement;
    const bought = within(boughtRow);
    expect(bought.getByText("+S$ 21,000")).toHaveClass("stockMonthChangeNeutral");
    expect(bought.getByText("bought S$ 20,000 · market +S$ 1,000")).toBeInTheDocument();
    expect(boughtRow.querySelector(".delta--up, .delta--down")).toBeNull();

    const soldRow = screen.getByText("AAPL").closest("tr") as HTMLElement;
    const sold = within(soldRow);
    expect(soldRow).toHaveClass("stockHoldingsSoldRow");
    expect(sold.getByText("Sold")).toBeInTheDocument();
    expect(sold.getByText("was S$ 5,000")).toBeInTheDocument();
    expect(soldRow.querySelector(".delta--down, .bad")).toBeNull();
    expect(sold.queryByText(/-S\$ 5,000/)).not.toBeInTheDocument();
    fireEvent.click(sold.getByRole("button", { name: /^AAPL since 28 Feb 2026: -S\$ 5,000, sold/ }));
    expect(sold.getByRole("note")).toHaveTextContent("Quantity-S$ 5,000sold 20 shares");
    expect(sold.getByRole("note")).not.toHaveTextContent("Price");
    expect(screen.getByText("2 of 2 positions · 1 sold since 28 Feb 2026")).toBeInTheDocument();
  });

  it("shows the change and its price / quantity / FX split on the mobile card (#251)", async () => {
    await renderChange(375);
    const hkCard = within(screen.getByText("Tencent Holdings").closest(".stockHoldingsMobileCard") as HTMLElement);
    expect(hkCard.getByText("Since 28 Feb 2026")).toBeInTheDocument();
    expect(hkCard.getByText("+S$ 3,000 (+2.6%)")).toBeInTheDocument();
    expect(hkCard.getByText("Price +S$ 3,400")).toBeInTheDocument();
    expect(hkCard.getByText("Quantity S$ 0")).toBeInTheDocument();
    expect(hkCard.getByText("FX -S$ 400")).toBeInTheDocument();

    const soldCard = within(screen.getByText("Apple").closest(".stockHoldingsMobileCard") as HTMLElement);
    expect(soldCard.getByText("Sold")).toBeInTheDocument();
    expect(soldCard.getByText("Quantity -S$ 5,000")).toBeInTheDocument();
    expect(soldCard.queryByText(/NW$/)).not.toBeInTheDocument();
  });

  it("says there's no comparison per holding when the compare month has no data (#251)", async () => {
    Object.defineProperty(window, "innerWidth", { value: 1024, configurable: true, writable: true });
    mockApi.stockHoldingsSummary.mockResolvedValueOnce({
      ...changeFixture,
      stock_snapshot_missing: true,
      sold_holdings: [],
      top_holdings: [{ ...summaryFixture.top_holdings[0], month_change: change({ abs: 120000, quantity_effect: 120000, side: "new", baseline_missing: true }) }],
    });
    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );
    const row = within((await screen.findByText("700")).closest("tr") as HTMLElement);
    expect(row.getByTitle("no comparison: no data for Feb 2026")).toHaveTextContent("—");
    // Never a change the size of the whole holding.
    expect(row.queryByText(/\+S\$ 120,000/)).not.toBeInTheDocument();
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

// #148: a slow earlier month never renders under a later one; the earlier one is aborted.
describe("StockHoldings races", () => {
  it("shows the later month even when the earlier month's reply lands last", async () => {
    window.localStorage.setItem("capitalos.selectedMonth", "2026-02");
    const summaries = controlledCalls<StockHoldingsSummary>();
    mockApi.stockHoldingsSummary.mockImplementation(summaries.impl as typeof api.stockHoldingsSummary);
    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );
    fireEvent.change(screen.getByLabelText("Month"), { target: { value: "2026-01" } });
    const feb = summaries.find((a) => a[0] === "2026-02");
    const jan = summaries.find((a) => a[0] === "2026-01");

    await act(async () => jan.resolve({ ...summaryFixture, as_of_month: "2026-01", is_live: false, net_worth_boundary_at: "2026-02-01T00:00:00+00:00" }));
    expect(await screen.findByText("STOCK VALUE — 2026-01")).toBeInTheDocument();
    await act(async () => feb.resolve({ ...summaryFixture, as_of_month: "2026-02", is_live: false }));
    expect(screen.queryByText("STOCK VALUE — 2026-02")).not.toBeInTheDocument();
    await waitFor(() => expect(feb.signal?.aborted).toBe(true));
  });

  it("keeps the previous month on screen (dimmed, aria-busy) while the next loads", async () => {
    window.localStorage.setItem("capitalos.selectedMonth", "2026-02");
    const summaries = controlledCalls<StockHoldingsSummary>();
    mockApi.stockHoldingsSummary.mockImplementation(summaries.impl as typeof api.stockHoldingsSummary);
    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );
    await act(async () => summaries.find((a) => a[0] === "2026-02").resolve(summaryFixture));
    expect(await screen.findByText("STOCK VALUE — 2026-02")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Month"), { target: { value: "2026-01" } });
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
    const kept = screen.getByText("STOCK VALUE — 2026-02");
    expect(kept.closest("[aria-busy]")).toHaveAttribute("aria-busy", "true");
    expect(screen.getAllByRole("status").some((el) => el.textContent?.includes("Updating"))).toBe(true);
  });
});
