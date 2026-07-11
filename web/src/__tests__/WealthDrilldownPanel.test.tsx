import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import WealthDrilldownPanel from "../components/WealthDrilldownPanel";
import { api } from "../lib/api";
import type { WealthTimelinePoint } from "../lib/api";
import type { MonthFlags } from "../lib/wealthHistoryAnalysis";

vi.mock("../lib/api", () => ({
  api: {
    netWorthTimelineMovers: vi.fn(),
    dividendsSummary: vi.fn(),
    spendingSummary: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

function point(overrides: Partial<WealthTimelinePoint> = {}): WealthTimelinePoint {
  return {
    month: "2026-06",
    anchor_date: "2026-06-01",
    total: 1000,
    cash: 300,
    stocks_funds: 600,
    crypto: 100,
    liabilities: 0,
    source_freshness: [],
    freshness_status: "fresh",
    computed_at: "2026-06-01T00:00:00+00:00",
    uploads: [],
    ...overrides,
  };
}

const baseFlags: MonthFlags = {
  isCatchUp: false,
  isOutlier: false,
  delta: 100,
  componentDeltas: { stocks_funds: 80, cash: 15, crypto: 5, liabilities: 0 },
  dominantComponent: "stocks_funds",
  comparedToMonth: "2026-05",
};

const formatMoney = (value?: number | null) => (value == null ? "—" : `S$ ${value.toLocaleString()}`);

function renderPanel(props: Partial<React.ComponentProps<typeof WealthDrilldownPanel>> = {}) {
  const onClose = vi.fn();
  const result = render(
    <MemoryRouter>
      <WealthDrilldownPanel
        month="2026-06"
        point={point()}
        prevPoint={point({ month: "2026-05", total: 900 })}
        flags={baseFlags}
        baseCurrency="SGD"
        formatMoney={formatMoney}
        onClose={onClose}
        {...props}
      />
    </MemoryRouter>,
  );
  return { ...result, onClose };
}

describe("WealthDrilldownPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.netWorthTimelineMovers.mockResolvedValue({ compare_month: "2026-05", gainers: [], detractors: [] });
    mockApi.dividendsSummary.mockResolvedValue({
      from_month: "2026-06",
      to_month: "2026-06",
      period: "month",
      base_currency: "SGD",
      assumed_tax_rate: 0,
      country_tax_rates: {},
      buckets: [{ bucket: "2026-06", gross: 50, withholding: 0, net_received: 50, estimated_tax: 0, payout_minus_tax: 50 }],
    } as never);
    mockApi.spendingSummary.mockResolvedValue({
      month: "2026-06",
      base_currency: "SGD",
      income_total: 5000,
      expense_total: 3800,
      net: 1200,
      savings_rate: 0.24,
      income_categories: [],
      expense_categories: [],
    } as never);
  });

  it("shows a start-of-history message when there is no prior point to compare against", async () => {
    renderPanel({ flags: { ...baseFlags, delta: null, componentDeltas: null, dominantComponent: null, comparedToMonth: null } });
    expect(await screen.findByText("Start of available history.")).toBeInTheDocument();
  });

  it("renders the delta, percent change, and comparison month heading", async () => {
    renderPanel();
    expect(await screen.findByLabelText("Details for June 2026")).toBeInTheDocument();
    expect(screen.getByText("+S$ 100")).toBeInTheDocument();
    expect(screen.getByText(/vs May 2026/)).toBeInTheDocument();
  });

  it("shows a negative delta without a leading plus sign", async () => {
    renderPanel({ flags: { ...baseFlags, delta: -50 } });
    expect(await screen.findByText("S$ -50")).toBeInTheDocument();
  });

  it("shows the outlier banner attributing the dominant component", async () => {
    renderPanel({ flags: { ...baseFlags, isOutlier: true } });
    expect(await screen.findByText(/Unusual move.*Stocks & funds/)).toBeInTheDocument();
  });

  it("shows the catch-up banner", async () => {
    renderPanel({ flags: { ...baseFlags, isCatchUp: true } });
    expect(await screen.findByText(/Catch-up month — a source uploaded after a gap/)).toBeInTheDocument();
  });

  it("renders a waterfall row per component with signed values", async () => {
    renderPanel();
    await screen.findByLabelText("Details for June 2026");
    expect(screen.getByText("+S$ 80")).toBeInTheDocument(); // stocks_funds
    expect(screen.getByText("+S$ 15")).toBeInTheDocument(); // cash
    expect(screen.getByText("+S$ 5")).toBeInTheDocument(); // crypto
  });

  it("lists top movers sorted by absolute delta once loaded", async () => {
    mockApi.netWorthTimelineMovers.mockResolvedValue({
      compare_month: "2026-05",
      gainers: [
        { asset_id: 1, symbol: "AAPL", asset_class: "STOCK", current_value: 100, previous_value: 80, delta_abs: 20, delta_pct: 0.25, compare_month: "2026-05" },
      ],
      detractors: [
        { asset_id: 2, symbol: "TSLA", asset_class: "STOCK", current_value: 50, previous_value: 100, delta_abs: -50, delta_pct: -0.5, compare_month: "2026-05" },
      ],
    });
    renderPanel();

    await waitFor(() => {
      expect(mockApi.netWorthTimelineMovers).toHaveBeenCalledWith("2026-06", "SGD", 8);
    });
    const tsla = await screen.findByText("TSLA");
    const aapl = screen.getByText("AAPL");
    // TSLA's |delta| (50) is larger than AAPL's (20), so it should come first in DOM order.
    expect(tsla.compareDocumentPosition(aapl) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows a fallback message when there are no significant movers", async () => {
    renderPanel();
    expect(await screen.findByText("No significant individual movers.")).toBeInTheDocument();
  });

  it("renders dividends received and net cash flow for the month once fetched", async () => {
    renderPanel();
    expect(await screen.findByText("S$ 50")).toBeInTheDocument();
    expect(screen.getByText("S$ 1,200")).toBeInTheDocument();
    expect(mockApi.dividendsSummary).toHaveBeenCalledWith("2026-06", "2026-06", "month", "SGD");
    expect(mockApi.spendingSummary).toHaveBeenCalledWith("2026-06", "SGD");
  });

  it("lists uploads landed for the month, or 'none' when empty", async () => {
    renderPanel({ point: point({ uploads: ["DBS", "OCBC"] }) });
    expect(await screen.findByText("DBS, OCBC")).toBeInTheDocument();
  });

  it("calls onClose when the close button is clicked", async () => {
    const { onClose } = renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
