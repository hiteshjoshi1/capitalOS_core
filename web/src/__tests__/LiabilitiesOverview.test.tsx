import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import LiabilitiesOverview from "../routes/LiabilitiesOverview";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";
import type { Account, CreditCardDetail } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    creditCardTransactions: vi.fn(),
    accounts: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

function currentMonthYYYYMM() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

const detailFixture: CreditCardDetail = {
  month: "2026-07",
  base_currency: "SGD",
  total_spend: 311.5,
  cards: [
    {
      account_id: 11,
      account_name: "DBS Credit Card",
      card_name: "DBS/POSB MasterCard Platinum (2403)",
      issuer: "DBS",
      credit_limit: 60000,
      available_limit: 59739.44,
      available_limit_as_of: "2026-07-04T00:00:00+00:00",
      current_due_source: "available_limit",
      statement_day: 20,
      due_day: 25,
      due_date: "2026-07-25",
      current_due: 260.56,
      utilization: 260.56 / 60000,
    },
    {
      account_id: 12,
      account_name: "UOB One Card",
      card_name: "UOB One",
      issuer: "UOB",
      credit_limit: 8000,
      available_limit: null,
      available_limit_as_of: null,
      current_due_source: "statement",
      statement_day: 5,
      due_day: 11,
      due_date: "2026-07-11",
      current_due: 320,
      utilization: 320 / 8000,
    },
  ],
  transactions: [
    {
      account_id: 11,
      account_name: "DBS Credit Card",
      card_name: "DBS/POSB MasterCard Platinum (2403)",
      issuer: "DBS",
      ts: "2026-07-05T12:00:00+00:00",
      description: "Netflix",
      amount: -121,
      type: "EXPENSE",
      category: "CreditCard::Purchase",
      resolved_category: "Subscriptions",
      category_source: "override",
      merchant_counterparty: "Netflix",
      notes: "Annual plan",
    },
    {
      account_id: 11,
      account_name: "DBS Credit Card",
      card_name: "DBS/POSB MasterCard Platinum (2403)",
      issuer: "DBS",
      ts: "2026-07-03T12:00:00+00:00",
      description: "Hawker Center",
      amount: -178,
      type: "EXPENSE",
      category: "CreditCard::Purchase",
      resolved_category: "Dining",
      category_source: "override",
      merchant_counterparty: "Hawker Center",
      notes: null,
    },
    {
      account_id: 12,
      account_name: "UOB One Card",
      card_name: "UOB One",
      issuer: "UOB",
      ts: "2026-07-06T12:00:00+00:00",
      description: "Grab Rides",
      amount: -12.5,
      type: "EXPENSE",
      category: "CreditCard::Purchase",
      resolved_category: "Uncategorized",
      category_source: "parser",
      merchant_counterparty: "Grab",
      notes: null,
    },
    {
      account_id: 12,
      account_name: "UOB One Card",
      card_name: "UOB One",
      issuer: "UOB",
      ts: "2026-07-02T12:00:00+00:00",
      description: "Payment received",
      amount: 300,
      type: "PAYMENT",
      category: "CreditCard::Payment",
      resolved_category: "Payment",
      category_source: "parser",
      merchant_counterparty: null,
      notes: null,
    },
  ],
  top_purchases: [
    {
      account_id: 11,
      account_name: "DBS Credit Card",
      card_name: "DBS/POSB MasterCard Platinum (2403)",
      issuer: "DBS",
      ts: "2026-07-03T12:00:00+00:00",
      description: "Hawker Center",
      amount: -178,
      type: "EXPENSE",
      category: "CreditCard::Purchase",
      resolved_category: "Dining",
      category_source: "override",
      merchant_counterparty: "Hawker Center",
      notes: null,
    },
  ],
  recurring_payments: [
    {
      account_id: 11,
      account_name: "DBS Credit Card",
      card_name: "DBS/POSB MasterCard Platinum (2403)",
      issuer: "DBS",
      merchant_counterparty: "Netflix",
      months_present: 3,
      current_month_amount: 121,
    },
  ],
};

const priorDetailFixture: CreditCardDetail = {
  ...detailFixture,
  month: "2026-06",
  cards: [
    { ...detailFixture.cards[0], current_due: 200 },
    { ...detailFixture.cards[1], current_due: 380 },
  ],
};

const accountsFixture: Account[] = [
  { id: 11, name: "DBS Credit Card", platform: "DBS", account_type: "CREDIT_CARD", currency: "SGD" },
  { id: 12, name: "UOB One Card", platform: "UOB", account_type: "CREDIT_CARD", currency: "SGD" },
];

describe("LiabilitiesOverview route", () => {
  beforeEach(() => {
    vi.setSystemTime(new Date("2026-07-08T00:00:00Z"));
    window.localStorage.clear();
    mockApi.creditCardTransactions.mockImplementation((month: string) =>
      Promise.resolve(month === "2026-06" ? priorDetailFixture : detailFixture)
    );
    mockApi.accounts.mockResolvedValue(accountsFixture);
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
    window.localStorage.clear();
    cleanup();
  });

  it("renders State A (no loans linked): hero, wallet, single upcoming payments list, no-loans banner", async () => {
    render(
      <ThemeProvider>
        <MemoryRouter>
          <LiabilitiesOverview />
        </MemoryRouter>
      </ThemeProvider>
    );

    expect(await screen.findByText("Credit card balance")).toBeInTheDocument();
    expect(mockApi.creditCardTransactions).toHaveBeenCalledWith(currentMonthYYYYMM(), "SGD");
    expect(mockApi.accounts).toHaveBeenCalled();

    // Hero value = sum of current_due (260.56 + 320 = 580.56 -> rounded 581)
    expect(screen.getByText("S$ 581")).toBeInTheDocument();
    expect(screen.getByText(/2 cards linked · blended utilization/)).toBeInTheDocument();

    // Wallet tiles (colorful cards, moved from the former Credit Cards page)
    expect(await screen.findByText("Wallet")).toBeInTheDocument();
    expect(screen.getAllByText("DBS/POSB MasterCard Platinum (2403)").length).toBeGreaterThan(0);
    expect(screen.getAllByText("UOB One").length).toBeGreaterThan(0);

    // Exactly one "Upcoming payments" section — not duplicated across pages
    expect(screen.getAllByText("Upcoming payments")).toHaveLength(1);
    const upcomingSection = screen.getByText("Upcoming payments").closest("section") as HTMLElement;
    expect(within(upcomingSection).getByText("Not synced")).toBeInTheDocument();
    expect(within(upcomingSection).getByText(/Due in 3d/)).toBeInTheDocument();

    // No loans linked in this fixture -> dashed banner, not the full Loans section
    expect(screen.getByText("No loans linked")).toBeInTheDocument();
    expect(screen.getByText("Connect a loan")).toBeDisabled();
    expect(screen.queryByText("Loans")).not.toBeInTheDocument();

    // Spend by category: multiple real categories, not a single bucket
    const categorySection = screen.getByText("Spend by category").closest("section") as HTMLElement;
    expect(within(categorySection).getByText("Subscriptions")).toBeInTheDocument();
    expect(within(categorySection).getByText("Dining")).toBeInTheDocument();
    expect(within(categorySection).getByText("Uncategorized")).toBeInTheDocument();

    // Notable charges: >S$50 EXPENSE only — Grab Rides ($12.50) and the PAYMENT excluded
    const notableSection = screen.getByText("Notable charges").closest("section") as HTMLElement;
    expect(within(notableSection).getByText("Netflix")).toBeInTheDocument();
    expect(within(notableSection).getByText("Hawker Center")).toBeInTheDocument();
    expect(within(notableSection).queryByText("Grab")).not.toBeInTheDocument();
    expect(within(notableSection).queryByText("Payment received")).not.toBeInTheDocument();

    // Recurring charges reuse existing recurring_payments data
    expect(screen.getByText("Recurring charges")).toBeInTheDocument();
    expect(screen.getByText(/DBS\/POSB MasterCard Platinum \(2403\) · 3 months/)).toBeInTheDocument();

    // Ledger collapsed by default
    expect(screen.getByText("Show all 4 transactions")).toBeInTheDocument();
    expect(screen.queryByText("Payment received")).not.toBeInTheDocument();
  });

  it("expands the full transaction ledger on toggle", async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <MemoryRouter>
          <LiabilitiesOverview />
        </MemoryRouter>
      </ThemeProvider>
    );

    await screen.findByText("Wallet");
    await user.click(screen.getByText("Show all 4 transactions"));

    expect(screen.getByText("Payment received")).toBeInTheDocument();
    expect(screen.getByText("Show less")).toBeInTheDocument();
  });

  it("renders State B when a LOAN account is linked", async () => {
    mockApi.accounts.mockResolvedValue([
      ...accountsFixture,
      { id: 20, name: "Home Loan", platform: "OCBC", account_type: "LOAN", currency: "SGD" },
    ]);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <LiabilitiesOverview />
        </MemoryRouter>
      </ThemeProvider>
    );

    expect(await screen.findByText("Total liabilities")).toBeInTheDocument();
    expect(screen.getByText("Loans")).toBeInTheDocument();
    expect(screen.getAllByText("Home Loan").length).toBeGreaterThan(0);
    expect(screen.queryByText("No loans linked")).not.toBeInTheDocument();

    // Loan upcoming-payment row still lives in the single shared upcoming-payments section
    expect(screen.getAllByText("Upcoming payments")).toHaveLength(1);
  });

  it("renders empty states when no credit card data exists", async () => {
    mockApi.creditCardTransactions.mockResolvedValue({
      month: "2026-07",
      base_currency: "SGD",
      total_spend: 0,
      cards: [],
      transactions: [],
      top_purchases: [],
      recurring_payments: [],
    });
    mockApi.accounts.mockResolvedValue([]);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <LiabilitiesOverview />
        </MemoryRouter>
      </ThemeProvider>
    );

    expect(await screen.findByText("Wallet")).toBeInTheDocument();
    expect(screen.getByText("No credit cards linked yet.")).toBeInTheDocument();
    expect(screen.getByText("No upcoming payments.")).toBeInTheDocument();
    expect(screen.getByText("No categorized spend for this month.")).toBeInTheDocument();
    expect(screen.getByText("No notable charges this month.")).toBeInTheDocument();
    expect(screen.getByText("No recurring payments detected in the last 3 months.")).toBeInTheDocument();
  });

  it("keeps month fixed when base currency changes", async () => {
    const user = userEvent.setup();

    render(
      <ThemeProvider>
        <MemoryRouter>
          <LiabilitiesOverview />
        </MemoryRouter>
      </ThemeProvider>
    );

    await screen.findByText("Wallet");
    await user.selectOptions(screen.getByLabelText("Base currency"), "USD");

    expect(mockApi.creditCardTransactions).toHaveBeenCalledWith(currentMonthYYYYMM(), "SGD");
    expect(mockApi.creditCardTransactions).toHaveBeenCalledWith(currentMonthYYYYMM(), "USD");
    expect(screen.getByLabelText("Month")).toHaveValue(currentMonthYYYYMM());
  });
});
