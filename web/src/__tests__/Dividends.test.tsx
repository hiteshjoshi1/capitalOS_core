import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import Dividends from "../routes/Dividends";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";

vi.mock("../lib/api", () => ({
  api: {
    dividendsSummary: vi.fn(),
    dividendsByCompany: vi.fn(),
    expectedDividendsOverview: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

describe("Dividends", () => {
  it("renders period totals and company table", async () => {
    const monthSummary = {
      from_month: "2025-03",
      to_month: "2026-02",
      period: "month" as const,
      base_currency: "SGD",
      assumed_tax_rate: 0.1,
      country_tax_rates: { US: 0.15 },
      buckets: [{ bucket: "2026-02", gross: 120, withholding: 15, net_received: 105, estimated_tax: 12, payout_minus_tax: 93 }],
      totals: { gross: 120, withholding: 15, net_received: 105, estimated_tax: 12, payout_minus_tax: 93 },
    };
    mockApi.dividendsSummary.mockResolvedValueOnce(monthSummary);
    mockApi.dividendsByCompany.mockResolvedValueOnce({
      from_month: "2025-03",
      to_month: "2026-02",
      base_currency: "SGD",
      assumed_tax_rate: 0.1,
      country_tax_rates: { US: 0.15 },
      totals: { gross: 120, withholding: 15, net_received: 105, estimated_tax: 12, payout_minus_tax: 93 },
      items: [
        {
          asset_id: 1,
          symbol: "AAPL",
          company: "Apple Inc.",
          country: "US",
          gross: 120,
          withholding: 15,
          net_received: 105,
          estimated_tax: 12,
          payout_minus_tax: 93,
          yield_pct: 0.8,
        },
      ],
    });
    mockApi.expectedDividendsOverview.mockResolvedValueOnce({
      from_month: "2025-03",
      to_month: "2026-02",
      base_currency: "SGD",
      assumed_tax_rate: 0.1,
      country_tax_rates: { US: 0.15 },
      holdings_considered: 2,
      assets_with_actions: 1,
      actions_evaluated: 1,
      monthly: {
        period: "month",
        buckets: [{ bucket: "2026-02", gross: 100, estimated_tax: 15, payout_minus_tax: 85 }],
        gross: 100,
        estimated_tax: 15,
        payout_minus_tax: 85,
      },
      quarterly: {
        period: "quarter",
        buckets: [{ bucket: "2026-Q1", gross: 100, estimated_tax: 15, payout_minus_tax: 85 }],
        gross: 100,
        estimated_tax: 15,
        payout_minus_tax: 85,
      },
      yearly: {
        period: "year",
        buckets: [{ bucket: "2026", gross: 100, estimated_tax: 15, payout_minus_tax: 85 }],
        gross: 100,
        estimated_tax: 15,
        payout_minus_tax: 85,
      },
      companies: [
        {
          asset_id: 1,
          symbol: "AAPL",
          company: "Apple Inc.",
          country: "US",
          shares: 100,
          yield_pct: 2.5,
          price: 200,
          quote_currency: "USD",
          yearly_dividend: 100,
          quarterly_dividend: 25,
          monthly_dividend: 8.3333,
          gross: 100,
          estimated_tax: 15,
          payout_minus_tax: 85,
        },
      ],
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <Dividends />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByRole("heading", { name: "Dividends" })).toBeInTheDocument();
    expect(screen.getByText("Realized (Selected Month)")).toBeInTheDocument();
    expect(screen.getByText("By Company (Realized, Selected Month)")).toBeInTheDocument();
    expect(screen.getByText("Expected Dividends (Holdings-Based)")).toBeInTheDocument();
    expect(screen.getByText("By Company (Expected)")).toBeInTheDocument();
    expect(screen.getAllByText("Apple Inc.").length).toBeGreaterThanOrEqual(1);
  });
});
