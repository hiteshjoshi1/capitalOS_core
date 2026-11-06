import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { controlledCalls } from "./raceHelpers";
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
    netWorthSinceUpdate: vi.fn(),
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

/** A past month's bootstrap (#223): `net_worth` is that month-end, `current_*` stay live. */
function makePastBootstrap(monthEndTotal: number, liveTotal: number) {
  const live = makeBootstrap(liveTotal);
  return {
    ...live,
    as_of_month: "2026-04",
    is_live: false,
    net_worth_as_of: "2026-05-01T00:00:00+00:00",
    net_worth_snapshot_as_of: "2026-04-28T00:00:00+00:00",
    net_worth_boundary_at: "2026-05-01T00:00:00+00:00",
    net_worth: { total: monthEndTotal, cash: 10, stocks_funds: monthEndTotal - 10, crypto: 0, liabilities: 0 },
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
    mockApi.netWorthSinceUpdate.mockResolvedValue({
      base_currency: "SGD",
      current_as_of: "2026-05-15T12:00:00+00:00",
      compare_as_of: "2026-05-14T12:00:00+00:00",
      net_worth_change: {
        abs: 0,
        pct: null,
        current_as_of: "2026-05-15T12:00:00+00:00",
        compare_as_of: "2026-05-14T12:00:00+00:00",
        compare_month: "2026-05-14T12:00:00+00:00",
      },
      component_change: {},
      top_movers: null,
    } as never);
  });

  // #223: Overview follows the shared selected month (the same one Stocks, Cash, Risk... use).
  it("fetches every panel for the shared selected month and shows the month pill", async () => {
    window.localStorage.setItem("capitalos.selectedMonth", "2026-04");
    mockSubscribe.mockImplementation(() => () => {});
    mockApi.dashboardBootstrap.mockImplementation(((month: string) =>
      Promise.resolve(month === "2026-04" ? makePastBootstrap(80, 100) : makeBootstrap(100))) as never);
    mockApi.dashboardSummary.mockImplementation(((month: string) =>
      Promise.resolve(month === "2026-04" ? { ...makeSummary(80, 100), as_of_month: "2026-04", is_live: false } : makeSummary(100))) as never);

    render(
      <MemoryRouter>
        <WealthOverview />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(mockApi.dashboardBootstrap).toHaveBeenCalledWith("2026-04", "SGD");
      expect(mockApi.dashboardSummary).toHaveBeenCalledWith("2026-04", "prev_month,prev_year", "SGD");
      expect(mockApi.platformAllocation).toHaveBeenCalledWith("2026-04", "SGD");
      expect(mockApi.spendingSummary).toHaveBeenCalledWith("2026-04", "SGD");
    });
    expect(screen.getByLabelText("Month")).toHaveValue("2026-04");
    // The #127 callout beside the pill.
    expect(screen.getByText("Past month")).toBeInTheDocument();
    // Never requested for the current month while a past one is selected.
    expect(mockApi.dashboardBootstrap).not.toHaveBeenCalledWith("2026-05", "SGD");
    // "Since last update" is live only.
    expect(mockApi.netWorthSinceUpdate).not.toHaveBeenCalled();
  });

  it("shows a past month as its month-end snapshot, with that month's comparisons", async () => {
    window.localStorage.setItem("capitalos.selectedMonth", "2026-04");
    mockSubscribe.mockImplementation(() => () => {});
    mockApi.dashboardBootstrap.mockResolvedValue(makePastBootstrap(80, 100) as never);
    const change = (abs: number, compareMonth: string) => ({
      abs,
      pct: null,
      current_as_of: "2026-05-01T00:00:00+00:00",
      compare_as_of: null,
      compare_month: compareMonth,
    });
    mockApi.dashboardSummary.mockResolvedValue({
      ...makeSummary(80, 100),
      as_of_month: "2026-04",
      is_live: false,
      // That month-end vs the month-end before it and a year before (D-24).
      net_worth_change: { vs_prev_month: change(11, "2026-03"), vs_prev_year: change(22, "2025-04") },
      // The live comparisons belong to the live headline, not to April.
      current_net_worth_change: { vs_prev_month: change(777, "2026-04"), vs_prev_year: change(999, "2025-04") },
    } as never);

    render(
      <MemoryRouter>
        <WealthOverview />
      </MemoryRouter>,
    );

    expect(await screen.findByText("NET WORTH · APR 2026 MONTH-END")).toBeInTheDocument();
    expect(document.querySelector(".coHeroValue")).toHaveTextContent("S$ 80");
    expect(screen.getByRole("note")).toHaveTextContent("Viewing Apr 2026 (month-end snapshot)");
    expect(screen.queryByText("CURRENT NET WORTH")).not.toBeInTheDocument();
    // Freshness chips and "since last update" are about live data.
    expect(screen.queryByLabelText("Data freshness by asset class")).not.toBeInTheDocument();
    expect(screen.queryByText(/SINCE LAST UPDATE/)).not.toBeInTheDocument();
    // Comparisons name their baseline.
    expect((await screen.findByText("VS MAR 2026 MONTH-END")).parentElement).toHaveTextContent("+S$ 11");
    expect(screen.getByText("VS APR 2025 MONTH-END").parentElement).toHaveTextContent("+S$ 22");
    expect(screen.queryByText(/S\$ 777/)).not.toBeInTheDocument();
    expect(screen.queryByText(/S\$ 999/)).not.toBeInTheDocument();
    // Today's movers are live only.
    expect(screen.getByRole("button", { name: "Movers" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Today" })).not.toBeInTheDocument();
  });

  it("changing the month refetches with it and writes the shared month; Back to live returns", async () => {
    mockSubscribe.mockImplementation(() => () => {});
    mockApi.dashboardBootstrap.mockImplementation(((month: string) =>
      Promise.resolve(month === "2026-04" ? makePastBootstrap(80, 100) : makeBootstrap(100))) as never);
    mockApi.dashboardSummary.mockImplementation(((month: string) =>
      Promise.resolve(month === "2026-04" ? { ...makeSummary(80, 100), as_of_month: "2026-04", is_live: false } : makeSummary(100))) as never);

    render(
      <MemoryRouter>
        <WealthOverview />
      </MemoryRouter>,
    );

    expect(await screen.findByText("CURRENT NET WORTH")).toBeInTheDocument();
    expect(mockApi.dashboardBootstrap).toHaveBeenCalledWith("2026-05", "SGD");

    fireEvent.change(screen.getByLabelText("Month"), { target: { value: "2026-04" } });
    await waitFor(() => {
      expect(mockApi.dashboardBootstrap).toHaveBeenCalledWith("2026-04", "SGD");
      expect(mockApi.platformAllocation).toHaveBeenCalledWith("2026-04", "SGD");
    });
    // The same key every other page reads, so Stocks/Cash/Risk follow.
    expect(window.localStorage.getItem("capitalos.selectedMonth")).toBe("2026-04");
    expect(await screen.findByText("NET WORTH · APR 2026 MONTH-END")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Back to live" }));
    expect(await screen.findByText("CURRENT NET WORTH")).toBeInTheDocument();
    expect(window.localStorage.getItem("capitalos.selectedMonth")).toBe("2026-05");
    expect(screen.getByLabelText("Month")).toHaveValue("2026-05");
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

  it("renders a since-last-update delta strip on the hero card", async () => {
    mockSubscribe.mockImplementation(() => () => {});
    mockApi.dashboardBootstrap.mockResolvedValue(makeBootstrap(100) as never);
    mockApi.dashboardSummary.mockResolvedValue(makeSummary(100) as never);
    mockApi.netWorthSinceUpdate.mockResolvedValue({
      base_currency: "SGD",
      current_as_of: "2026-05-15T12:00:00+00:00",
      compare_as_of: "2026-05-14T12:00:00+00:00",
      net_worth_change: {
        abs: 5,
        pct: 0.05,
        current_as_of: "2026-05-15T12:00:00+00:00",
        compare_as_of: "2026-05-14T12:00:00+00:00",
        compare_month: "2026-05-14T12:00:00+00:00",
      },
      component_change: {},
      top_movers: null,
    } as never);

    render(
      <MemoryRouter>
        <WealthOverview />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/SINCE LAST UPDATE/)).toBeInTheDocument();
    expect(screen.getByText("+S$ 5 (+5.0%)")).toBeInTheDocument();
  });

  it("shows the live comparisons next to the live headline (#133)", async () => {
    mockSubscribe.mockImplementation(() => () => {});
    mockApi.dashboardBootstrap.mockResolvedValue(makeBootstrap(100) as never);
    const change = (abs: number, compareMonth: string) => ({
      abs,
      pct: null,
      current_as_of: "2026-06-01T00:00:00+00:00",
      compare_as_of: null,
      compare_month: compareMonth,
    });
    mockApi.dashboardSummary.mockResolvedValue({
      ...makeSummary(100),
      // Snapshot-to-snapshot: what the requested month's snapshot changed by.
      net_worth_change: { vs_prev_month: change(111, "2026-04"), vs_prev_year: change(222, "2025-05") },
      // Live headline vs the latest completed month-end and that month-end a year earlier.
      current_net_worth_change: { vs_prev_month: change(7, "2026-05"), vs_prev_year: change(9, "2025-05") },
    } as never);

    render(
      <MemoryRouter>
        <WealthOverview />
      </MemoryRouter>,
    );

    const monthLabel = await screen.findByText("VS LAST MONTH");
    expect(monthLabel.parentElement).toHaveTextContent("+S$ 7");
    expect(screen.getByText("VS LAST YEAR").parentElement).toHaveTextContent("+S$ 9");
    expect(screen.queryByText(/S\$ 111/)).not.toBeInTheDocument();
    expect(screen.queryByText(/S\$ 222/)).not.toBeInTheDocument();
  });

  it("shows today's movers when the Today tab is selected", async () => {
    mockSubscribe.mockImplementation(() => () => {});
    mockApi.dashboardBootstrap.mockResolvedValue(makeBootstrap(100) as never);
    mockApi.dashboardSummary.mockResolvedValue(makeSummary(100) as never);
    mockApi.netWorthSinceUpdate.mockResolvedValue({
      base_currency: "SGD",
      current_as_of: "2026-05-15T12:00:00+00:00",
      compare_as_of: "2026-05-14T12:00:00+00:00",
      net_worth_change: {
        abs: 5,
        pct: 0.05,
        current_as_of: "2026-05-15T12:00:00+00:00",
        compare_as_of: "2026-05-14T12:00:00+00:00",
        compare_month: "2026-05-14T12:00:00+00:00",
      },
      component_change: {},
      top_movers: {
        compare_month: "2026-05-14T12:00:00+00:00",
        gainers: [
          {
            asset_id: 1,
            symbol: "AAPL",
            asset_class: "STOCK",
            current_value: 110,
            previous_value: 100,
            delta_abs: 10,
            delta_pct: 0.1,
            compare_month: "2026-05-14T12:00:00+00:00",
          },
        ],
        detractors: [],
      },
    } as never);

    render(
      <MemoryRouter>
        <WealthOverview />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Largest positions")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Today" }));

    expect(await screen.findByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("+S$ 10")).toBeInTheDocument();
  });
});

// #148: currency switches with out-of-order replies.
describe("WealthOverview currency races", () => {
  it("keeps the previous currency on screen, then shows only the latest currency", async () => {
    vi.clearAllMocks();
    vi.setSystemTime(new Date("2026-05-15T12:00:00Z"));
    mockSubscribe.mockImplementation(() => () => {});
    mockApi.dashboardSummary.mockResolvedValue(makeSummary(100) as never);
    mockApi.spendingSummary.mockResolvedValue({ income_total: 0, expense_total: 0, net: 0, savings_rate: null } as never);
    mockApi.platformAllocation.mockResolvedValue({ as_of: null, total: 0, items: [] } as never);
    mockApi.netWorthSinceUpdate.mockResolvedValue({ base_currency: "SGD", net_worth_change: null, top_movers: null } as never);
    const boot = controlledCalls<ReturnType<typeof makeBootstrap>>();
    mockApi.dashboardBootstrap.mockImplementation(boot.impl as never);

    render(
      <MemoryRouter>
        <WealthOverview />
      </MemoryRouter>,
    );
    await act(async () => boot.find((a) => a[1] === "SGD").resolve(makeBootstrap(100)));
    expect(await screen.findByText("S$ 100")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Base currency"), { target: { value: "USD" } });
    // Still the SGD figure, still labelled S$, marked busy.
    expect(screen.getByText("S$ 100").closest("[aria-busy]")).toHaveAttribute("aria-busy", "true");
    fireEvent.change(screen.getByLabelText("Base currency"), { target: { value: "HKD" } });

    const usd = boot.find((a) => a[1] === "USD");
    await act(async () => boot.find((a) => a[1] === "HKD").resolve({ ...makeBootstrap(500), base_currency: "HKD" }));
    expect(await screen.findByText("HKD 500")).toBeInTheDocument();
    await act(async () => usd.resolve({ ...makeBootstrap(300), base_currency: "USD" }));
    expect(screen.queryByText("USD 300")).not.toBeInTheDocument();
    expect(screen.getByText("HKD 500")).toBeInTheDocument();
    await waitFor(() => expect(usd.signal?.aborted).toBe(true));
  });
});

// #151: a failed panel says so (with a retry) instead of showing "—" like a zero.
describe("WealthOverview panel errors", () => {
  it("shows a couldn't-load state per panel and recovers on retry", async () => {
    vi.resetAllMocks();
    vi.setSystemTime(new Date("2026-05-15T12:00:00Z"));
    mockSubscribe.mockImplementation(() => () => {});
    mockApi.dashboardBootstrap.mockResolvedValue(makeBootstrap(100) as never);
    mockApi.dashboardSummary
      .mockRejectedValueOnce(new Error("summary down"))
      .mockResolvedValue(makeSummary(100) as never);
    mockApi.spendingSummary.mockRejectedValue(new Error("spending down"));
    mockApi.platformAllocation.mockResolvedValue({ as_of: null, total: 0, items: [] } as never);
    mockApi.netWorthSinceUpdate.mockResolvedValue({ base_currency: "SGD", net_worth_change: null, top_movers: null } as never);

    render(
      <MemoryRouter>
        <WealthOverview />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Couldn't load positions")).toBeInTheDocument();
    expect(screen.getByText("Couldn't load cash flow")).toBeInTheDocument();
    const alerts = screen.getAllByRole("alert");
    expect(alerts.length).toBeGreaterThanOrEqual(2);
    // The cash-flow card no longer prints "—" as if it were a value.
    expect(screen.getByText("spending down")).toBeInTheDocument();

    const positions = screen.getByText("Couldn't load positions").closest("[role=alert]") as HTMLElement;
    fireEvent.click(within(positions).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.queryByText("Couldn't load positions")).not.toBeInTheDocument());
  });

  it("the allocation donut is an image with its data described", async () => {
    vi.clearAllMocks();
    vi.setSystemTime(new Date("2026-05-15T12:00:00Z"));
    mockSubscribe.mockImplementation(() => () => {});
    mockApi.dashboardBootstrap.mockResolvedValue(makeBootstrap(100) as never);
    mockApi.dashboardSummary.mockResolvedValue(makeSummary(100) as never);
    mockApi.spendingSummary.mockResolvedValue({ income_total: 0, expense_total: 0, net: 0, savings_rate: null } as never);
    mockApi.platformAllocation.mockResolvedValue({
      as_of: null,
      total: 125,
      items: [
        { platform: "IBKR", platform_type: "BROKER", country: "US", value: 100, percent: 80 },
        { platform: "DBS_VICKERS", platform_type: "BROKER", country: "SG", value: 25, percent: 20 },
      ],
    } as never);
    mockApi.netWorthSinceUpdate.mockResolvedValue({ base_currency: "SGD", net_worth_change: null, top_movers: null } as never);
    render(
      <MemoryRouter>
        <WealthOverview />
      </MemoryRouter>,
    );
    const donut = await screen.findByRole("img", { name: "Allocation donut chart" });
    await waitFor(() => expect(donut).toHaveAccessibleDescription(/IBKR 80.0%, DBS Vickers 20.0%/));
  });

  it("says 'no data for <month>' when a comparison has no baseline (#224)", async () => {
    mockSubscribe.mockImplementation(() => () => {});
    mockApi.dashboardBootstrap.mockResolvedValue(makeBootstrap(100) as never);
    const change = (abs: number, pct: number | null, compareMonth: string, baselineMissing: boolean) => ({
      abs,
      pct,
      current_as_of: "2026-05-15T00:00:00+00:00",
      compare_as_of: baselineMissing ? null : "2026-05-01T00:00:00+00:00",
      compare_month: compareMonth,
      compare_value: baselineMissing ? 0 : 100 - abs,
      baseline_missing: baselineMissing,
    });
    mockApi.dashboardSummary.mockResolvedValue({
      ...makeSummary(100),
      current_net_worth_change: {
        vs_prev_month: change(-4, -0.04, "2026-04", false),
        // A year back has no data at all: the whole figure, not a change.
        vs_prev_year: change(100, null, "2025-04", true),
      },
    } as never);

    render(
      <MemoryRouter>
        <WealthOverview />
      </MemoryRouter>,
    );

    const yearRow = (await screen.findByText("VS LAST YEAR")).parentElement as HTMLElement;
    expect(yearRow).toHaveTextContent("no comparison: no data for Apr 2025");
    expect(yearRow).not.toHaveTextContent("S$ 100");
    // Last month is real: ▼, the down colour, amount and % together.
    const monthDelta = (screen.getByText("VS LAST MONTH").parentElement as HTMLElement).querySelector(".delta");
    expect(monthDelta).toHaveClass("delta--down");
    expect(monthDelta).toHaveTextContent("▼-S$ 4 (-4.0%)");
    // The hero chip is the same <Delta>, in the same colour.
    const chip = document.querySelector(".coHeroValueRow .deltaChip");
    expect(chip).toHaveClass("delta--down");
    expect(chip).toHaveTextContent("▼-4.0%");
  });
});
