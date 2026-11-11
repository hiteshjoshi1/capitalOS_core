import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CompareMonthsCard from "../components/CompareMonthsCard";
import WealthHistoryChart from "../components/WealthHistoryChart";
import { api } from "../lib/api";
import type { BridgeLine, SpanBridge, WealthTimelinePoint } from "../lib/api";
import { clearApiCache } from "../lib/useApiResource";
import { lastYearSeries, monthOptions } from "../lib/wealthHistoryAnalysis";

// #398: History → Compare two months (U20) and the "vs last year" line (U21). Synthetic numbers.

vi.mock("../lib/api", () => ({
  api: { spanBridge: vi.fn() },
}));

const mockApi = vi.mocked(api, true);

function line(key: string, label: string, amount: number, extra: Partial<BridgeLine> = {}): BridgeLine {
  return { key, label, amount, status: "ok", reason: null, parts: [], notes: [], ...extra };
}

function makeSpan(overrides: Partial<SpanBridge> = {}): SpanBridge {
  const nw = { total: 0, cash: 0, stocks_funds: 0, crypto: 0, liabilities: 0 };
  return {
    from_month: "2026-08",
    to_month: "2026-10",
    base_currency: "SGD",
    snapshot_day: 1,
    is_live: false,
    months: [
      { month: "2026-09", start_value: 100_000, end_value: 104_000, change: 4_000 },
      { month: "2026-10", start_value: 104_000, end_value: 110_000, change: 6_000 },
    ],
    start: { month: "2026-08", boundary_at: "2026-09-01T00:00:00+00:00", as_of: null, value: 100_000, net_worth: { ...nw, total: 100_000 }, baseline_missing: false },
    end: { month: "2026-10", boundary_at: "2026-11-01T00:00:00+00:00", as_of: null, value: 110_000, net_worth: { ...nw, total: 110_000 }, baseline_missing: false },
    change: 10_000,
    lines: [
      line("new_money", "New money in", 3_000),
      line("markets", "Markets", 6_500),
      line("fx", "FX", -500),
      line("dividends_interest", "Dividends & interest", 200),
      line("cash_kept", "Cash kept", 1_000, { status: "partial", reason: "Sep 2026: No transactions imported for this month" }),
    ],
    unexplained: line("unexplained", "Unexplained", -200, { parts: [{ key: "other", label: "Other", amount: -200, items: [] }] }),
    liabilities_change: 0,
    movers: [],
    trades: [],
    fx_incomplete: false,
    fx_missing_currencies: [],
    fx_fallback_used: false,
    ...overrides,
  } as SpanBridge;
}

const MONTHS = ["2026-11", "2026-10", "2026-09", "2026-08"];

function renderCard(from: string, to: string, onChange = vi.fn()) {
  render(
    <MemoryRouter>
      <CompareMonthsCard from={from} to={to} months={MONTHS} baseCurrency="SGD" onChange={onChange} />
    </MemoryRouter>,
  );
  return onChange;
}

describe("CompareMonthsCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearApiCache();
  });

  it("shows the bridge between two month-ends, adding up to the end", async () => {
    mockApi.spanBridge.mockResolvedValue(makeSpan());
    renderCard("2026-08", "2026-10");

    await waitFor(() => expect(mockApi.spanBridge).toHaveBeenCalledWith("2026-08", "2026-10", "SGD"));
    const card = screen.getByTestId("compare-months");
    expect(await within(card).findByTestId("compare-start")).toHaveTextContent("S$ 100,000");
    expect(within(card).getByTestId("compare-end")).toHaveTextContent("S$ 110,000");
    expect(within(card).getByTestId("bridge-line-markets")).toHaveTextContent("Markets");
    expect(within(card).getByTestId("compare-summary")).toHaveTextContent("over 2 months");
    expect(within(card).getByTestId("compare-summary")).toHaveTextContent(/biggest move Oct 2026/);
  });

  it("asks for a from month before the to month, without calling the API", () => {
    renderCard("2026-10", "2026-08");
    expect(screen.getByTestId("compare-invalid")).toBeInTheDocument();
    expect(mockApi.spanBridge).not.toHaveBeenCalled();
  });

  it("says nothing changed for the same month on both sides", async () => {
    mockApi.spanBridge.mockResolvedValue(makeSpan({ months: [], lines: [], change: 0 }));
    renderCard("2026-10", "2026-10");
    expect(await screen.findByTestId("compare-same-month")).toBeInTheDocument();
  });

  it("reports a picked month", async () => {
    mockApi.spanBridge.mockResolvedValue(makeSpan());
    const onChange = renderCard("2026-08", "2026-10");
    fireEvent.change(screen.getByLabelText(/From the close of/), { target: { value: "2026-09" } });
    expect(onChange).toHaveBeenCalledWith({ from: "2026-09", to: "2026-10" });
    fireEvent.change(screen.getByLabelText(/^to/), { target: { value: "2026-11" } });
    expect(onChange).toHaveBeenCalledWith({ from: "2026-08", to: "2026-11" });
  });
});

describe("History helpers (#398)", () => {
  it("lists months newest first", () => {
    expect(monthOptions("2025-11", "2026-02")).toEqual(["2026-02", "2026-01", "2025-12", "2025-11"]);
  });

  it("finds the same month a year earlier, null where there's no data", () => {
    const point = (month: string, total: number, gap = false): WealthTimelinePoint => ({
      month,
      anchor_date: `${month}-01`,
      total,
      cash: total,
      stocks_funds: 0,
      crypto: 0,
      liabilities: 0,
      source_freshness: gap ? [] : [{ platform: "DBS", as_of: `${month}-01`, days_old: 0, status: "fresh" }],
      freshness_status: "fresh",
      computed_at: gap ? null : `${month}-01T00:00:00+00:00`,
      uploads: [],
    });
    const points = [point("2026-01", 200), point("2026-02", 210)];
    const older = [point("2025-01", 150), point("2025-02", 0, true), ...points];
    expect(lastYearSeries(points, older)).toEqual([150, null]);
  });

  it("draws the last-year line and its legend on the chart", () => {
    const point = (month: string, total: number): WealthTimelinePoint => ({
      month,
      anchor_date: `${month}-01`,
      total,
      cash: total,
      stocks_funds: 0,
      crypto: 0,
      liabilities: 0,
      source_freshness: [{ platform: "DBS", as_of: `${month}-01`, days_old: 0, status: "fresh" }],
      freshness_status: "fresh",
      computed_at: `${month}-01T00:00:00+00:00`,
      uploads: [],
    });
    const points = [point("2026-01", 200), point("2026-02", 210), point("2026-03", 220)];
    render(
      <WealthHistoryChart
        points={points}
        now={{ total: 225, cash: 225, stocks_funds: 0, crypto: 0, liabilities: 0, as_of: null, uploads: [] }}
        mode="total"
        formatMoney={(v) => String(v)}
        formatMoneyShort={(v) => String(v)}
        lastYear={[150, 160, null]}
      />,
    );
    expect(screen.getAllByTestId("wh-last-year-segment")).toHaveLength(1);
    expect(screen.getByTestId("wh-last-year-legend")).toBeInTheDocument();
  });
});
