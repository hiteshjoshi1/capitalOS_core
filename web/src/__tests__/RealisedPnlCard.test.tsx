import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RealisedPnlCard from "../components/RealisedPnlCard";
import { api, type RealisedPnl } from "../lib/api";

vi.mock("../lib/api", () => ({ api: { realisedPnl: vi.fn() } }));
const mockApi = vi.mocked(api, true);

// Synthetic sales only.
const fixture: RealisedPnl = {
  base_currency: "SGD",
  month: { realised: 1250.5, sales: 2, cost_unknown: 1, fx_missing_currencies: [], sources: { ibkr: 1, cost_unknown: 1 } },
  year_to_date: { realised: -300, sales: 4, cost_unknown: 1, fx_missing_currencies: ["JPY"], sources: { ibkr: 2, fifo: 1, cost_unknown: 1 } },
  sales: [
    { trade_date: "2026-03-05", symbol: "AAA", platform: "IBKR", quantity: 5, proceeds: 649, cost: 400, realised: 930, currency: "USD", realised_base: 1250.5, source: "ibkr", fx_missing: false },
    { trade_date: "2026-03-20", symbol: "BBB", platform: "IBKR", quantity: 2, proceeds: 300, cost: null, realised: null, currency: "SGD", realised_base: null, source: "cost_unknown", fx_missing: false },
  ],
};

describe("RealisedPnlCard (#293)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.realisedPnl.mockResolvedValue(fixture);
  });

  it("shows the month and year to date, signed with arrows, and what was left out", async () => {
    render(<RealisedPnlCard month="2026-03" baseCurrency="SGD" />);
    const card = await screen.findByRole("region", { name: "Realised profit and loss" });
    expect(mockApi.realisedPnl).toHaveBeenCalledWith("2026-03", "SGD");
    expect(card).toHaveTextContent("▲ +S$ 1,251"); // D-69: whole units from 1,000
    expect(card).toHaveTextContent("2 sales");
    expect(card).toHaveTextContent("2026 to date");
    expect(card).toHaveTextContent("▼ -S$ 300.00");
    expect(card).toHaveTextContent("1 sale with no known buy cost: left out");
    expect(card).toHaveTextContent("No exchange rate for JPY: left out");
    expect(card).toHaveTextContent("IBKR's figure (2) · FIFO from your trades (1) · cost unknown (1)");
  });

  it("lists the month's sales on demand, naming the source and never showing 0 for an unknown cost", async () => {
    render(<RealisedPnlCard month="2026-03" baseCurrency="SGD" />);
    fireEvent.click(await screen.findByRole("button", { name: /Show .* sales/ }));
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("AAA");
    expect(items[0]).toHaveTextContent("IBKR's figure");
    expect(items[0]).toHaveTextContent("+USD 930.00"); // the trade currency next to the base amount
    expect(within(items[1]).getAllByText("cost unknown").length).toBeGreaterThan(0);
    expect(items[1]).not.toHaveTextContent("S$ 0");
  });

  it("says No sales when there were none", async () => {
    const none = { realised: 0, sales: 0, cost_unknown: 0, fx_missing_currencies: [], sources: {} };
    mockApi.realisedPnl.mockResolvedValue({ base_currency: "SGD", month: none, year_to_date: none, sales: [] });
    render(<RealisedPnlCard month="2026-03" baseCurrency="SGD" />);
    const card = await screen.findByRole("region", { name: "Realised profit and loss" });
    expect(within(card).getAllByText("No sales")).toHaveLength(3); // the period, the month, the year
    expect(screen.queryByRole("button", { name: /sales/ })).not.toBeInTheDocument();
  });
});

// #313: any period, grouped per stock. Synthetic data only.
const year: RealisedPnl = {
  ...fixture,
  period: { key: "last_year", start: "2025-01-01", end: "2025-12-31", label: "2025" },
  period_totals: { realised: 4200, sales: 3, cost_unknown: 1, fx_missing_currencies: [], sources: { ibkr: 2, cost_unknown: 1 } },
  years_with_sales: [2026, 2025],
  trades_from: "2025-11-03",
  platforms_without_trades: ["SHAREKHAN", "DBS_VICKERS"],
  by_instrument: [
    {
      symbol: "LOSS", platform: "IBKR", currency: "USD", sales_count: 1, quantity: 10, realised_base: -5000,
      proceeds_base: 1000, cost_base: 6000, realised: -3700, in_total: 1, cost_unknown: 0, fx_missing: false,
      sources: { ibkr: 1 }, first_sale: "2025-12-01", last_sale: "2025-12-01",
      sales: [{ trade_date: "2025-12-01", symbol: "LOSS", platform: "IBKR", quantity: 10, proceeds: 740, cost: 4440, realised: -3700, currency: "USD", realised_base: -5000, source: "ibkr", fx_missing: false }],
    },
    {
      symbol: "GAIN", platform: "IBKR", currency: "SGD", sales_count: 2, quantity: 5, realised_base: 9200,
      proceeds_base: 12000, cost_base: 2800, realised: 9200, in_total: 1, cost_unknown: 1, fx_missing: false,
      sources: { ibkr: 1, cost_unknown: 1 }, first_sale: "2025-11-10", last_sale: "2025-11-20",
      sales: [
        { trade_date: "2025-11-10", symbol: "GAIN", platform: "IBKR", quantity: 3, proceeds: 12000, cost: 2800, realised: 9200, currency: "SGD", realised_base: 9200, source: "ibkr", fx_missing: false },
        { trade_date: "2025-11-20", symbol: "GAIN", platform: "IBKR", quantity: 2, proceeds: 500, cost: null, realised: null, currency: "SGD", realised_base: null, source: "cost_unknown", fx_missing: false },
      ],
    },
  ],
};

describe("RealisedPnlCard periods and stocks (#313)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.realisedPnl.mockImplementation(async (_month, _base, period) => (period ? year : fixture));
  });

  it("asks for last year and shows its total and each stock, biggest move first, losses included", async () => {
    render(<RealisedPnlCard month="2026-03" baseCurrency="SGD" />);
    fireEvent.click(await screen.findByRole("button", { name: "Last year" }));
    expect(mockApi.realisedPnl).toHaveBeenLastCalledWith("2026-03", "SGD", { period: "last_year" });
    const table = await screen.findByRole("table");
    const card = screen.getByRole("region", { name: "Realised profit and loss" });
    expect(card).toHaveTextContent("2025");
    expect(card).toHaveTextContent("▲ +S$ 4,200");
    expect(card).toHaveTextContent("3 sales · 2 stocks");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("LOSS");
    expect(rows[0]).toHaveTextContent("▼ -S$ 5,000");
    expect(rows[1]).toHaveTextContent("GAIN");
    expect(rows[1]).toHaveTextContent("Left out: 1 with no known cost");
    expect(card).toHaveTextContent("Gains ▲ +S$ 9,200 · Losses ▼ -S$ 5,000");
    expect(screen.getByRole("button", { name: "Last year" })).toHaveAttribute("aria-pressed", "true");
  });

  it("opens a stock's sales, naming the source and never 0 for an unknown cost", async () => {
    render(<RealisedPnlCard month="2026-03" baseCurrency="SGD" />);
    fireEvent.click(await screen.findByRole("button", { name: "Last year" }));
    const open = await screen.findByRole("button", { name: "GAIN: show its sales" });
    fireEvent.click(open);
    expect(screen.getByRole("button", { name: "GAIN: hide its sales" })).toHaveAttribute("aria-expanded", "true");
    const list = screen.getByRole("list", { name: "GAIN sales" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("IBKR's figure");
    expect(within(items[1]).getAllByText("cost unknown").length).toBeGreaterThan(0);
    expect(items[1]).not.toHaveTextContent("S$ 0");
  });

  it("picks a year from the years with sales", async () => {
    render(<RealisedPnlCard month="2026-03" baseCurrency="SGD" />);
    await screen.findByRole("region", { name: "Realised profit and loss" });
    fireEvent.click(screen.getByRole("button", { name: "Year to date" }));
    const select = await screen.findByRole("combobox", { name: "Year" });
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["Year…", "2026", "2025"]);
    fireEvent.change(select, { target: { value: "2025" } });
    expect(mockApi.realisedPnl).toHaveBeenLastCalledWith("2026-03", "SGD", { period: "year", year: 2025 });
  });

  it("says where data is missing: before the first trade, and brokers with holdings only", async () => {
    render(<RealisedPnlCard month="2026-03" baseCurrency="SGD" />);
    fireEvent.click(await screen.findByRole("button", { name: "Last year" }));
    await screen.findByRole("table");
    const card = screen.getByRole("region", { name: "Realised profit and loss" });
    expect(card).toHaveTextContent("Trades in the app start on 3 Nov 2025: earlier sales aren't known yet.");
    expect(card).toHaveTextContent("Sharekhan and DBS Vickers report holdings only, no trades: no realised P&L for them.");
  });
});
