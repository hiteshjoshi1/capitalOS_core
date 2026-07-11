import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import WealthHistory from "../routes/WealthHistory";
import { api } from "../lib/api";
import type { WealthTimeline, WealthTimelinePoint } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    netWorthTimeline: vi.fn(),
    netWorthTimelineBackfill: vi.fn(),
    netWorthTimelineMovers: vi.fn(),
    dividendsSummary: vi.fn(),
    cashFlowDetail: vi.fn(),
    spendingSummary: vi.fn(),
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
    },
  };
}

const emptyDividends = { from_month: "2026-01", to_month: "2026-06", period: "month" as const, base_currency: "SGD", assumed_tax_rate: 0, country_tax_rates: {}, buckets: [] };
const emptyCashFlow = {
  month: "2026-06",
  base_currency: "SGD",
  income_total: 0,
  expense_total: 0,
  net: 0,
  savings_rate: null,
  calculation: "transactions",
  analytics: {
    burn_rate: null,
    prior_month: null,
    prior_month_net: null,
    free_cash_flow_change_vs_prior_month: null,
    outflow_categories: [],
    inflow_categories: [],
    outflow_recurring_split: [],
    inflow_recurring_split: [],
    outflow_fixed_variable_split: [],
    inflow_source_mix: [],
    top_outflow_merchants: [],
    largest_inflow_drivers: [],
    outflow_category_deltas: [],
    deterioration_drivers: [],
    trend: [],
    waterfall: {
      starting_cash: null,
      snapshot_start_as_of: null,
      snapshot_start_boundary_at: null,
      inflows: 0,
      outflows: 0,
      transfers_and_funding: null,
      investment_and_fx_effects: null,
      other_cash_movements: null,
      snapshot_end_as_of: null,
      snapshot_end_boundary_at: null,
      boundary_exact: false,
      availability_message: null,
      ending_cash: null,
    },
    answers: [],
  },
  income: { total: 0, categories: [] },
  expenses: { total: 0, categories: [] },
} as never;

describe("WealthHistory route", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.dividendsSummary.mockResolvedValue(emptyDividends as never);
    mockApi.cashFlowDetail.mockResolvedValue(emptyCashFlow as never);
    mockApi.spendingSummary.mockResolvedValue({ month: "2026-06", base_currency: "SGD", income_total: 0, expense_total: 0, net: 0, savings_rate: null, income_categories: [], expense_categories: [] } as never);
    mockApi.netWorthTimelineMovers.mockResolvedValue({ compare_month: "2026-05", gainers: [], detractors: [] });
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

  it("generating history calls the backfill endpoint and refetches the timeline", async () => {
    mockApi.netWorthTimeline.mockResolvedValueOnce(timeline([gapPoint("2026-06")]));
    mockApi.netWorthTimelineBackfill.mockResolvedValue({ months_written: 1, base_currency: "SGD" });
    mockApi.netWorthTimeline.mockResolvedValueOnce(timeline([dataPoint("2026-06")]));

    render(
      <MemoryRouter>
        <WealthHistory />
      </MemoryRouter>,
    );

    const generateBtn = await screen.findByRole("button", { name: "Generate history" });
    fireEvent.click(generateBtn);

    await waitFor(() => {
      expect(mockApi.netWorthTimelineBackfill).toHaveBeenCalledWith(24, "SGD");
    });
    await waitFor(() => {
      expect(mockApi.netWorthTimeline).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText("Net worth")).toBeInTheDocument();
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

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
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
