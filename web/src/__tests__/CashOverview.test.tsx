import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import CashOverview from "../routes/CashOverview";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";
import type { CashDeposits, CryptoSummary } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    cashDeposits: vi.fn(),
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

const cryptoSummaryFixture: CryptoSummary = {
  month: "2026-02",
  snapshot_day: 6,
  snapshot_as_of: "2026-02-06",
  total_crypto_usd: 0,
  total_crypto_base: 0,
  snapshot_total_base: 0,
  snapshot_total_usd: 0,
  snapshot_delta_base: 0,
  snapshot_delta_pct: 0,
  base_currency: "SGD",
  trend: [],
  eth: { balance: 0, value_usd: 0, value_base: 0 },
  sol: { balance: 0, value_usd: 0, value_base: 0 },
  top5_holdings: [],
  top_holdings: [],
  chain_exposure: [],
  last_refreshed_at: "2026-02-06T00:00:00+00:00",
  is_stale: false,
  refresh_triggered: false,
};

const cashDepositsFixture: CashDeposits = {
  total: 40000,
  as_of_month: "2026-02",
  base_currency: "SGD",
  snapshot_day: 6,
  is_live: true,
  compare_month: "2026-01",
  current_cash_as_of: "2026-02-21T00:00:00+00:00",
  snapshot_cash_as_of: "2026-02-06T00:00:00+00:00",
  current_total: 40000,
  snapshot_total: 36000,
  delta_abs: 4000,
  delta_pct: 4000 / 36000,
  trend: [
    { month: "2025-11", value: null },
    { month: "2025-12", value: null },
    { month: "2026-01", value: 35000 },
    { month: "2026-02", value: 36000 },
  ],
  currency_breakdown: [
    { currency: "SGD", current_value: 25000, snapshot_value: 22000, delta_abs: 3000, delta_pct: 3000 / 22000 },
    { currency: "USD", current_value: 15000, snapshot_value: 14000, delta_abs: 1000, delta_pct: 1000 / 14000 },
  ],
  items: [
    { source: "DBS", value: 25000, percent: 62.5 },
    { source: "OCBC", value: 15000, percent: 37.5 },
  ],
};

describe("CashOverview route", () => {
  beforeEach(() => {
    mockApi.cashDeposits.mockResolvedValue(cashDepositsFixture);
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

    expect(await screen.findByText("CURRENT CASH")).toBeInTheDocument();
    const cashSitsHeading = screen.getByText("Where the cash sits");
    const currencyHeading = screen.getByText("Currency mix and stablecoins");
    const stablecoinsHeading = screen.getByText("Stablecoins");
    const trendHeading = screen.getByText("Six-month cash trend");
    expect(currencyHeading).toBeInTheDocument();
    expect(screen.getByText("Currency exposure")).toBeInTheDocument();
    expect(screen.getAllByText("DBS").length).toBeGreaterThan(0);
    expect(screen.getByText("62.5%")).toBeInTheDocument();
    expect(trendHeading).toBeInTheDocument();
    expect(screen.getByLabelText("Six-month cash trend")).toBeInTheDocument();
    expect(cashSitsHeading.compareDocumentPosition(trendHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(currencyHeading.compareDocumentPosition(trendHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(stablecoinsHeading.compareDocumentPosition(trendHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText("Nov '25")).not.toBeInTheDocument();
    expect(screen.queryByText("Dec '25")).not.toBeInTheDocument();
    expect(screen.getAllByText("Jan '26").length).toBeGreaterThan(0);
    expect(screen.getAllByText("S$ 35K").length).toBeGreaterThan(0);

    expect(mockApi.cashDeposits).toHaveBeenCalledWith(currentMonthYYYYMM(), "SGD");
    expect(mockApi.cryptoSummary).toHaveBeenCalledWith(currentMonthYYYYMM(), "SGD");
    expect(screen.getByLabelText("Month")).toHaveValue(currentMonthYYYYMM());

    await user.selectOptions(screen.getByLabelText("Base currency"), "USD");

    expect(mockApi.cashDeposits).toHaveBeenCalledWith(currentMonthYYYYMM(), "USD");
    expect(mockApi.cryptoSummary).toHaveBeenCalledWith(currentMonthYYYYMM(), "USD");
  });
});
