import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import WealthHistory from "../routes/WealthHistory";
import { api } from "../lib/api";
import { currentMonth } from "../lib/format";
import { shiftMonth } from "../lib/selectedMonth";
import type { HistoryGenerateStatus, WealthTimeline, WealthTimelinePoint } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    netWorthTimeline: vi.fn(),
    netWorthTimelineBackfill: vi.fn(),
    netWorthTimelineGenerate: vi.fn(),
    netWorthTimelineGenerateStatus: vi.fn(),
    netWorthTimelineMovers: vi.fn(),
    dividendsSummary: vi.fn(),
    cashFlowDetail: vi.fn(),
    cashFlowTrend: vi.fn(),
    spendingSummary: vi.fn(),
    spanBridge: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

function gapPoint(month: string): WealthTimelinePoint {
  return {
    month,
    anchor_date: `${month}-01`,
    total: 0,
    cash: 0,
    stocks_funds: 0,
    crypto: 0,
    liabilities: 0,
    source_freshness: [],
    freshness_status: "fresh",
    computed_at: null,
    uploads: [],
  };
}

function dataPoint(month: string, overrides: Partial<WealthTimelinePoint> = {}): WealthTimelinePoint {
  return {
    month,
    anchor_date: `${month}-01`,
    total: 1000,
    cash: 300,
    stocks_funds: 600,
    crypto: 100,
    liabilities: 0,
    source_freshness: [{ platform: "DBS", as_of: `${month}-01`, days_old: 0, status: "fresh" }],
    freshness_status: "fresh",
    computed_at: `${month}-01T00:00:00+00:00`,
    uploads: [],
    ...overrides,
  };
}

function timeline(points: WealthTimelinePoint[]): WealthTimeline {
  const last = points[points.length - 1];
  return {
    base_currency: "SGD",
    points,
    now: {
      total: last.total,
      cash: last.cash,
      stocks_funds: last.stocks_funds,
      crypto: last.crypto,
      liabilities: last.liabilities,
      as_of: "2026-06-15T00:00:00+00:00",
      uploads: [],
    },
  };
}

function runStatus(overrides: Partial<HistoryGenerateStatus> = {}): HistoryGenerateStatus {
  return {
    status: "running",
    stage: "fx",
    base_currency: "SGD",
    months: 10,
    months_total: 0,
    months_done: 0,
    current_month: null,
    months_written: 0,
    started_at: "2026-06-15T00:00:00+00:00",
    finished_at: null,
    fx: null,
    error: null,
    ...overrides,
  };
}

const emptyDividends = { from_month: "2026-01", to_month: "2026-06", period: "month" as const, base_currency: "SGD", assumed_tax_rate: 0, country_tax_rates: {}, buckets: [] };
const emptyCashFlow = { month: "2026-06", base_currency: "SGD", trend: [] } as never;

describe("WealthHistory route", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // The selected month is shared per browser (#223): start each test on the current month.
    window.localStorage.removeItem("capitalos.selectedMonth");
    mockApi.dividendsSummary.mockResolvedValue(emptyDividends as never);
    mockApi.cashFlowTrend.mockResolvedValue(emptyCashFlow as never);
    mockApi.spendingSummary.mockResolvedValue({ month: "2026-06", base_currency: "SGD", income_total: 0, expense_total: 0, net: 0, savings_rate: null, income_categories: [], expense_categories: [] } as never);
    mockApi.netWorthTimelineMovers.mockResolvedValue({ compare_month: "2026-05", gainers: [], detractors: [] });
    mockApi.netWorthTimelineGenerateStatus.mockResolvedValue(runStatus({ status: "idle", stage: "done", months: 0 }));
  });

  it("shows an empty state with a Generate history action when every point is a gap", async () => {
    mockApi.netWorthTimeline.mockResolvedValue(timeline([gapPoint("2026-04"), gapPoint("2026-05"), gapPoint("2026-06")]));

    render(
      <MemoryRouter>
        <WealthHistory />
      </MemoryRouter>,
    );

    expect(await screen.findByText("No history yet")).toBeInTheDocument();
    expect(screen.queryByText("Net worth")).not.toBeInTheDocument();
  });

  it("generating history runs in the background with progress, then refetches the timeline (#292)", async () => {
    mockApi.netWorthTimeline.mockResolvedValueOnce(timeline([gapPoint("2026-06")]));
    mockApi.netWorthTimeline.mockResolvedValueOnce(timeline([dataPoint("2026-06")]));
    mockApi.netWorthTimelineGenerate.mockResolvedValue(runStatus());
    mockApi.netWorthTimelineGenerateStatus
      .mockResolvedValueOnce(runStatus({ status: "idle", stage: "done" }))
      .mockResolvedValueOnce(runStatus({ stage: "months", months_total: 10, months_done: 2, current_month: "2026-03" }))
      .mockResolvedValue(runStatus({ status: "completed", stage: "done", months_total: 10, months_done: 10, months_written: 9 }));

    render(
      <MemoryRouter>
        <WealthHistory />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Generate history" }));

    // No months: the server's default, the span of the data.
    await waitFor(() => expect(mockApi.netWorthTimelineGenerate).toHaveBeenCalledWith("SGD", undefined));
    expect(await screen.findByText(/Fetching past exchange rates…/)).toBeInTheDocument();
    expect(await screen.findByText(/Valuing month 3 of 10 \(Mar/, {}, { timeout: 3000 })).toBeInTheDocument();
    expect(await screen.findByText("Net worth", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(mockApi.netWorthTimeline).toHaveBeenCalledTimes(2);
    expect(mockApi.netWorthTimelineBackfill).not.toHaveBeenCalled();
  });

  it("a run already going when the page opens shows its progress (#292)", async () => {
    mockApi.netWorthTimeline.mockResolvedValue(timeline([dataPoint("2026-06")]));
    mockApi.netWorthTimelineGenerateStatus.mockResolvedValue(
      runStatus({ stage: "months", months_total: 4, months_done: 0, current_month: "2026-02" }),
    );

    render(
      <MemoryRouter>
        <WealthHistory />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/Valuing month 1 of 4/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refreshing…" })).toBeDisabled();
  });

  it("a failed run says so and offers a retry (#292)", async () => {
    mockApi.netWorthTimeline.mockResolvedValue(timeline([gapPoint("2026-06")]));
    mockApi.netWorthTimelineGenerate.mockResolvedValue(
      runStatus({ status: "failed", stage: "done", error: "History generation failed. Try again." }),
    );

    render(
      <MemoryRouter>
        <WealthHistory />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Generate history" }));
    expect(await screen.findByText("Couldn't generate history")).toBeInTheDocument();
  });

  it("says when the capped FX fetch left rates for the next run (#292)", async () => {
    mockApi.netWorthTimeline.mockResolvedValue(timeline([gapPoint("2026-06")]));
    mockApi.netWorthTimelineGenerate.mockResolvedValue(
      runStatus({ status: "completed", stage: "done", fx: { status: "partial", remaining_requests: 3, unsupported_currencies: [] } }),
    );

    render(
      <MemoryRouter>
        <WealthHistory />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Generate history" }));
    expect(await screen.findByText(/Some past exchange rates are still missing/)).toBeInTheDocument();
  });

  it("the default range is the span of the data, and Carried is explained (#292)", async () => {
    mockApi.netWorthTimeline.mockResolvedValue({
      ...timeline([dataPoint("2026-05"), dataPoint("2026-06")]),
      data_span: { first_month: "2025-11", months: 8 },
    });

    render(
      <MemoryRouter>
        <WealthHistory />
      </MemoryRouter>,
    );

    await waitFor(() => expect(mockApi.netWorthTimeline).toHaveBeenCalledWith(12, "SGD"));
    expect(mockApi.netWorthTimeline).toHaveBeenNthCalledWith(1, 24, "SGD");
    expect(screen.getByText(/means no new statement or price for that month/)).toBeInTheDocument();
  });

  it("renders the chart, attribution strip, and a table row per month once populated", async () => {
    mockApi.netWorthTimeline.mockResolvedValue(
      timeline([dataPoint("2026-04", { total: 900 }), dataPoint("2026-05", { total: 950 }), dataPoint("2026-06", { total: 1000 })]),
    );

    render(
      <MemoryRouter>
        <WealthHistory />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Net worth")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Net worth over time" })).toBeInTheDocument();
    expect(screen.getByText("What moved it — month-over-month, by component")).toBeInTheDocument();

    const table = screen.getByRole("table");
    const rows = within(table).getAllByRole("row");
    // header + 3 month rows
    expect(rows).toHaveLength(4);
    expect(within(table).getByText("S$ 1,000")).toBeInTheDocument();
  });

  it("shows '—' for gap months and the freshness status for observed months in the table", async () => {
    mockApi.netWorthTimeline.mockResolvedValue(
      timeline([dataPoint("2026-04"), gapPoint("2026-05"), dataPoint("2026-06", { freshness_status: "carried" })]),
    );

    render(
      <MemoryRouter>
        <WealthHistory />
      </MemoryRouter>,
    );

    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(within(rows[1]).getAllByText("—").length).toBeGreaterThan(0);
    expect(within(rows[2]).getByText("carried")).toBeInTheDocument();
  });

  it("switching the range control refetches the timeline with the new month count", async () => {
    mockApi.netWorthTimeline.mockResolvedValue(timeline([dataPoint("2026-06")]));

    render(
      <MemoryRouter>
        <WealthHistory />
      </MemoryRouter>,
    );

    await screen.findByText("Net worth");
    expect(mockApi.netWorthTimeline).toHaveBeenCalledWith(24, "SGD");

    fireEvent.click(screen.getByRole("button", { name: "1Y" }));

    await waitFor(() => {
      expect(mockApi.netWorthTimeline).toHaveBeenCalledWith(12, "SGD");
    });
  });

  it("switching series mode to 'By component' shows the per-component legend", async () => {
    mockApi.netWorthTimeline.mockResolvedValue(timeline([dataPoint("2026-06")]));

    const { container } = render(
      <MemoryRouter>
        <WealthHistory />
      </MemoryRouter>,
    );

    await screen.findByText("Net worth");
    expect(container.querySelector(".whChartWrap .whSeriesLegend")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "By component" }));

    const legendItems = container.querySelectorAll(".whChartWrap .whSeriesLegend .whSeriesLegendItem");
    expect(Array.from(legendItems).map((el) => el.textContent)).toEqual([
      "Stocks & funds",
      "Cash",
      "Crypto",
    ]);
  });

  it("selecting a month from the attribution strip opens the drill-down panel and fetches its context", async () => {
    mockApi.netWorthTimeline.mockResolvedValue(
      timeline([dataPoint("2026-05", { total: 900 }), dataPoint("2026-06", { total: 1000 })]),
    );

    const { container } = render(
      <MemoryRouter>
        <WealthHistory />
      </MemoryRouter>,
    );

    await screen.findByText("Net worth");
    expect(screen.queryByLabelText(/Details for/)).not.toBeInTheDocument();

    const columns = container.querySelectorAll(".whAttribCol");
    expect(columns.length).toBeGreaterThan(0);
    fireEvent.click(columns[columns.length - 1]);

    await waitFor(() => {
      expect(screen.getByLabelText(/Details for June 2026/)).toBeInTheDocument();
    });
    expect(mockApi.netWorthTimelineMovers).toHaveBeenCalledWith("2026-06", "SGD", 8);

    fireEvent.click(screen.getByRole("button", { name: "Close details" }));
    await waitFor(() => {
      expect(screen.queryByLabelText(/Details for/)).not.toBeInTheDocument();
    });
  });

  it("changing the base currency resets any open drill-down selection", async () => {
    mockApi.netWorthTimeline.mockResolvedValue(
      timeline([dataPoint("2026-05", { total: 900 }), dataPoint("2026-06", { total: 1000 })]),
    );

    const { container } = render(
      <MemoryRouter>
        <WealthHistory />
      </MemoryRouter>,
    );

    await screen.findByText("Net worth");
    const columns = container.querySelectorAll(".whAttribCol");
    fireEvent.click(columns[columns.length - 1]);
    await waitFor(() => {
      expect(screen.getByLabelText(/Details for/)).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.change(screen.getByRole("combobox", { name: "Base currency" }), { target: { value: "USD" } });
    });

    await waitFor(() => {
      expect(screen.queryByLabelText(/Details for/)).not.toBeInTheDocument();
    });
  });
});

// #223: History follows the shared selected month (the pill every page shows).
describe("WealthHistory selected month", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.removeItem("capitalos.selectedMonth");
    mockApi.dividendsSummary.mockResolvedValue(emptyDividends as never);
    mockApi.cashFlowTrend.mockResolvedValue(emptyCashFlow as never);
    mockApi.spendingSummary.mockResolvedValue({ month: "2026-05", base_currency: "SGD", income_total: 0, expense_total: 0, net: 0, savings_rate: null, income_categories: [], expense_categories: [] } as never);
    mockApi.netWorthTimelineMovers.mockResolvedValue({ compare_month: "2026-04", gainers: [], detractors: [] });
    mockApi.netWorthTimeline.mockResolvedValue(
      timeline([dataPoint("2026-04", { total: 900 }), dataPoint("2026-05", { total: 950 }), dataPoint("2026-06", { total: 1000 })]),
    );
  });

  it("shows the month pill, marks the selected month on the chart and opens its drill-down", async () => {
    window.localStorage.setItem("capitalos.selectedMonth", "2026-05");

    render(
      <MemoryRouter>
        <WealthHistory />
      </MemoryRouter>,
    );

    expect(await screen.findByLabelText(/Details for May 2026/)).toBeInTheDocument();
    expect(screen.getByLabelText("Month")).toHaveValue("2026-05");
    expect(screen.getByTestId("wh-selected-month")).toHaveTextContent("Selected month: May 2026");
    // The drill-down fetches its movers from an effect that can run after the panel paints (#233).
    await waitFor(() => expect(mockApi.netWorthTimelineMovers).toHaveBeenCalledWith("2026-05", "SGD", 8));
  });

  it("the open month marks the live point and opens no drill-down", async () => {
    render(
      <MemoryRouter>
        <WealthHistory />
      </MemoryRouter>,
    );

    await screen.findByText("Net worth");
    expect(screen.getByLabelText("Month")).toHaveValue(currentMonth());
    expect(screen.getByTestId("wh-selected-month")).toHaveTextContent("Selected month: now");
    expect(screen.queryByLabelText(/Details for/)).not.toBeInTheDocument();
  });

  it("picking a month on the pill opens its drill-down; picking one on the chart sets the shared month", async () => {
    const { container } = render(
      <MemoryRouter>
        <WealthHistory />
      </MemoryRouter>,
    );
    await screen.findByText("Net worth");

    fireEvent.change(screen.getByLabelText("Month"), { target: { value: "2026-04" } });
    expect(await screen.findByLabelText(/Details for April 2026/)).toBeInTheDocument();
    expect(window.localStorage.getItem("capitalos.selectedMonth")).toBe("2026-04");

    // Closing the drill-down keeps the month; choosing a month on the chart moves it.
    fireEvent.click(screen.getByRole("button", { name: "Close details" }));
    await waitFor(() => expect(screen.queryByLabelText(/Details for/)).not.toBeInTheDocument());
    expect(screen.getByLabelText("Month")).toHaveValue("2026-04");

    const columns = container.querySelectorAll(".whAttribCol");
    fireEvent.click(columns[columns.length - 1]);
    expect(await screen.findByLabelText(/Details for June 2026/)).toBeInTheDocument();
    // The same key every other page reads, so Overview and Stocks follow.
    expect(window.localStorage.getItem("capitalos.selectedMonth")).toBe("2026-06");
    expect(screen.getByLabelText("Month")).toHaveValue("2026-06");
  });

  it("widens the range to reach a selected month older than it", async () => {
    window.localStorage.setItem("capitalos.selectedMonth", shiftMonth(currentMonth(), -30));

    render(
      <MemoryRouter>
        <WealthHistory />
      </MemoryRouter>,
    );

    await screen.findByText("Net worth");
    expect(mockApi.netWorthTimeline).toHaveBeenCalledWith(60, "SGD");
    expect(mockApi.netWorthTimeline).not.toHaveBeenCalledWith(24, "SGD");
  });
});

// #398: History's Compare mode (U20) and the "vs last year" line (U21).
describe("WealthHistory compare and last year", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.removeItem("capitalos.selectedMonth");
    mockApi.dividendsSummary.mockResolvedValue(emptyDividends as never);
    mockApi.cashFlowTrend.mockResolvedValue(emptyCashFlow as never);
    mockApi.netWorthTimelineMovers.mockResolvedValue({ compare_month: "2026-05", gainers: [], detractors: [] });
    mockApi.netWorthTimelineGenerateStatus.mockResolvedValue(runStatus({ status: "idle", stage: "done", months: 0 }));
    mockApi.netWorthTimeline.mockResolvedValue(timeline([dataPoint("2026-05"), dataPoint("2026-06")]));
  });

  it("switches to Compare: the card asks for a year ago to now, and the chart goes", async () => {
    mockApi.spanBridge.mockResolvedValue(new Promise(() => undefined) as never);
    render(
      <MemoryRouter>
        <WealthHistory />
      </MemoryRouter>,
    );
    await screen.findByText("Net worth");
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));
    expect(await screen.findByTestId("compare-months")).toBeInTheDocument();
    const now = currentMonth();
    await waitFor(() => expect(mockApi.spanBridge).toHaveBeenCalledWith(shiftMonth(now, -12), now, "SGD"));
    expect(screen.queryByText("Net worth")).not.toBeInTheDocument();
  });

  it("vs last year loads a timeline reaching 12 months further back", async () => {
    render(
      <MemoryRouter>
        <WealthHistory />
      </MemoryRouter>,
    );
    await screen.findByText("Net worth");
    const calls = mockApi.netWorthTimeline.mock.calls.length;
    const range = mockApi.netWorthTimeline.mock.calls[calls - 1][0] as number;
    fireEvent.click(screen.getByLabelText(/vs last/));
    await waitFor(() => expect(mockApi.netWorthTimeline).toHaveBeenCalledWith(Math.min(range + 12, 120), "SGD"));
  });
});

// #149: the income-vs-spending card reads the lean trend, not the month's whole cash-flow detail.
describe("WealthHistory cash-flow trend", () => {
  it("draws income vs spending from /spending/cash-flow-trend", async () => {
    vi.clearAllMocks();
    window.localStorage.removeItem("capitalos.selectedMonth");
    mockApi.dividendsSummary.mockResolvedValue(emptyDividends as never);
    mockApi.netWorthTimelineMovers.mockResolvedValue({ compare_month: "2026-05", gainers: [], detractors: [] });
    mockApi.netWorthTimeline.mockResolvedValue(timeline([dataPoint("2026-05", { total: 950 }), dataPoint("2026-06", { total: 1000 })]));
    mockApi.cashFlowTrend.mockResolvedValue({
      month: currentMonth(),
      base_currency: "SGD",
      trend: [
        { month: "2026-05", inflows: 5000, outflows: 3000, net: 2000, savings_rate: 0.4, burn_rate: 0.6 },
        { month: "2026-06", inflows: 4000, outflows: 4500, net: -500, savings_rate: -0.125, burn_rate: 1.125 },
      ],
    });

    render(
      <MemoryRouter>
        <WealthHistory />
      </MemoryRouter>,
    );

    await waitFor(() => expect(mockApi.cashFlowTrend).toHaveBeenCalledWith(currentMonth(), "SGD"));
    const chart = await screen.findByRole("img", { name: "Income vs spending" });
    expect(within(chart).getByTitle(/May '26 income: S\$ 5,000/)).toBeInTheDocument();
    expect(within(chart).getByTitle(/Jun '26 spending: S\$ 4,500/)).toBeInTheDocument();
    expect(mockApi.cashFlowDetail).not.toHaveBeenCalled();
  });
});
