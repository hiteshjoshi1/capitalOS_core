import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import StockHoldings from "../routes/StockHoldings";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";
import type { DashboardSummary } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    dashboardSummary: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

const summaryFixture: DashboardSummary = {
  as_of_month: "2026-02",
  base_currency: "SGD",
  snapshot_day: 6,
  net_worth_as_of: "2026-02-06T00:00:00+00:00",
  net_worth_change: null,
  net_worth: {
    total: 500000,
    cash: 50000,
    stocks_funds: 450000,
    crypto: 0,
    liabilities: 0,
  },
  geography: [],
  cash_flow: {
    income: 0,
    expenses: 0,
    net: 0,
    savings_rate: null,
  },
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
  cash_balances: [{ currency: "USD", value: 50000 }],
  cash_percent: 10.0,
};

describe("StockHoldings", () => {
  it("renders dashboard-style header nav and native-currency detail columns", async () => {
    mockApi.dashboardSummary.mockResolvedValueOnce(summaryFixture);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <StockHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("Top Holdings")).toBeInTheDocument();

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
});
