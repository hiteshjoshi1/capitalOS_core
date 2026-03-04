import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import MarketData from "../routes/MarketData";
import { api } from "../lib/api";

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
          id: 1,
          provider: "eodhd",
          exchange_code: "US",
          trade_date: "2026-03-04",
          status: "success",
          requested_symbols: 10,
          received_rows: 10,
          upserted_rows: 10,
          missing_symbols: 0,
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
      <MemoryRouter>
        <MarketData />
      </MemoryRouter>
    );

    expect(await screen.findByText("Latest by Exchange")).toBeInTheDocument();
    expect(screen.getByText("Recent Runs")).toBeInTheDocument();
    expect(screen.getAllByText("US").length).toBeGreaterThan(0);
  });
});
