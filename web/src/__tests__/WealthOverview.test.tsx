import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import WealthOverview from "../routes/WealthOverview";
import { api } from "../lib/api";
import type { RealtimeEventEnvelope } from "../lib/api";
import { subscribeToRealtimeTopic } from "../lib/realtime";

vi.mock("../lib/api", () => ({
  api: {
    dashboardBootstrap: vi.fn(),
    dashboardSummary: vi.fn(),
    platformAllocation: vi.fn(),
    spendingSummary: vi.fn(),
  },
}));

vi.mock("../lib/realtime", () => ({
  subscribeToRealtimeTopic: vi.fn(),
}));

const mockApi = vi.mocked(api, true);
const mockSubscribe = vi.mocked(subscribeToRealtimeTopic);

function makeBootstrap(currentTotal: number, liabilities = 0) {
  const stocksFunds = currentTotal - 10 + liabilities;
  return {
    as_of_month: "2026-05",
    base_currency: "SGD",
    snapshot_day: 1,
    current_net_worth_as_of: "2026-05-15T12:00:00+00:00",
    current_net_worth: {
      total: currentTotal,
      cash: 10,
      stocks_funds: stocksFunds,
      crypto: 0,
      liabilities,
    },
    current_net_worth_freshness: {
      stocks: {
        most_recent_at: "2026-05-15T12:00:00+00:00",
        most_recent_label: "AAPL",
        stalest_at: "2026-05-15T12:00:00+00:00",
        stalest_label: "AAPL",
      },
      crypto: {
        most_recent_at: null,
        most_recent_label: null,
        stalest_at: null,
        stalest_label: null,
      },
      cash: {
        most_recent_at: "2026-05-15T12:00:00+00:00",
        most_recent_label: "DBS",
        stalest_at: "2026-05-15T12:00:00+00:00",
        stalest_label: "DBS",
      },
    },
    net_worth_as_of: "2026-06-01T00:00:00+00:00",
    net_worth_snapshot_as_of: "2026-05-01T00:00:00+00:00",
    net_worth_boundary_at: "2026-06-01T00:00:00+00:00",
    net_worth_boundary_exact: false,
    net_worth_freshness_status: "synthetic",
    net_worth: {
      total: currentTotal,
      cash: 10,
      stocks_funds: stocksFunds,
      crypto: 0,
      liabilities,
    },
    current_stock_exposure_total: stocksFunds,
    current_crypto_exposure_total: 0,
    current_cash_percent: currentTotal ? (10 / currentTotal) * 100 : 0,
    stock_exposure_total: stocksFunds,
    crypto_exposure_total: 0,
    cash_percent: currentTotal ? (10 / currentTotal) * 100 : 0,
  };
}

function makeSummary(snapshotTotal: number, currentTotal = snapshotTotal, liabilities = 0) {
  return {
    as_of_month: "2026-05",
    base_currency: "SGD",
    snapshot_day: 1,
    current_net_worth_as_of: "2026-05-15T12:00:00+00:00",
    current_net_worth: {
      total: currentTotal,
      cash: 10,
      stocks_funds: currentTotal - 10 + liabilities,
      crypto: 0,
      liabilities,
    },
    current_net_worth_freshness: {
      stocks: {
        most_recent_at: "2026-05-15T12:00:00+00:00",
        most_recent_label: "AAPL",
        stalest_at: "2026-05-15T12:00:00+00:00",
        stalest_label: "AAPL",
      },
      crypto: {
        most_recent_at: null,
        most_recent_label: null,
        stalest_at: null,
        stalest_label: null,
      },
      cash: {
        most_recent_at: "2026-05-15T12:00:00+00:00",
        most_recent_label: "DBS",
        stalest_at: "2026-05-15T12:00:00+00:00",
        stalest_label: "DBS",
      },
    },
    net_worth_as_of: "2026-06-01T00:00:00+00:00",
    net_worth_snapshot_as_of: "2026-05-01T00:00:00+00:00",
    net_worth_boundary_at: "2026-06-01T00:00:00+00:00",
    net_worth_freshness_status: "synthetic",
    net_worth: {
      total: snapshotTotal,
      cash: 10,
      stocks_funds: snapshotTotal - 10 + liabilities,
      crypto: 0,
      liabilities,
    },
    geography: [],
    cash_flow: { income: 0, expenses: 0, net: 0, savings_rate: null },
    top_holdings: [],
    cash_balances: [],
    net_worth_change: null,
    net_worth_component_change: null,
    top_movers: null,
    cash_percent: snapshotTotal === 0 ? 0 : (10 / snapshotTotal) * 100,
  };
}

describe("WealthOverview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    vi.setSystemTime(new Date("2026-05-15T12:00:00Z"));
    mockApi.spendingSummary.mockResolvedValue({
      income_total: 0,
      expense_total: 0,
      net: 0,
      savings_rate: null,
    } as never);
    mockApi.platformAllocation.mockResolvedValue({
      as_of: "2026-06-01T00:00:00+00:00",
      total: 125,
      items: [
        { platform: "IBKR", platform_type: "BROKER", country: "US", value: 100, percent: 80 },
        { platform: "CRYPTO", platform_type: "WALLET_PROVIDER", country: null, value: 25, percent: 20 },
        { platform: "DBS_VICKERS", platform_type: "BROKER", country: "SG", value: 0, percent: 0 },
      ],
    } as never);
  });

  it("always fetches the current month and never renders a month picker", async () => {
    window.localStorage.setItem("capitalos.selectedMonth", "2026-04");
    mockSubscribe.mockImplementation(() => () => {});
    mockApi.dashboardBootstrap.mockResolvedValue(makeBootstrap(100) as never);
    mockApi.dashboardSummary.mockResolvedValue(makeSummary(100) as never);

    render(
      <MemoryRouter>
        <WealthOverview />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(mockApi.dashboardBootstrap).toHaveBeenCalledWith("2026-05", "SGD");
      expect(mockApi.dashboardSummary).toHaveBeenCalledWith("2026-05", "prev_month,prev_year", "SGD");
      expect(mockApi.platformAllocation).toHaveBeenCalledWith("2026-05", "SGD");
    });
    // No MonthControl anywhere on this page, and nothing writes a wealth-specific
    // month preference — the page has no concept of a selectable month.
    expect(screen.queryByLabelText("Month")).not.toBeInTheDocument();
    expect(window.localStorage.getItem("capitalos.selectedMonth.wealth")).toBeNull();
    expect(screen.getAllByText("DBS Vickers")).not.toHaveLength(0);
  });

  it("renders per-source freshness chips on the hero from bootstrap data", async () => {
    mockSubscribe.mockImplementation(() => () => {});
    mockApi.dashboardBootstrap.mockResolvedValue(makeBootstrap(100) as never);
    mockApi.dashboardSummary.mockResolvedValue(makeSummary(100) as never);

    render(
      <MemoryRouter>
        <WealthOverview />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Stocks")).toBeInTheDocument();
    expect(screen.getByText("Crypto")).toBeInTheDocument();
    expect(screen.getByText("Cash")).toBeInTheDocument();
    // stocks/cash most_recent_at is same-day as the faked system clock -> "today"
    expect(screen.getAllByText("today").length).toBeGreaterThan(0);
    // crypto freshness is null in the mock -> renders as missing, not a false date
    expect(screen.getByText("no data")).toBeInTheDocument();
  });

  it("paints the hero from bootstrap before the heavier summary call resolves", async () => {
    mockSubscribe.mockImplementation(() => () => {});
    mockApi.dashboardBootstrap.mockResolvedValue(makeBootstrap(100) as never);
    // Summary never resolves within this test — hero must not wait on it.
    mockApi.dashboardSummary.mockReturnValue(new Promise(() => {}) as never);

    render(
      <MemoryRouter>
        <WealthOverview />
      </MemoryRouter>,
    );

    await screen.findByText("Loading holdings…");
    // Scoped to the hero specifically — the platform-allocation legend can
    // coincidentally show the same figure for an individual platform.
    expect(document.querySelector(".coHeroValue")).toHaveTextContent("S$ 100");
  });

  it("refetches bootstrap and summary when a portfolio refresh event arrives", async () => {
    let handlers: Parameters<typeof subscribeToRealtimeTopic>[1] | undefined;
    mockSubscribe.mockImplementation((_topic, nextHandlers) => {
      handlers = nextHandlers;
      return () => {};
    });
    mockApi.dashboardBootstrap
      .mockResolvedValueOnce(makeBootstrap(125) as never)
      .mockResolvedValueOnce(makeBootstrap(225) as never);
    mockApi.dashboardSummary.mockResolvedValue(makeSummary(100, 125) as never);

    render(
      <MemoryRouter>
        <WealthOverview />
      </MemoryRouter>,
    );

    expect(await screen.findAllByText("S$ 125")).not.toHaveLength(0);

    await act(async () => {
      handlers?.onEvent?.({
        id: "event-1",
        topic: "portfolio-refresh",
        event_name: "market_data_refresh_completed",
        payload: { source: "market-data" },
      } as RealtimeEventEnvelope);
    });

    await waitFor(() => {
      expect(mockApi.dashboardBootstrap).toHaveBeenCalledTimes(2);
    }, { timeout: 2000 });
    expect(await screen.findByText("S$ 225")).toBeInTheDocument();
  });

  it("does not render upload reminders on the wealth overview", async () => {
    mockSubscribe.mockImplementation(() => () => {});
    mockApi.dashboardBootstrap.mockResolvedValue(makeBootstrap(100) as never);
    mockApi.dashboardSummary.mockResolvedValue(makeSummary(100) as never);

    render(
      <MemoryRouter>
        <WealthOverview />
      </MemoryRouter>,
    );

    // New allocation section renders platform allocation rows
    expect(await screen.findByText("Where the money sits")).toBeInTheDocument();
    expect(screen.getAllByText("IBKR")).not.toHaveLength(0);
    expect(screen.queryByText("Upload reminders")).not.toBeInTheDocument();
    expect(screen.queryByText("Statement coverage")).not.toBeInTheDocument();
  });

  it("renders credit card liability from bootstrap net worth", async () => {
    mockSubscribe.mockImplementation(() => () => {});
    mockApi.dashboardBootstrap.mockResolvedValue(makeBootstrap(739.44, 260.56) as never);
    mockApi.dashboardSummary.mockResolvedValue(makeSummary(739.44, 739.44, 260.56) as never);

    render(
      <MemoryRouter>
        <WealthOverview />
      </MemoryRouter>,
    );

    // Signals section shows LIABILITIES with the value
    expect(await screen.findByText("LIABILITIES")).toBeInTheDocument();
    expect(screen.getByText("Outstanding obligations vs current net worth.")).toBeInTheDocument();
    expect(screen.getByText("S$ 261")).toBeInTheDocument();
  });
});
