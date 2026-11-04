import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { controlledCalls } from "./raceHelpers";
import type { DividendsByCompany, DividendsSummary, ExpectedDividendsOverview } from "../lib/api";
import { beforeEach, describe, expect, it, vi } from "vitest";
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
  beforeEach(() => {
    vi.clearAllMocks();
  });

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
    expect(await screen.findByText("REALIZED THIS MONTH")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What's received vs. what's ahead" })).toBeInTheDocument();
    expect(screen.getByText("Expected, next 12 months")).toBeInTheDocument();
    expect(screen.getByText("Portfolio coverage")).toBeInTheDocument();
    expect(screen.getByText("12-month dividend income")).toBeInTheDocument();
    expect(screen.getByText("Who paid you this month")).toBeInTheDocument();
    expect((await screen.findAllByText("Apple Inc.")).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByLabelText("Assumed tax rate percent")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Country tax rates")).not.toBeInTheDocument();

    const user = (await import("@testing-library/user-event")).default.setup();
    await user.click(screen.getByRole("button", { name: "Expected" }));
    expect(await screen.findByText("Projected annual payers")).toBeInTheDocument();
    expect(screen.getAllByText("Apple Inc.").length).toBeGreaterThanOrEqual(1);
  });

  it("renders API error state when loading fails", async () => {
    mockApi.dividendsSummary.mockRejectedValueOnce(new Error("dividends failed"));
    mockApi.dividendsByCompany.mockResolvedValueOnce({
      from_month: "2026-01",
      to_month: "2026-02",
      base_currency: "SGD",
      assumed_tax_rate: 0,
      country_tax_rates: {},
      totals: { gross: 0, withholding: 0, net_received: 0, estimated_tax: 0, payout_minus_tax: 0 },
      items: [],
    });
    mockApi.expectedDividendsOverview.mockResolvedValueOnce({
      from_month: "2026-01",
      to_month: "2026-02",
      base_currency: "SGD",
      assumed_tax_rate: 0,
      country_tax_rates: {},
      holdings_considered: 0,
      assets_with_actions: 0,
      actions_evaluated: 0,
      monthly: { period: "month", buckets: [], gross: 0, estimated_tax: 0, payout_minus_tax: 0 },
      quarterly: { period: "quarter", buckets: [], gross: 0, estimated_tax: 0, payout_minus_tax: 0 },
      yearly: { period: "year", buckets: [], gross: 0, estimated_tax: 0, payout_minus_tax: 0 },
      companies: [],
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <Dividends />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("Couldn't load dividends")).toBeInTheDocument();
    expect(screen.getByText("dividends failed")).toBeInTheDocument();
  });

  it("renders empty-state tables and refetches when controls change", async () => {
    mockApi.dividendsSummary.mockResolvedValue({
      from_month: "2025-03",
      to_month: "2026-02",
      period: "month",
      base_currency: "SGD",
      assumed_tax_rate: 0.1,
      country_tax_rates: {},
      buckets: [],
      totals: { gross: 0, withholding: 0, net_received: 0, estimated_tax: 0, payout_minus_tax: 0 },
    });
    mockApi.dividendsByCompany.mockResolvedValue({
      from_month: "2026-02",
      to_month: "2026-02",
      base_currency: "SGD",
      assumed_tax_rate: 0.1,
      country_tax_rates: {},
      totals: { gross: 0, withholding: 0, net_received: 0, estimated_tax: 0, payout_minus_tax: 0 },
      items: [],
    });
    mockApi.expectedDividendsOverview.mockResolvedValue({
      from_month: "2025-03",
      to_month: "2026-02",
      base_currency: "SGD",
      assumed_tax_rate: 0.1,
      country_tax_rates: {},
      holdings_considered: 0,
      assets_with_actions: 0,
      actions_evaluated: 0,
      monthly: { period: "month", buckets: [], gross: 0, estimated_tax: 0, payout_minus_tax: 0 },
      quarterly: { period: "quarter", buckets: [], gross: 0, estimated_tax: 0, payout_minus_tax: 0 },
      yearly: { period: "year", buckets: [], gross: 0, estimated_tax: 0, payout_minus_tax: 0 },
      companies: [],
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <Dividends />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("No dividends in selected range.")).toBeInTheDocument();
    expect(screen.getByText("No company-level dividend records yet.")).toBeInTheDocument();

    const user = (await import("@testing-library/user-event")).default.setup();
    await user.click(screen.getByRole("button", { name: "Expected" }));
    expect(await screen.findByText("No expected dividend estimates found for selected range.")).toBeInTheDocument();

    await waitFor(() => {
      expect(mockApi.dividendsSummary).toHaveBeenLastCalledWith(
        expect.any(String),
        expect.any(String),
        "month",
        "SGD",
      );
    });
    expect(mockApi.dividendsByCompany).toHaveBeenLastCalledWith(
      expect.any(String),
      expect.any(String),
      "SGD",
    );
    expect(mockApi.expectedDividendsOverview).toHaveBeenLastCalledWith(
      expect.any(String),
      expect.any(String),
      "SGD",
    );
  });
});

// #148: the realized-this-month hero follows the selected month, whatever order replies land in.
describe("Dividends races", () => {
  const totals = { gross: 0, withholding: 0, net_received: 0, estimated_tax: 0, payout_minus_tax: 0 };
  const summaryFor = (month: string, payout: number): DividendsSummary => ({
    from_month: "2025-01",
    to_month: month,
    period: "month",
    base_currency: "SGD",
    assumed_tax_rate: 0.1,
    country_tax_rates: {},
    buckets: [{ bucket: month, gross: payout, withholding: 0, net_received: payout, estimated_tax: 0, payout_minus_tax: payout }],
    totals,
  });

  it("a slow earlier month never renders under the later month", async () => {
    vi.clearAllMocks();
    window.localStorage.setItem("capitalos.selectedMonth", "2026-02");
    const summaries = controlledCalls<DividendsSummary>();
    mockApi.dividendsSummary.mockImplementation(summaries.impl as typeof api.dividendsSummary);
    mockApi.dividendsByCompany.mockResolvedValue({
      from_month: "2026-01", to_month: "2026-01", base_currency: "SGD", assumed_tax_rate: 0.1,
      country_tax_rates: {}, items: [], totals,
    } as DividendsByCompany);
    mockApi.expectedDividendsOverview.mockResolvedValue({
      from_month: "2025-01", to_month: "2026-01", base_currency: "SGD", assumed_tax_rate: 0.1,
      country_tax_rates: {}, holdings_considered: 0, assets_with_actions: 0, actions_evaluated: 0,
      yearly: { period: "year", buckets: [], gross: 0, estimated_tax: 0, payout_minus_tax: 0 },
      companies: [],
    } as unknown as ExpectedDividendsOverview);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <Dividends />
        </MemoryRouter>
      </ThemeProvider>,
    );
    fireEvent.change(screen.getByLabelText("Month"), { target: { value: "2026-01" } });
    const feb = summaries.find((a) => a[1] === "2026-02");
    const jan = summaries.find((a) => a[1] === "2026-01");

    await act(async () => jan.resolve(summaryFor("2026-01", 111)));
    expect((await screen.findAllByText("S$ 111")).length).toBeGreaterThan(0);
    await act(async () => feb.resolve(summaryFor("2026-02", 999)));
    expect(screen.queryByText("S$ 999")).not.toBeInTheDocument();
    await waitFor(() => expect(feb.signal?.aborted).toBe(true));
  });
});
