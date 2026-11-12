// #417 (U17): Income → Dividends, next 3 months.
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DividendCalendar } from "../lib/api";
import DividendCalendarCard from "../components/DividendCalendarCard";
import { basisLabel, coverageText } from "../lib/dividendCalendar";
import { api } from "../lib/api";

vi.mock("../lib/api", () => ({ api: { dividendCalendar: vi.fn() } }));
const mockApi = vi.mocked(api, true);

function calendar(overrides: Partial<DividendCalendar> = {}): DividendCalendar {
  return {
    base_currency: "SGD",
    from_date: "2026-11-12",
    to_date: "2027-02-11",
    events: [
      {
        asset_id: 1,
        symbol: "D05",
        company: "DBS Group",
        date: "2026-11-13",
        ex_date: "2026-11-13",
        pay_date: null,
        shares: 300,
        amount_per_share: 0.81,
        currency: "SGD",
        amount: 243,
        amount_base: 243,
        basis: "announced",
        estimated: true,
      },
      {
        asset_id: 2,
        symbol: "AAPL",
        company: "Apple Inc.",
        date: "2027-02-12",
        ex_date: "2027-02-09",
        pay_date: "2027-02-12",
        shares: 10,
        amount_per_share: 0.26,
        currency: "USD",
        amount: 2.6,
        amount_base: 3.38,
        basis: "projected",
        estimated: true,
      },
    ],
    months: [
      { month: "2026-11", amount_base: 243, count: 1 },
      { month: "2026-12", amount_base: 0, count: 0 },
      { month: "2027-02", amount_base: 3.38, count: 1 },
    ],
    total_base: 246.38,
    holdings_considered: 5,
    holdings_with_events: 2,
    holdings_without_data: 3,
    holdings_no_dividend_history: 1,
    data_as_of: "2026-11-12T05:00:00+00:00",
    ...overrides,
  };
}

describe("dividend calendar (U17)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists each expected dividend under its month, saying how it's known", async () => {
    mockApi.dividendCalendar.mockResolvedValue(calendar());
    render(<DividendCalendarCard baseCurrency="SGD" />);
    expect(await screen.findByText("DBS Group")).toBeInTheDocument();
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
    expect(screen.getByText("Date listed")).toBeInTheDocument();
    expect(screen.getByText("Estimated")).toBeInTheDocument();
    expect(screen.getByText(/Paid 12 Feb 2027/)).toBeInTheDocument();
    expect(screen.getByText(/Ex-date 13 Nov 2026/)).toBeInTheDocument();
    expect(screen.getByText(/2 of 5 holdings expected to pay · 2 usually pay at other times of year · 1 with no dividend history/)).toBeInTheDocument();
    expect(mockApi.dividendCalendar).toHaveBeenCalledWith("SGD", 3);
  });

  it("says so when nothing is expected", async () => {
    mockApi.dividendCalendar.mockResolvedValue(calendar({ events: [], months: [], total_base: 0, holdings_with_events: 0 }));
    render(<DividendCalendarCard baseCurrency="SGD" />);
    expect(await screen.findByText(/No dividends expected in 12 Nov 2026 – 11 Feb 2027/)).toBeInTheDocument();
  });

  it("names each basis", () => {
    expect(basisLabel("your_payments").label).toBe("From your payments");
    expect(basisLabel("whatever").label).toBe("Estimated");
    expect(coverageText(calendar({ holdings_without_data: 0, holdings_no_dividend_history: 0, holdings_considered: 1, holdings_with_events: 1 }))).toBe(
      "1 of 1 holding expected to pay",
    );
  });
});
