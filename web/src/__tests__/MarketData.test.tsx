import { render, screen } from "@testing-library/react";
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

    expect(await screen.findByText("Latest by Exchange")).toBeInTheDocument();

    expect(screen.getByText("Recent Runs")).toBeInTheDocument();
    expect(screen.getAllByText("US").length).toBeGreaterThan(0);
    expect(screen.getByText("ADBE")).toBeInTheDocument();
    expect(screen.getByText("REGN")).toBeInTheDocument();
    expect(screen.getByText("rate limited")).toBeInTheDocument();
  });
});
