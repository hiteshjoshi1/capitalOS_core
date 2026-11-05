import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { controlledCalls, monthBefore } from "./raceHelpers";
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

// #148: out-of-order replies on month and currency switches.
describe("CashOverview races", () => {
  function renderPage() {
    return render(
      <ThemeProvider>
        <MemoryRouter>
          <CashOverview />
        </MemoryRouter>
      </ThemeProvider>,
    );
  }

  beforeEach(() => {
    window.localStorage.clear();
    mockApi.cryptoSummary.mockResolvedValue(cryptoSummaryFixture);
  });

  it("a slow earlier month never renders under the later month, and is aborted", async () => {
    const deposits = controlledCalls<CashDeposits>();
    mockApi.cashDeposits.mockImplementation(deposits.impl as typeof api.cashDeposits);
    const thisMonth = currentMonthYYYYMM();
    const lastMonth = monthBefore(thisMonth);
    renderPage();

    fireEvent.change(screen.getByLabelText("Month"), { target: { value: lastMonth } });
    const slow = deposits.find((args) => args[0] === thisMonth);
    const fast = deposits.find((args) => args[0] === lastMonth);

    await act(async () =>
      fast.resolve({ ...cashDepositsFixture, is_live: false, as_of_month: lastMonth, current_total: 11111 }),
    );
    expect(await screen.findByText("S$ 11,111")).toBeInTheDocument();
    expect(screen.getByText(`CASH — ${lastMonth}`)).toBeInTheDocument();

    await act(async () => slow.resolve({ ...cashDepositsFixture, current_total: 99999 }));
    expect(screen.queryByText("S$ 99,999")).not.toBeInTheDocument();
    expect(screen.getByText("S$ 11,111")).toBeInTheDocument();
    await waitFor(() => expect(slow.signal?.aborted).toBe(true));
  });

  it("keeps the previous currency's numbers, labelled in that currency, until the new one lands", async () => {
    const deposits = controlledCalls<CashDeposits>();
    mockApi.cashDeposits.mockImplementation(deposits.impl as typeof api.cashDeposits);
    renderPage();
    await act(async () =>
      deposits.find((a) => a[1] === "SGD").resolve({ ...cashDepositsFixture, current_total: 40000 }),
    );
    expect((await screen.findAllByText("S$ 40,000")).length).toBeGreaterThan(0);

    fireEvent.change(screen.getByLabelText("Base currency"), { target: { value: "USD" } });
    // Not blanked to "Loading…", and still labelled S$ (the numbers are SGD).
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
    expect(screen.getAllByText("S$ 40,000")[0].closest("[aria-busy]")).toHaveAttribute("aria-busy", "true");

    await act(async () =>
      deposits
        .find((a) => a[1] === "USD")
        .resolve({ ...cashDepositsFixture, base_currency: "USD", current_total: 30000 }),
    );
    expect((await screen.findAllByText("USD 30,000")).length).toBeGreaterThan(0);
    expect(screen.queryByText("S$ 40,000")).not.toBeInTheDocument();
  });
});

// #150: the base currency is shared, so a choice made on another page applies here.
describe("CashOverview shared currency", () => {
  it("loads in the currency chosen elsewhere, and formats deltas with the shared rules", async () => {
    window.localStorage.setItem("capitalos.baseCurrency", "USD");
    mockApi.cryptoSummary.mockResolvedValue(cryptoSummaryFixture);
    mockApi.cashDeposits.mockResolvedValue({ ...cashDepositsFixture, base_currency: "USD" });
    render(
      <ThemeProvider>
        <MemoryRouter>
          <CashOverview />
        </MemoryRouter>
      </ThemeProvider>,
    );
    expect((await screen.findAllByText("USD 40,000")).length).toBeGreaterThan(0);
    expect(mockApi.cashDeposits).toHaveBeenCalledWith(currentMonthYYYYMM(), "USD");
    expect(screen.getByLabelText("Base currency")).toHaveValue("USD");
    // Currency rows: "<amount> (<signed delta>)", sign before the prefix.
    expect(screen.getByText("USD 25,000 (+USD 3,000)")).toBeInTheDocument();
  });
});

// #151: the donut is announced with its data.
describe("CashOverview chart accessibility", () => {
  it("exposes the donut as an image described by its shares", async () => {
    mockApi.cashDeposits.mockResolvedValue(cashDepositsFixture);
    mockApi.cryptoSummary.mockResolvedValue(cryptoSummaryFixture);
    render(
      <ThemeProvider>
        <MemoryRouter>
          <CashOverview />
        </MemoryRouter>
      </ThemeProvider>,
    );
    const donut = await screen.findByRole("img", { name: "Cash by account" });
    expect(donut).toHaveAccessibleDescription("Cash by account: DBS 62.5%, OCBC 37.5%");
    expect(screen.getByRole("img", { name: "Six-month cash trend" })).toHaveAccessibleDescription(/Jan '26 S\$ 35K/);
  });
});
