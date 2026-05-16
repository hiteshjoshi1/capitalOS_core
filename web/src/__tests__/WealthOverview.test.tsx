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
    spendingSummary: vi.fn(),
    alertNotifications: vi.fn(),
  },
}));

vi.mock("../lib/realtime", () => ({
  subscribeToRealtimeTopic: vi.fn(),
}));

const mockApi = vi.mocked(api, true);
const mockSubscribe = vi.mocked(subscribeToRealtimeTopic);

function makeSummary(snapshotTotal: number, currentTotal = snapshotTotal) {
  return {
    as_of_month: "2026-05",
    base_currency: "SGD",
    snapshot_day: 1,
    current_net_worth_as_of: "2026-05-15T12:00:00+00:00",
    current_net_worth: {
      total: currentTotal,
      cash: 10,
      stocks_funds: currentTotal - 10,
      crypto: 0,
      liabilities: 0,
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
      stocks_funds: snapshotTotal - 10,
      crypto: 0,
      liabilities: 0,
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
    mockApi.alertNotifications.mockResolvedValue({ upload_reminders: [] } as never);
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
    });
    expect(window.localStorage.getItem("capitalos.selectedMonth.wealth")).toBe("2026-05");
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

    expect(await screen.findByText("S$ 125")).toBeInTheDocument();
    expect(screen.getByText("Snapshot net worth for 2026-05")).toBeInTheDocument();

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
});