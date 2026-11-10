import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { controlledCalls } from "./raceHelpers";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import LiabilitiesOverview from "../routes/LiabilitiesOverview";
import { api } from "../lib/api";
import type { Account, CreditCardAnalytics, CreditCardTransaction } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    creditCardAnalytics: vi.fn(),
    creditCardBalances: vi.fn(),
    accounts: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

function tx(overrides: Partial<CreditCardTransaction> = {}): CreditCardTransaction {
  return {
    account_id: 1,
    account_name: "Amex Platinum",
    card_name: "Amex Platinum",
    issuer: "Amex",
    ts: "2026-07-08T00:00:00+00:00",
    description: "Singapore Airlines",
    amount: -12640,
    type: "EXPENSE",
    category: "Travel",
    resolved_category: "Travel",
    category_source: "parser",
    merchant_counterparty: "SIA",
    notes: null,
    ...overrides,
  };
}

function makeAnalytics(overrides: Partial<CreditCardAnalytics> = {}): CreditCardAnalytics {
  return {
    month: "2026-07",
    base_currency: "SGD",
    months: 12,
    account_id: null,
    total_spend: 53192,
    transaction_count: 64,
    purchase_spend: 52880.94,
    prior_month: "2026-06",
    prior_month_spend: 29742,
    cards: [
      {
        account_id: 1,
        account_name: "Amex Platinum",
        card_name: "Amex Platinum",
        issuer: "Amex",
        spend: 40820,
        transaction_count: 22,
        available_limit: null,
        available_limit_as_of: null,
        statement_day: 15,
        due_day: 22,
        due_date: "2026-07-22",
      },
      {
        account_id: 2,
        account_name: "DBS Credit Card",
        card_name: "DBS Credit Card",
        issuer: "DBS",
        spend: 8202,
        transaction_count: 18,
        available_limit: 59739.44,
        available_limit_as_of: "2026-07-04T00:00:00+00:00",
        statement_day: 20,
        due_day: 25,
        due_date: "2026-07-25",
      },
    ],
    charges: [
      tx({ account_id: 2, card_name: "DBS Credit Card", description: "DBS Annual Membership Fee", amount: -196.2, type: "FEE", category: "Fees", resolved_category: "Fees" }),
    ],
    charge_total: 196.2,
    categories: [
      { label: "Travel", amount: 18420, percent: 0.346 },
      { label: "Shopping", amount: 12380, percent: 0.232 },
    ],
    trend: Array.from({ length: 12 }, (_, i) => ({ month: `2025-${String(8 + i).padStart(2, "0")}`, spend: 25000 + i * 1000 })),
    transactions: [
      tx(),
      tx({ account_id: 2, card_name: "DBS Credit Card", description: "DBS Annual Membership Fee", amount: -196.2, type: "FEE", category: "Fees", resolved_category: "Fees" }),
    ],
    recurring_payments: [
      {
        account_id: 1,
        account_name: "Amex Platinum",
        card_name: "Amex Platinum",
        issuer: "Amex",
        merchant_counterparty: "Netflix",
        months_present: 3,
        current_month_amount: 22,
      },
    ],
    ...overrides,
  };
}

const noLoans: Account[] = [
  { id: 1, name: "Amex Platinum", platform: "AMEX", account_type: "CREDIT_CARD", currency: "SGD" },
  { id: 2, name: "DBS Credit Card", platform: "DBS", account_type: "CREDIT_CARD", currency: "SGD" },
];

function renderPage() {
  return render(
    <MemoryRouter>
      <LiabilitiesOverview />
    </MemoryRouter>,
  );
}

describe("LiabilitiesOverview route", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.accounts.mockResolvedValue(noLoans);
    // #300's card balances section has its own request; empty here.
    mockApi.creditCardBalances.mockResolvedValue({
      base_currency: "SGD", as_of: "2026-07-20", total_owed_base: 0, flagged_count: 0, cards: [],
      fx_incomplete: false, fx_missing_currencies: [],
    } as never);
  });

  it("renders the hero spend, charge total, and largest category once loaded", async () => {
    mockApi.creditCardAnalytics.mockResolvedValue(makeAnalytics());
    renderPage();

    expect(await screen.findByText("S$ 53,192")).toBeInTheDocument();
    expect(screen.getByText("64 purchases across 2 cards")).toBeInTheDocument();
    const largestCategoryCard = screen.getByText("Largest category").closest("article")!;
    expect(within(largestCategoryCard).getByText("Travel")).toBeInTheDocument();
  });

  it("notes card spend left out for lack of an FX rate (#170)", async () => {
    mockApi.creditCardAnalytics.mockResolvedValue(
      makeAnalytics({ fx_incomplete: true, fx_missing_currencies: ["XYZ"], fx_stale_currencies: [] }),
    );
    renderPage();

    expect(await screen.findByText("S$ 53,192")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("Excludes amounts in XYZ");
  });

  it("filters by card, updating hero, trend meta, and ledger together", async () => {
    mockApi.creditCardAnalytics.mockResolvedValue(makeAnalytics());
    renderPage();
    await screen.findByText("S$ 53,192");
    expect(mockApi.creditCardAnalytics).toHaveBeenCalledWith(expect.any(String), "SGD", 12, null);

    mockApi.creditCardAnalytics.mockResolvedValue(
      makeAnalytics({ account_id: 1, total_spend: 40820, prior_month_spend: 20000, transaction_count: 22 }),
    );
    fireEvent.click(screen.getByRole("button", { name: /Amex Platinum/ }));

    await waitFor(() => {
      const lastCall = mockApi.creditCardAnalytics.mock.calls.at(-1)!;
      expect(lastCall[3]).toBe(1);
    });
    await waitFor(() => {
      expect(document.querySelector(".coHeroValue")?.textContent).toBe("S$ 40,820");
    });
  });

  it("shows fee/interest/tax charges prominently, or a positive no-charges state", async () => {
    mockApi.creditCardAnalytics.mockResolvedValue(makeAnalytics());
    renderPage();
    expect(await screen.findByText("1 card charge need attention")).toBeInTheDocument();
    // #266: "Show charges" filters the one transaction list to fees, interest and tax.
    fireEvent.click(screen.getByRole("button", { name: "Show charges" }));
    const filters = screen.getByRole("group", { name: "Filter transactions" });
    expect(within(filters).getByRole("button", { name: /Fees & charges/ })).toHaveAttribute("aria-pressed", "true");
    const table = screen.getByRole("table");
    expect(within(table).getByText("DBS Annual Membership Fee")).toBeInTheDocument();
    expect(within(table).queryByText("SIA")).not.toBeInTheDocument();

    mockApi.creditCardAnalytics.mockResolvedValue(makeAnalytics({ charges: [], charge_total: 0 }));
    renderPage();
    expect(await screen.findAllByText("No card charges this month.")).not.toHaveLength(0);
  });

  it("shows the 12-month trend chart and category breakdown", async () => {
    mockApi.creditCardAnalytics.mockResolvedValue(makeAnalytics());
    renderPage();
    expect(await screen.findByText("12-month spending trend")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /credit card spend trend/ })).toBeInTheDocument();
    const categoryCard = screen.getByText("Spend by category").closest("article")!;
    expect(within(categoryCard).getByText("Travel")).toBeInTheDocument();
    expect(within(categoryCard).getByText("Shopping")).toBeInTheDocument();
  });

  it("shows notable charges (EXPENSE over the threshold) separately from fees", async () => {
    mockApi.creditCardAnalytics.mockResolvedValue(makeAnalytics());
    renderPage();

    const filters = await screen.findByRole("group", { name: "Filter transactions" });
    fireEvent.click(within(filters).getByRole("button", { name: /Notable/ }));
    const table = screen.getByRole("table");
    expect(within(table).getByText("SIA")).toBeInTheDocument();
    expect(within(table).queryByText("DBS Annual Membership Fee")).not.toBeInTheDocument();
    // Purchases in cents, totals in whole units (#266).
    expect(within(table).getByText("S$ 12,640.00")).toBeInTheDocument();
  });

  it("shows recurring charges from the API response", async () => {
    mockApi.creditCardAnalytics.mockResolvedValue(
      makeAnalytics({
        transactions: [
          tx(),
          tx({ description: "NETFLIX.COM", merchant_counterparty: "Netflix", amount: -22, category: "Subscription", resolved_category: "Subscription" }),
          // Same merchant on another card: not that card's repeat.
          tx({ account_id: 2, card_name: "DBS Credit Card", description: "NETFLIX.COM", merchant_counterparty: "Netflix", amount: -22 }),
        ],
        recurring_payments: [
          { account_id: 1, account_name: "Amex Platinum", card_name: "Amex Platinum", issuer: "Amex", merchant_counterparty: "Netflix", months_present: 5, current_month_amount: 22, cadence: "monthly", typical_amount: 22 },
        ],
      }),
    );
    renderPage();
    const filters = await screen.findByRole("group", { name: "Filter transactions" });
    expect(within(filters).getByRole("button", { name: "Recurring 1" })).toBeInTheDocument();
    fireEvent.click(within(filters).getByRole("button", { name: /Recurring/ }));
    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(1);
    expect(within(rows[0]).getByText("Netflix")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Monthly · 5 months")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Amex Platinum")).toBeInTheDocument();
  });

  it("shows upcoming payments by due date only, with no dollar estimate", async () => {
    mockApi.creditCardAnalytics.mockResolvedValue(makeAnalytics());
    renderPage();

    const upcomingSection = (await screen.findByText("Upcoming payments")).closest("section") as HTMLElement;
    expect(within(upcomingSection).getByText("Amex Platinum")).toBeInTheDocument();
    expect(within(upcomingSection).getByText("DBS Credit Card")).toBeInTheDocument();
  });

  it("shows a no-loans banner when no LOAN accounts are linked", async () => {
    mockApi.creditCardAnalytics.mockResolvedValue(makeAnalytics());
    mockApi.accounts.mockResolvedValue(noLoans);
    renderPage();

    expect(await screen.findByText("No loans linked")).toBeInTheDocument();
    expect(screen.getByText("Connect a loan")).toBeDisabled();
    expect(screen.queryByText("Loans")).not.toBeInTheDocument();
  });

  it("shows a Loans section when a LOAN account is linked", async () => {
    mockApi.creditCardAnalytics.mockResolvedValue(makeAnalytics());
    mockApi.accounts.mockResolvedValue([
      ...noLoans,
      { id: 20, name: "Home Loan", platform: "OCBC", account_type: "LOAN", currency: "SGD" },
    ]);
    renderPage();

    expect(await screen.findByText("Loans")).toBeInTheDocument();
    expect(screen.getAllByText("Home Loan").length).toBeGreaterThan(0);
    expect(screen.queryByText("No loans linked")).not.toBeInTheDocument();

    const upcomingSection = screen.getByText("Upcoming payments").closest("section") as HTMLElement;
    expect(within(upcomingSection).getByText("Home Loan")).toBeInTheDocument();
  });

  it("shows available credit only when both value and as-of date are present", async () => {
    mockApi.creditCardAnalytics.mockResolvedValue(makeAnalytics());
    renderPage();
    await screen.findByText("S$ 53,192");

    expect(screen.getByText("S$ 59,739")).toBeInTheDocument();
    // #266: no filler when the issuer doesn't give it; one card has it, one doesn't.
    expect(screen.queryByText("Not provided by issuer")).not.toBeInTheDocument();
    expect(screen.getAllByText("Available credit")).toHaveLength(1);
  });

  it("never renders utilization, credit-limit progress, or a fabricated total-liabilities balance", async () => {
    mockApi.creditCardAnalytics.mockResolvedValue(makeAnalytics());
    const { container } = renderPage();
    await screen.findByText("S$ 53,192");

    expect(container.textContent).not.toMatch(/utilization/i);
    expect(container.textContent).not.toMatch(/0% of/i);
    expect(container.textContent).not.toMatch(/current due/i);
    expect(container.textContent).not.toMatch(/total liabilities/i);
  });

  it("renders the transaction ledger scoped to the current selection", async () => {
    mockApi.creditCardAnalytics.mockResolvedValue(makeAnalytics());
    renderPage();

    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
  });

  it("shows a loading state, then an error state with a working retry action", async () => {
    let resolveFn: (value: CreditCardAnalytics) => void;
    mockApi.creditCardAnalytics.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveFn = resolve;
        }),
    );
    renderPage();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    resolveFn!(makeAnalytics());
    await screen.findByText("S$ 53,192");

    mockApi.creditCardAnalytics.mockRejectedValueOnce(new Error("network down"));
    fireEvent.click(screen.getByRole("button", { name: /DBS Credit Card/ }));
    expect(await screen.findByText("network down")).toBeInTheDocument();

    mockApi.creditCardAnalytics.mockResolvedValueOnce(makeAnalytics({ account_id: 2, total_spend: 8202 }));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => {
      expect(document.querySelector(".coHeroValue")?.textContent).toBe("S$ 8,202");
    });
  });

  it("shows a no-cards empty state with a link to add an account", async () => {
    mockApi.creditCardAnalytics.mockResolvedValue(makeAnalytics({ cards: [] }));
    renderPage();

    expect(await screen.findByText("No credit cards linked yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add account" })).toHaveAttribute("href", "/add?what=card");
  });

  it("shows empty states for notable charges, recurring charges, and category breakdown", async () => {
    mockApi.creditCardAnalytics.mockResolvedValue(
      makeAnalytics({ transactions: [], charges: [], charge_total: 0, categories: [], recurring_payments: [] }),
    );
    renderPage();

    expect(await screen.findByText("No categorized spend this month.")).toBeInTheDocument();
    expect(screen.getByText("No transactions for this scope.")).toBeInTheDocument();
    const filters = screen.getByRole("group", { name: "Filter transactions" });
    expect(within(filters).getByRole("button", { name: "Recurring 0" })).toBeInTheDocument();
  });

  it("keeps month fixed when base currency changes", async () => {
    mockApi.creditCardAnalytics.mockResolvedValue(makeAnalytics());
    renderPage();
    await screen.findByText("S$ 53,192");

    fireEvent.change(screen.getByLabelText("Base currency"), { target: { value: "USD" } });

    await waitFor(() => {
      expect(mockApi.creditCardAnalytics).toHaveBeenCalledWith(expect.any(String), "USD", 12, null);
    });
    const monthCalls = mockApi.creditCardAnalytics.mock.calls.map((c) => c[0]);
    expect(new Set(monthCalls).size).toBe(1);
  });
});

// #148: month switches with out-of-order replies; the account list is fetched once.
describe("LiabilitiesOverview: one filtered list (#266)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.accounts.mockResolvedValue(noLoans);
  });

  it("replaces the Notable, Recurring and Fees sections with filters on one list", async () => {
    mockApi.creditCardAnalytics.mockResolvedValue(makeAnalytics());
    renderPage();
    const filters = await screen.findByRole("group", { name: "Filter transactions" });
    expect(screen.queryByText("Notable charges")).not.toBeInTheDocument();
    expect(screen.queryByText("Recurring charges")).not.toBeInTheDocument();
    expect(screen.queryByText("Fees & finance charges")).not.toBeInTheDocument();
    expect(within(filters).getByRole("button", { name: "All 2" })).toHaveAttribute("aria-pressed", "true");
    expect(within(filters).getByRole("button", { name: "Notable 1" })).toBeInTheDocument();
    expect(within(filters).getByRole("button", { name: "Fees & charges 1" })).toBeInTheDocument();
    expect(screen.getByText(/2 of 2 entries/)).toBeInTheDocument();
    fireEvent.click(within(filters).getByRole("button", { name: /Notable/ }));
    expect(screen.getByText(/1 of 2 entries/)).toBeInTheDocument();
  });
});

describe("LiabilitiesOverview races", () => {
  it("a slow earlier month never renders under the later month, and accounts load once", async () => {
    vi.clearAllMocks();
    window.localStorage.setItem("capitalos.selectedMonth", "2026-07");
    mockApi.accounts.mockResolvedValue(noLoans);
    const analytics = controlledCalls<CreditCardAnalytics>();
    mockApi.creditCardAnalytics.mockImplementation(analytics.impl as typeof api.creditCardAnalytics);
    renderPage();

    fireEvent.change(screen.getByLabelText("Month"), { target: { value: "2026-06" } });
    const july = analytics.find((a) => a[0] === "2026-07");
    const june = analytics.find((a) => a[0] === "2026-06");
    await act(async () => june.resolve(makeAnalytics({ month: "2026-06", total_spend: 11111 })));
    expect(await screen.findByText("S$ 11,111")).toBeInTheDocument();
    await act(async () => july.resolve(makeAnalytics({ month: "2026-07", total_spend: 99999 })));
    expect(screen.queryByText("S$ 99,999")).not.toBeInTheDocument();
    await waitFor(() => expect(july.signal?.aborted).toBe(true));
    expect(mockApi.accounts).toHaveBeenCalledTimes(1);
  });
});
