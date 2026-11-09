import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import MarketData from "../routes/MarketData";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";

vi.mock("../lib/api", () => ({
  api: {
    marketDataStatus: vi.fn(),
    marketDataRuns: vi.fn(),
    marketDataRefreshNow: vi.fn(),
    marketDataUnpriced: vi.fn(),
    marketDataTickerTest: vi.fn(),
    marketDataSetTicker: vi.fn(),
  },
}));

const authState: { user: { id: number; username: string; is_admin: boolean } } = {
  user: { id: 1, username: "demo", is_admin: true },
};
vi.mock("../context/useAuth", () => ({ useAuth: () => authState }));

const mockApi = vi.mocked(api, true);

beforeEach(() => {
  authState.user.is_admin = true;
  mockApi.marketDataUnpriced.mockResolvedValue({ items: [], can_fix: true });
});

describe("MarketData", () => {
  it("renders latest market data tables", async () => {
    mockApi.marketDataStatus.mockResolvedValueOnce({
      status: [
        {
          provider: "eodhd",
          exchange_code: "US",
          status: "success",
          diagnostics_summary: {
            active_symbols: 2,
            refreshed: 1,
            fresh: 1,
            stale: 1,
            failed: 1,
            deferred: 0,
            missing: 0,
          },
          symbols: [
            {
              asset_id: 1,
              symbol: "ADBE",
              mapped_symbol: "ADBE.US",
              latest_trade_date: "2026-03-04",
              freshness_status: "fresh",
              refresh_status: "refreshed",
              provider: "eodhd",
              source: "close",
              failure_reason: null,
            },
            {
              asset_id: 2,
              symbol: "REGN",
              mapped_symbol: "REGN.US",
              latest_trade_date: "2026-02-28",
              freshness_status: "stale",
              refresh_status: "failed",
              provider: "eodhd",
              source: "close",
              failure_reason: "rate limited",
              reason_code: "RATE_LIMITED",
            },
          ],
        },
      ],
    });
    mockApi.marketDataRuns.mockResolvedValueOnce({
      runs: [
        {
          id: 1,
          provider: "eodhd",
          exchange_code: "US",
          trade_date: "2026-03-04",
          status: "success",
          requested_symbols: 10,
          received_rows: 10,
          upserted_rows: 10,
          missing_symbols: 0,
          started_at: "2026-03-04T12:00:00Z",
        },
      ],
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <MarketData />
        </MemoryRouter>
      </ThemeProvider>
    );

    expect(await screen.findByText("Latest refresh status")).toBeInTheDocument();

    expect(screen.getByText("Recent runs")).toBeInTheDocument();
    expect(screen.getAllByText("US").length).toBeGreaterThan(0);
    expect(screen.getByText("ADBE")).toBeInTheDocument();
    expect(screen.getByText("REGN")).toBeInTheDocument();
    expect(screen.getByText("Rate limited")).toBeInTheDocument();

    expect(screen.getByText("1 fresh")).toBeInTheDocument();
    expect(screen.getByText("1 stale")).toBeInTheDocument();
    expect(screen.getByText("1 failed")).toBeInTheDocument();
    expect(screen.getByText("0 deferred")).toBeInTheDocument();
  });

  it("collapses the exchange row on click and shows a fallback for missing reasons", async () => {
    mockApi.marketDataStatus.mockResolvedValueOnce({
      status: [
        {
          provider: "IEX Cloud",
          exchange_code: "NASDAQ",
          status: "Idle",
          diagnostics_summary: {
            active_symbols: 1,
            refreshed: 0,
            fresh: 0,
            stale: 1,
            failed: 0,
            deferred: 0,
            missing: 0,
          },
          symbols: [
            {
              asset_id: 9,
              symbol: "AAPL",
              mapped_symbol: "AAPL.US",
              latest_trade_date: "2026-03-01",
              freshness_status: "stale",
              refresh_status: "failed",
              provider: "IEX Cloud",
              source: "close",
              failure_reason: null,
            },
          ],
        },
      ],
    });
    mockApi.marketDataRuns.mockResolvedValueOnce({ runs: [] });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <MarketData />
        </MemoryRouter>
      </ThemeProvider>
    );

    expect(await screen.findByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("Reason unavailable")).toBeInTheDocument();

    await userEvent.click(screen.getByText("NASDAQ"));
    expect(screen.queryByText("AAPL")).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("NASDAQ"));
    expect(await screen.findByText("AAPL")).toBeInTheDocument();
  });

  it("leaves out exchanges with nothing held, and gives fresh rows no reason line (#315)", async () => {
    const summary = { active_symbols: 1, refreshed: 1, fresh: 1, stale: 0, failed: 0, deferred: 0, missing: 0 };
    mockApi.marketDataStatus.mockResolvedValueOnce({
      status: [
        { provider: "Yahoo", exchange_code: "SGX", status: "Idle", diagnostics_summary: summary, symbols: [
          { asset_id: 1, symbol: "D05", mapped_symbol: "D05.SI", latest_trade_date: "2026-11-06", freshness_status: "fresh",
            refresh_status: "ok", provider: "Yahoo", source: "close", failure_reason: null },
        ] },
        { provider: "Yahoo", exchange_code: "TSE", status: "Idle", diagnostics_summary: { ...summary, active_symbols: 0, fresh: 0 }, symbols: [] },
      ],
    });
    mockApi.marketDataRuns.mockResolvedValueOnce({ runs: [] });
    render(
      <ThemeProvider>
        <MemoryRouter>
          <MarketData />
        </MemoryRouter>
      </ThemeProvider>
    );
    expect(await screen.findByText("SGX")).toBeInTheDocument();
    expect(screen.queryByText("TSE")).not.toBeInTheDocument();
    expect(await screen.findByText("D05")).toBeInTheDocument(); // expanded by default
    expect(screen.queryByText("Reason unavailable")).not.toBeInTheDocument();
  });

  describe("Needs a fix (#320)", () => {
    const summary = { active_symbols: 1, refreshed: 1, fresh: 1, stale: 0, failed: 0, deferred: 0, missing: 0 };
    const nseStatus = {
      status: [
        { provider: "yfinance", exchange_code: "NSE", status: "partial", diagnostics_summary: summary, symbols: [
          { asset_id: 1, symbol: "TCS", mapped_symbol: "TCS.NS", latest_trade_date: "2026-11-06", freshness_status: "fresh",
            refresh_status: "ok", provider: "yfinance", source: "close", failure_reason: null },
        ] },
      ],
    };
    const unpricedItem = {
      instrument_id: 9, asset_id: 83, symbol: "SYNTHN", name: "Synthetic N", currency: "INR", exchange_code: "NSE",
      platform: "SHAREKHAN", reason: "no_quote", suggested_yahoo_symbols: ["SYNTHN.NS", "SYNTHN.BO"],
    };

    function renderPage(path = "/market-data") {
      return render(
        <ThemeProvider>
          <MemoryRouter initialEntries={[path]}>
            <MarketData />
          </MemoryRouter>
        </ThemeProvider>,
      );
    }

    it("lets an admin test a ticker, then save it", async () => {
      mockApi.marketDataStatus.mockResolvedValue(nseStatus);
      mockApi.marketDataRuns.mockResolvedValue({ runs: [] });
      mockApi.marketDataUnpriced.mockResolvedValueOnce({ items: [unpricedItem], can_fix: true });
      mockApi.marketDataTickerTest.mockResolvedValueOnce({
        found: true, yahoo_symbol: "SYNTHN.BO", close: 1908.35, trade_date: "2026-11-06", currency: "INR",
      });
      mockApi.marketDataSetTicker.mockResolvedValueOnce({
        found: true, yahoo_symbol: "SYNTHN.BO", close: 1908.35, trade_date: "2026-11-06", currency: "INR",
        asset_id: 83, exchange_code: "NSE", action: "set",
      });
      renderPage("/market-data#needs-fix");

      const row = await screen.findByTestId("needs-fix-SYNTHN");
      expect(within(row).getByText(/Yahoo has no quote for its ticker/)).toBeInTheDocument();
      const input = within(row).getByLabelText("Yahoo ticker for SYNTHN") as HTMLInputElement;
      expect(input.value).toBe("SYNTHN.BO"); // the BSE suggestion: the NSE one already failed
      const save = within(row).getByRole("button", { name: "Save ticker" });
      expect(save).toBeDisabled(); // test first

      await userEvent.click(within(row).getByRole("button", { name: "Test" }));
      expect(mockApi.marketDataTickerTest).toHaveBeenCalledWith("SYNTHN.BO", "NSE");
      expect(await within(row).findByRole("status")).toHaveTextContent("SYNTHN.BO");
      expect(save).toBeEnabled();

      await userEvent.click(save);
      expect(mockApi.marketDataSetTicker).toHaveBeenCalledWith(83, "NSE", "SYNTHN.BO");
      await waitFor(() => expect(screen.getByText(/SYNTHN now uses SYNTHN.BO/)).toBeInTheDocument());
    });

    it("a failed test keeps Save disabled", async () => {
      mockApi.marketDataStatus.mockResolvedValue(nseStatus);
      mockApi.marketDataRuns.mockResolvedValue({ runs: [] });
      mockApi.marketDataUnpriced.mockResolvedValueOnce({ items: [unpricedItem], can_fix: true });
      mockApi.marketDataTickerTest.mockResolvedValueOnce({ found: false, yahoo_symbol: "SYNTHN.NS", error: "Yahoo has no quote for SYNTHN.NS" });
      renderPage();
      const row = await screen.findByTestId("needs-fix-SYNTHN");
      await userEvent.click(within(row).getByRole("button", { name: "SYNTHN.NS" }));
      await userEvent.click(within(row).getByRole("button", { name: "Test" }));
      expect(await within(row).findByRole("status")).toHaveTextContent("Yahoo has no quote for SYNTHN.NS");
      expect(within(row).getByRole("button", { name: "Save ticker" })).toBeDisabled();
    });

    it("refreshes one exchange, or all", async () => {
      mockApi.marketDataStatus.mockResolvedValue(nseStatus);
      mockApi.marketDataRuns.mockResolvedValue({ runs: [] });
      mockApi.marketDataRefreshNow.mockResolvedValue({ status: "ok", exchanges: [] });
      renderPage();
      await userEvent.click(await screen.findByRole("button", { name: "Refresh NSE" }));
      expect(mockApi.marketDataRefreshNow).toHaveBeenCalledWith(undefined, "NSE");
      await userEvent.click(screen.getByRole("button", { name: "Refresh all" }));
      expect(mockApi.marketDataRefreshNow).toHaveBeenLastCalledWith();
      expect(await screen.findByText("Every holding has a price.")).toBeInTheDocument();
    });

    it("shows a non-admin the list but no actions", async () => {
      authState.user.is_admin = false;
      mockApi.marketDataStatus.mockResolvedValue(nseStatus);
      mockApi.marketDataRuns.mockResolvedValue({ runs: [] });
      mockApi.marketDataUnpriced.mockResolvedValueOnce({ items: [unpricedItem], can_fix: false });
      renderPage();
      const row = await screen.findByTestId("needs-fix-SYNTHN");
      expect(within(row).getByText("An admin can set its ticker.")).toBeInTheDocument();
      expect(within(row).queryByRole("button", { name: "Test" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Refresh all" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Refresh NSE" })).not.toBeInTheDocument();
    });
  });
});

