import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import CashOverview from "../routes/CashOverview";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";
import type { CashDeposits, DashboardSummary, CryptoSummary } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    cashDeposits: vi.fn(),
    dashboardSummary: vi.fn(),
    cryptoSummary: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

function currentMonthYYYYMM() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

const summaryFixture: DashboardSummary = {
  as_of_month: "2026-02",
  base_currency: "SGD",
  snapshot_day: 6,
  net_worth_as_of: "2026-02-06T00:00:00+00:00",
  net_worth_change: null,
  net_worth: {
    total: 100000,
    cash: 40000,
    stocks_funds: 60000,
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
  top_holdings: [],
  cash_balances: [{ currency: "SGD", value: 25000 }],
  cash_percent: 40.0,
};

const cryptoSummaryFixture: CryptoSummary = {
  total_crypto_usd: 0,
  total_crypto_base: 0,
  base_currency: "SGD",
  eth: { balance: 0, value_usd: 0, value_base: 0 },
  sol: { balance: 0, value_usd: 0, value_base: 0 },
  top5_holdings: [],
  top_holdings: [],
  last_refreshed_at: "2026-02-06T00:00:00+00:00",
  is_stale: false,
  refresh_triggered: false,
};

const cashDepositsFixture: CashDeposits = {
  total: 40000,
  items: [
    { source: "DBS", value: 25000, percent: 62.5 },
    { source: "OCBC", value: 15000, percent: 37.5 },
  ],
};

describe("CashOverview route", () => {
  beforeEach(() => {
    mockApi.cashDeposits.mockResolvedValue(cashDepositsFixture);
    mockApi.dashboardSummary.mockResolvedValue(summaryFixture);
    mockApi.cryptoSummary.mockResolvedValue(cryptoSummaryFixture);
  });

  it("uses dashboard+ingest nav and keeps month fixed", async () => {
    const user = userEvent.setup();

    render(
      <ThemeProvider>
        <MemoryRouter>
          <CashOverview />
        </MemoryRouter>
      </ThemeProvider>
    );

    expect(await screen.findByText("Cash Deposits")).toBeInTheDocument();
    expect(screen.getByText("Cash Balances")).toBeInTheDocument();
    expect(screen.getByText("DBS")).toBeInTheDocument();
    expect(screen.getByText("62.5%")).toBeInTheDocument();

    expect(mockApi.dashboardSummary).toHaveBeenCalledWith(currentMonthYYYYMM(), "prev_month,prev_year", "SGD");
    expect(mockApi.cashDeposits).toHaveBeenCalledWith(currentMonthYYYYMM(), "SGD");
    expect(screen.getByLabelText("Month")).toHaveValue(currentMonthYYYYMM());

    await user.selectOptions(screen.getByLabelText("Base currency"), "USD");

    expect(mockApi.dashboardSummary).toHaveBeenCalledWith(currentMonthYYYYMM(), "prev_month,prev_year", "USD");
    expect(mockApi.cashDeposits).toHaveBeenCalledWith(currentMonthYYYYMM(), "USD");
  });
});
