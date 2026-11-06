import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MonthBridgeCard from "../components/MonthBridgeCard";
import { BRIDGE_LINKS } from "../lib/monthBridge";
import { api } from "../lib/api";
import type { BridgeLine, MonthBridge } from "../lib/api";
import { clearApiCache } from "../lib/useApiResource";

// #240: Overview's "This month" bridge. Synthetic numbers only.

vi.mock("../lib/api", () => ({
  api: { monthBridge: vi.fn() },
}));

const mockApi = vi.mocked(api, true);

function line(key: string, label: string, amount: number, extra: Partial<BridgeLine> = {}): BridgeLine {
  return { key, label, amount, status: "ok", reason: null, parts: [], notes: [], ...extra };
}

function makeBridge(overrides: Partial<MonthBridge> = {}): MonthBridge {
  const nw = { total: 0, cash: 0, stocks_funds: 0, crypto: 0, liabilities: 0 };
  const lines = [
    line("new_money", "New money in", 6000, {
      status: "partial",
      reason: "No cash record for Sharekhan: money paid in or taken out there is in Unexplained",
      parts: [
        { key: "deposits", label: "Deposits", amount: 6000 },
        { key: "withdrawals", label: "Withdrawals", amount: 0 },
      ],
      notes: [{ key: "internal_transfers", label: "1 transfer(s) from your own accounts to a broker: not new money", amount: 2000 }],
    }),
    line("markets", "Markets", 19400, {
      parts: [
        { key: "stocks", label: "Stocks & funds", amount: 15100 },
        { key: "crypto", label: "Crypto", amount: 4300 },
      ],
    }),
    line("fx", "FX", -2800),
    line("dividends_interest", "Dividends & interest", 650),
    line("cash_kept", "Cash kept", 1450, {
      parts: [
        { key: "income", label: "Income", amount: 9200 },
        { key: "spending", label: "Spending", amount: -7750 },
      ],
    }),
  ];
  return {
    as_of_month: "2026-11",
    base_currency: "SGD",
    snapshot_day: 1,
    is_live: true,
    period_start: "2026-11-01",
    period_end: "2026-11-04T14:05:00+08:00",
    start: {
      month: "2026-10",
      boundary_at: "2026-11-01T00:00:00+00:00",
      as_of: "2026-10-31T00:00:00+00:00",
      value: 1_260_600,
      net_worth: { ...nw, total: 1_260_600 },
      baseline_missing: false,
    },
    end: {
      month: "2026-11",
      boundary_at: "2026-11-04T14:05:00+08:00",
      as_of: "2026-11-04T00:00:00+00:00",
      value: 1_284_500,
      net_worth: { ...nw, total: 1_284_500 },
      baseline_missing: false,
    },
    change: 23_900,
    lines,
    unexplained: line("unexplained", "Unexplained", -800, {
      reason: "What the lines above can't account for; its known parts are listed",
      parts: [
        { key: "untracked_trades", label: "Bought or sold with no cash record (Sharekhan)", amount: 500 },
        { key: "other", label: "Other", amount: -1300 },
      ],
      notes: [{ key: "not_updated", label: "No data after 2026-11-01: DBS, HSBC", amount: null }],
    }),
    liabilities_change: 350,
    movers: [
      { asset_id: 1, symbol: "NVDA", name: "NVDA", asset_class: "STOCK", start_value: 44_100, end_value: 48_200, change: 4100, price_effect: 4350, quantity_effect: 0, fx_effect: -250, market_effect: 4100, cause: "price" },
      { asset_id: null, symbol: "ETH", name: "ETH", asset_class: "CRYPTO", start_value: 9000, end_value: 12_200, change: 3200, price_effect: 3200, quantity_effect: 0, fx_effect: 0, market_effect: 3200, cause: "price" },
      { asset_id: 4, symbol: "ABT", name: "ABT", asset_class: "STOCK", start_value: 15_000, end_value: 0, change: -15_000, price_effect: 600, quantity_effect: -15_600, fx_effect: 0, market_effect: 600, cause: "price" },
    ],
    trades: [
      { asset_id: 4, symbol: "ABT", name: "ABT", asset_class: "STOCK", amount: -15_600, side: "sold", cash_recorded: true },
      { asset_id: 3, symbol: "MMF", name: "MMF", asset_class: "FUND", amount: 5000, side: "bought", cash_recorded: false },
    ],
    fx_incomplete: false,
    fx_missing_currencies: [],
    fx_stale_currencies: [],
    ...overrides,
  };
}

function renderCard(month = "2026-11", currency = "SGD") {
  return render(
    <MemoryRouter>
      <MonthBridgeCard month={month} baseCurrency={currency} />
    </MemoryRouter>,
  );
}

describe("<MonthBridgeCard>", () => {
  beforeEach(() => {
    clearApiCache();
    vi.clearAllMocks();
  });

  it("goes from the last close through each line and the unexplained rest to now", async () => {
    mockApi.monthBridge.mockResolvedValue(makeBridge());
    renderCard();
    await screen.findByTestId("bridge-start");
    expect(mockApi.monthBridge).toHaveBeenCalledWith("2026-11", "SGD");

    expect(screen.getByText("THIS MONTH")).toBeInTheDocument();
    expect(within(screen.getByTestId("bridge-start")).getByText("Oct 2026 close")).toBeInTheDocument();
    expect(within(screen.getByTestId("bridge-start")).getByText("S$ 1,260,600")).toBeInTheDocument();
    expect(within(screen.getByTestId("bridge-end")).getByText("S$ 1,284,500")).toBeInTheDocument();
    expect(within(screen.getByTestId("bridge-end")).getByText(/= Now · 4 Nov 2026/)).toBeInTheDocument();

    const rows = screen.getAllByTestId(/^bridge-line-/).map((row) => row.getAttribute("data-testid"));
    expect(rows).toEqual([
      "bridge-line-new_money",
      "bridge-line-markets",
      "bridge-line-fx",
      "bridge-line-dividends_interest",
      "bridge-line-cash_kept",
      "bridge-line-unexplained",
    ]);
    expect(within(screen.getByTestId("bridge-line-markets")).getByText("▲")).toBeInTheDocument();
    expect(within(screen.getByTestId("bridge-line-markets")).getByText("+S$ 19,400")).toBeInTheDocument();
    expect(within(screen.getByTestId("bridge-line-fx")).getByText("-S$ 2,800")).toBeInTheDocument();
    // The residual is a row like the others, never hidden.
    expect(within(screen.getByTestId("bridge-line-unexplained")).getByText("-S$ 800.00")).toBeInTheDocument();
    // Markets says how it splits between stocks and crypto.
    expect(within(screen.getByTestId("bridge-line-markets")).getByText(/stocks & funds \+S\$ 15,100 · crypto \+S\$ 4,300/)).toBeInTheDocument();
    expect(screen.getByText(/Month to date: flows from 1 Nov 2026/)).toBeInTheDocument();
    expect(screen.getByText(/Cards owe S\$ 350.00 more than at the start; card spending is in Cash kept/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What moved net worth since the Oct 2026 close" })).toBeInTheDocument();
  });

  it("flags a line it can only partly compute, and says why when opened", async () => {
    mockApi.monthBridge.mockResolvedValue(makeBridge());
    renderCard();
    const row = await screen.findByTestId("bridge-line-new_money");
    expect(within(row).getByText("partial")).toBeInTheDocument();
    expect(within(row).queryByText(/No cash record for Sharekhan/)).not.toBeInTheDocument();

    const toggle = within(row).getByRole("button", { name: /New money in/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(within(row).getByText(/No cash record for Sharekhan/)).toBeInTheDocument();
    expect(within(row).getByText("Deposits")).toBeInTheDocument();
    expect(within(row).getByText(/not new money: S\$ 2,000/)).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: BRIDGE_LINKS.new_money.label })).toHaveAttribute("href", "/cash");
  });

  it("opens the unexplained rest to its named parts and links each line to its page", async () => {
    mockApi.monthBridge.mockResolvedValue(makeBridge());
    renderCard();
    const rest = await screen.findByTestId("bridge-line-unexplained");
    fireEvent.click(within(rest).getByRole("button", { name: /Unexplained/ }));
    expect(within(rest).getByText("Bought or sold with no cash record (Sharekhan)")).toBeInTheDocument();
    expect(within(rest).getByText("No data after 2026-11-01: DBS, HSBC")).toBeInTheDocument();
    expect(within(rest).getByRole("link")).toHaveAttribute("href", "/wealth/history");

    const kept = screen.getByTestId("bridge-line-cash_kept");
    fireEvent.click(within(kept).getByRole("button", { name: /Cash kept/ }));
    expect(within(kept).getByRole("link")).toHaveAttribute("href", "/cash-flow");
    expect(within(kept).getByText("-S$ 7,750")).toBeInTheDocument();
  });

  it("lists the top movers with their main cause", async () => {
    mockApi.monthBridge.mockResolvedValue(makeBridge());
    renderCard();
    const nvda = await screen.findByTestId("bridge-mover-NVDA");
    expect(nvda).toHaveTextContent("NVDA ▲+S$ 4,100 (price)");
    // A holding sold this month shows its market move, not the sale.
    expect(screen.getByTestId("bridge-mover-ABT")).toHaveTextContent("ABT ▲+S$ 600.00 (price)");
  });

  it("lists purchases and sales apart, not as gains or losses", async () => {
    mockApi.monthBridge.mockResolvedValue(makeBridge());
    renderCard();
    expect(await screen.findByText("BOUGHT AND SOLD")).toBeInTheDocument();
    expect(screen.getByTestId("bridge-trade-ABT")).toHaveTextContent("Sold ABT S$ 15,600 (to cash)");
    expect(screen.getByTestId("bridge-trade-MMF")).toHaveTextContent("Bought MMF S$ 5,000");
    expect(screen.getByTestId("bridge-trade-MMF")).not.toHaveTextContent("from cash");
  });

  it("names a past month's month-end instead of now", async () => {
    mockApi.monthBridge.mockResolvedValue(
      makeBridge({
        as_of_month: "2026-09",
        is_live: false,
        start: { ...makeBridge().start, month: "2026-08" },
        end: { ...makeBridge().end, month: "2026-09", boundary_at: "2026-10-01T00:00:00+00:00" },
        period_start: "2026-09-01",
      }),
    );
    renderCard("2026-09");
    await screen.findByTestId("bridge-start");
    expect(mockApi.monthBridge).toHaveBeenCalledWith("2026-09", "SGD");
    expect(screen.getByText("SEP 2026")).toBeInTheDocument();
    expect(within(screen.getByTestId("bridge-start")).getByText("Aug 2026 close")).toBeInTheDocument();
    expect(within(screen.getByTestId("bridge-end")).getByText("= Sep 2026 close")).toBeInTheDocument();
    expect(screen.getByText(/Whole month: flows from 1 Sep 2026/)).toBeInTheDocument();
  });

  it("says there is nothing to compare with when the start has no data", async () => {
    mockApi.monthBridge.mockResolvedValue(
      makeBridge({ start: { ...makeBridge().start, value: 0, as_of: null, baseline_missing: true } }),
    );
    renderCard();
    expect(await screen.findByTestId("bridge-no-baseline")).toHaveTextContent("No comparison: no data for Oct 2026.");
    expect(screen.queryByTestId("bridge-line-markets")).not.toBeInTheDocument();
  });

  it("shows a failed load with a retry, not a zero", async () => {
    mockApi.monthBridge.mockRejectedValueOnce(new Error("boom"));
    renderCard();
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load this month's changes");
    mockApi.monthBridge.mockResolvedValue(makeBridge());
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByTestId("bridge-start")).toBeInTheDocument());
  });

  it("shows amounts in the currency of the reply", async () => {
    mockApi.monthBridge.mockResolvedValue(makeBridge({ base_currency: "USD" }));
    renderCard("2026-11", "USD");
    const start = await screen.findByTestId("bridge-start");
    expect(within(start).getByText("USD 1,260,600")).toBeInTheDocument();
  });
});
