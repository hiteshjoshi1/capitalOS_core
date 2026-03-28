import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import StockHoldings from "../routes/StockHoldings";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";
import type { StockHoldingsSummary } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    stockHoldingsSummary: vi.fn(),
    dividendsByCompany: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

const summaryFixture: StockHoldingsSummary = {
  as_of_month: "2026-02",
  base_currency: "SGD",
  snapshot_day: 6,
  net_worth_as_of: "2026-02-06T00:00:00+00:00",
  top_holdings: [
    {
      asset_id: 1,
      symbol: "700",
      asset_class: "STOCK",
      value: 120000,
      percent_of_networth: 24,
      quantity: 10.5,
      avg_cost: 123.45,
      latest_price: 150.12,
      quote_currency: "HKD",
      geo: "HK",
      platform: "IBKR",
    },
    {
      asset_id: 2,
      symbol: "INFY",
      asset_class: "STOCK",
      value: 90000,
      percent_of_networth: 18,
      quantity: 20,
      avg_cost: null,
      latest_price: null,
      quote_currency: "INR",
      geo: "IN",
      platform: "IBKR",
    },
    {
      asset_id: 3,
      symbol: "USD",
      asset_class: "CASH",
      value: 50000,
      percent_of_networth: 10,
      quantity: 1,
      avg_cost: null,
      latest_price: null,
      quote_currency: "USD",
      geo: "US",
      platform: "DBS",
    },
  ],
};

describe("StockHoldings", () => {
  it("renders dashboard-style header nav and native-currency detail columns", async () => {
    mockApi.stockHoldingsSummary.mockResolvedValueOnce(summaryFixture);
    mockApi.dividendsByCompany.mockResolvedValueOnce({
      from_month: "2025-03",
      to_month: "2026-02",
      base_currency: "SGD",
      assumed_tax_rate: 0,
      country_tax_rates: {},
      totals: { gross: 0, withholding: 0, net_received: 0, estimated_tax: 0, payout_minus_tax: 0 },
      items: [],
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("Top Holdings")).toBeInTheDocument();
    expect(screen.getByText("Dividends")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open full Dividends view" })).toBeInTheDocument();

    expect(screen.getByLabelText("Base currency")).toBeInTheDocument();
    expect(screen.getByLabelText("Month")).toBeInTheDocument();

    expect(screen.getByRole("columnheader", { name: "Shares" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Purchase Price" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Current Price" })).toBeInTheDocument();

    const hkRow = screen.getByText("700").closest("tr");
    expect(hkRow).not.toBeNull();
    if (hkRow) {
      const scoped = within(hkRow);
      expect(scoped.getByText("10.5")).toBeInTheDocument();
      expect(scoped.getByText("HKD 123.45")).toBeInTheDocument();
      expect(scoped.getByText("HKD 150.12")).toBeInTheDocument();
    }

    const inRow = screen.getByText("INFY").closest("tr");
    expect(inRow).not.toBeNull();
    if (inRow) {
      const scoped = within(inRow);
      expect(scoped.getByText("20")).toBeInTheDocument();
      expect(scoped.getAllByText("—").length).toBeGreaterThanOrEqual(2);
    }
  });

  it("shows top 20 positions first and reveals more on Next", async () => {
    const manyHoldings: StockHoldingsSummary = {
      ...summaryFixture,
      top_holdings: Array.from({ length: 25 }, (_, idx) => ({
        asset_id: idx + 100,
        symbol: `POS${idx + 1}`,
        asset_class: "STOCK" as const,
        value: 100000 - idx * 1000,
        percent_of_networth: 10 - idx * 0.1,
        quantity: idx + 1,
        avg_cost: 100 + idx,
        latest_price: 110 + idx,
        quote_currency: "USD",
        geo: "US",
        platform: "IBKR",
      })),
    };

    mockApi.stockHoldingsSummary.mockResolvedValueOnce(manyHoldings);
    mockApi.dividendsByCompany.mockResolvedValueOnce({
      from_month: "2025-03",
      to_month: "2026-02",
      base_currency: "SGD",
      assumed_tax_rate: 0,
      country_tax_rates: {},
      totals: { gross: 0, withholding: 0, net_received: 0, estimated_tax: 0, payout_minus_tax: 0 },
      items: [],
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("Showing 20 of 25 positions")).toBeInTheDocument();
    expect(screen.getByText("POS20")).toBeInTheDocument();
    expect(screen.queryByText("POS21")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("Showing 25 of 25 positions")).toBeInTheDocument();
    expect(screen.getByText("POS25")).toBeInTheDocument();
  });
});
