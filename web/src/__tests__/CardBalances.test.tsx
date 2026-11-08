import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CardBalances from "../components/CardBalances";
import { api } from "../lib/api";
import type { CreditCardBalanceItem, CreditCardBalancePeriod, CreditCardBalances } from "../lib/api";
import { differenceReason, owedLabel } from "../lib/cardBalances";

vi.mock("../lib/api", () => ({
  api: {
    creditCardBalances: vi.fn(),
    setCreditCardBalance: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

function period(over: Partial<CreditCardBalancePeriod> = {}): CreditCardBalancePeriod {
  return {
    from_date: "2026-09-12", to_date: "2026-10-13", opening: 271.06, charges: 524.21, fees: 0, interest: 0,
    payments: 271.06, credits: 0, transaction_count: 9, expected: 524.21, printed: 524.21, difference: 0,
    flagged: false, paid_in_full: true, ...over,
  };
}

function card(over: Partial<CreditCardBalanceItem> = {}): CreditCardBalanceItem {
  return {
    account_id: 1, account_name: "Synthetic Card", card_name: "Synthetic Card", issuer: "UOB", currency: "SGD",
    method: "running", owed_now: 674.98, owed_now_base: 674.98, last_balance_date: "2026-10-13", last_balance: 524.21,
    last_balance_source: "statement_balance", paid_since: 524.21, charges_since: 674.98, paid_in_full: true,
    due_date: null, fees_interest_ytd: 0, last_transaction_date: "2026-11-06", flagged_count: 0,
    periods: [
      { ...period(), from_date: "2026-10-13", to_date: null, printed: null, difference: null },
      period(),
    ],
    ...over,
  };
}

function payload(cards: CreditCardBalanceItem[]): CreditCardBalances {
  return {
    base_currency: "SGD", as_of: "2026-11-07", total_owed_base: 0,
    flagged_count: cards.reduce((n, c) => n + c.flagged_count, 0), cards,
  };
}

describe("CardBalances (#300)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows what is owed, the statement it starts from, and that it was paid in full", async () => {
    mockApi.creditCardBalances.mockResolvedValue(payload([card()]));
    render(<CardBalances baseCurrency="SGD" />);
    expect(await screen.findByText("Owes S$ 674.98")).toBeInTheDocument();
    expect(screen.getByText(/Statement of 13 Oct 2026: S\$ 524\.21/)).toBeInTheDocument();
    expect(screen.getByText("That statement is paid in full")).toBeInTheDocument();
    expect(screen.getByText(/Statement checks: 1 of 1 add up/)).toBeInTheDocument();
  });

  it("flags a statement that doesn't add up, and says why", async () => {
    const bad = period({ printed: 300, difference: 28.94, flagged: true, expected: 271.06 });
    mockApi.creditCardBalances.mockResolvedValue(payload([card({ flagged_count: 1, periods: [card().periods[0], bad] })]));
    render(<CardBalances baseCurrency="SGD" />);
    expect(await screen.findByText(/1 statement doesn't add up/)).toHaveAttribute("role", "status");
    const checks = screen.getByText(/Statement checks: 0 of 1 add up · 1 to look at/).closest("details")!;
    expect(checks).toHaveAttribute("open");
    expect(within(checks).getByText(/S\$ 28\.94 more is owed than your transactions add up to/)).toBeInTheDocument();
  });

  it("says which payments came from the bank and why a gap is left (#308)", async () => {
    const shifted = period({ note: "Transactions dated 2026-08-30 are counted in the next period: the balance on that day didn't include them yet." });
    const gap = period({
      from_date: "2026-08-30", to_date: "2026-10-02", printed: 242.44, difference: 242.44, flagged: true, bank_payments: 592.41,
      note: "No card transactions after 2026-09-13: charges between then and 2026-10-02 aren't uploaded, so the balance is higher than the transactions add up to.",
    });
    mockApi.creditCardBalances.mockResolvedValue(
      payload([card({ flagged_count: 1, periods: [card().periods[0], gap, shifted] })]),
    );
    render(<CardBalances baseCurrency="SGD" />);
    const checks = (await screen.findByText(/Statement checks: 1 of 2 add up/)).closest("details")!;
    expect(within(checks).getByText(/No card transactions after 2026-09-13/)).toBeInTheDocument();
    expect(within(checks).getByText(/Includes S\$ 592\.41 paid from your bank account/)).toBeInTheDocument();
    expect(within(checks).getByText(/counted in the next period/)).toBeInTheDocument();
  });

  it("shows a credit for an overpaid card", () => {
    expect(owedLabel({ owed_now: -150, currency: "SGD" })).toBe("In credit S$ 150.00");
  });

  it("calls a period with no transactions a missing statement", () => {
    const reason = differenceReason(period({ transaction_count: 0, flagged: true, difference: -170.88 }), "SGD");
    expect(reason).toMatch(/No transactions between these dates/);
    expect(differenceReason(period(), "SGD")).toBeNull();
  });

  it("lets a card with no statement balance get one typed in", async () => {
    const estimate = card({ method: "transactions", last_balance_date: null, last_balance: null, periods: [], paid_in_full: null });
    mockApi.creditCardBalances.mockResolvedValueOnce(payload([estimate])).mockResolvedValue(payload([card()]));
    mockApi.setCreditCardBalance.mockResolvedValue(payload([card()]));
    render(<CardBalances baseCurrency="SGD" />);
    expect(await screen.findByText(/No statement balance on file/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Statement date"), { target: { value: "2026-10-13" } });
    fireEvent.change(screen.getByLabelText("Amount owed (SGD)"), { target: { value: "524.21" } });
    fireEvent.click(screen.getByRole("button", { name: "Save balance" }));
    await waitFor(() =>
      expect(mockApi.setCreditCardBalance).toHaveBeenCalledWith(1, { as_of_date: "2026-10-13", owed: 524.21 }, "SGD"),
    );
    expect(await screen.findByText("Owes S$ 674.98")).toBeInTheDocument();
  });
});
