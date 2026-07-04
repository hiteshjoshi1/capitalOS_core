import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import WealthOverview from "../routes/WealthOverview";
import { api } from "../lib/api";
import type { RealtimeEventEnvelope } from "../lib/api";
import { subscribeToRealtimeTopic } from "../lib/realtime";

vi.mock("../lib/api", () => ({
  api: {
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
      positions_as_of: "2026-05-15T12:00:00+00:00",
      market_data_as_of: "2026-05-15",
      crypto_as_of: null,
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

  it("uses the wealth-specific current month instead of a stale global month", async () => {
    window.localStorage.setItem("capitalos.selectedMonth", "2026-04");
    mockSubscribe.mockImplementation(() => () => {});
    mockApi.dashboardSummary.mockResolvedValue(makeSummary(100) as never);

    render(
      <MemoryRouter>
        <WealthOverview />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(mockApi.dashboardSummary).toHaveBeenCalledWith("2026-05", "prev_month,prev_year", "SGD");
      expect(mockApi.platformAllocation).toHaveBeenCalledWith("2026-05", "SGD");
    });
    expect(window.localStorage.getItem("capitalos.selectedMonth.wealth")).toBe("2026-05");
    expect(screen.getAllByText("DBS Vickers")).not.toHaveLength(0);
  });

  it("refetches summary when a portfolio refresh event arrives", async () => {
    let handlers: Parameters<typeof subscribeToRealtimeTopic>[1] | undefined;
    mockSubscribe.mockImplementation((_topic, nextHandlers) => {
      handlers = nextHandlers;
      return () => {};
    });
    mockApi.dashboardSummary
      .mockResolvedValueOnce(makeSummary(100, 125) as never)
      .mockResolvedValueOnce(makeSummary(150, 225) as never);

    render(
      <MemoryRouter>
        <WealthOverview />
      </MemoryRouter>,
    );

    expect(await screen.findAllByText("S$ 125")).not.toHaveLength(0);
    expect(screen.getByText("Snapshot context for 2026-05")).toBeInTheDocument();
    expect(screen.getByText("Latest-known snapshot")).toBeInTheDocument();
    expect(screen.getByText("Snapshot period 2026-05 · Boundary 2026-06-01 · Source holdings 2026-05-01")).toBeInTheDocument();
    expect(screen.getByText("Snapshot day 1. Computed from the latest known component values at or before the boundary.")).toBeInTheDocument();

    await act(async () => {
      handlers?.onEvent?.({
        id: "event-1",
        topic: "portfolio-refresh",
        event_name: "market_data_refresh_completed",
        payload: { source: "market-data" },
      } as RealtimeEventEnvelope);
    });

    await waitFor(() => {
      expect(mockApi.dashboardSummary).toHaveBeenCalledTimes(2);
    }, { timeout: 2000 });
    expect(await screen.findByText("S$ 225")).toBeInTheDocument();
  });

  it("does not render upload reminders on the wealth overview", async () => {
    mockSubscribe.mockImplementation(() => () => {});
    mockApi.dashboardSummary.mockResolvedValue(makeSummary(100) as never);

    render(
      <MemoryRouter>
        <WealthOverview />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Portfolio Composition")).toBeInTheDocument();
    expect(screen.getByText("Platform Allocation")).toBeInTheDocument();
    expect(screen.getAllByText("IBKR")).not.toHaveLength(0);
    expect(screen.queryByText("Upload reminders")).not.toBeInTheDocument();
    expect(screen.queryByText("Statement coverage")).not.toBeInTheDocument();
  });

  it("renders DBS credit card liability from net worth summary", async () => {
    mockSubscribe.mockImplementation(() => () => {});
    mockApi.dashboardSummary.mockResolvedValue(makeSummary(739.44, 739.44, 260.56) as never);

    render(
      <MemoryRouter>
        <WealthOverview />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Liabilities")).toBeInTheDocument();
    expect(screen.getByText("Outstanding obligations remain visible inside the Liabilities section overview.")).toBeInTheDocument();
    expect(screen.getByText("S$ 261")).toBeInTheDocument();
  });
});
