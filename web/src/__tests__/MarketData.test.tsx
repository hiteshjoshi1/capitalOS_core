import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import MarketData from "../routes/MarketData";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";

vi.mock("../lib/api", () => ({
  api: {
    marketDataStatus: vi.fn(),
    marketDataRuns: vi.fn(),
    marketDataRefreshNow: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

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
    expect(screen.getByText("rate limited")).toBeInTheDocument();

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
});
