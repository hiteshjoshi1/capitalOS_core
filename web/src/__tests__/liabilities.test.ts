import { describe, expect, it } from "vitest";

import type { CreditCardRecurringPayment, CreditCardTransaction } from "../lib/api";
import { formatMoney } from "../lib/format";
import { filterCounts, filterTransactions, isNotable, recurringFor, recurringIndex } from "../lib/liabilities";

function tx(overrides: Partial<CreditCardTransaction> = {}): CreditCardTransaction {
  return {
    account_id: 1,
    account_name: "Synthetic Card",
    card_name: "Synthetic Card",
    issuer: "Bank",
    ts: "2026-07-08T00:00:00+00:00",
    description: "SHOP",
    amount: -20,
    type: "EXPENSE",
    category: "Shopping",
    resolved_category: "Shopping",
    category_source: "parser",
    merchant_counterparty: "Shop",
    notes: null,
    ...overrides,
  };
}

const streamly: CreditCardRecurringPayment = {
  account_id: 1,
  account_name: "Synthetic Card",
  card_name: "Synthetic Card",
  issuer: "Bank",
  merchant_counterparty: "Streamly",
  months_present: 4,
  current_month_amount: 18,
  cadence: "monthly",
  typical_amount: 18,
};

const rows = [
  tx({ ts: "2026-07-03T00:00:00+00:00", merchant_counterparty: " streamly ", amount: -18 }),
  tx({ ts: "2026-07-10T00:00:00+00:00", merchant_counterparty: "Airline", amount: -900 }),
  tx({ ts: "2026-07-12T00:00:00+00:00", merchant_counterparty: "Cafe", amount: -50 }),
  tx({ ts: "2026-07-15T00:00:00+00:00", description: "ANNUAL FEE", merchant_counterparty: null, amount: -196.2, type: "FEE" }),
  tx({ ts: "2026-07-20T00:00:00+00:00", account_id: 2, merchant_counterparty: "Streamly", amount: -18 }),
  tx({ ts: "2026-07-25T00:00:00+00:00", merchant_counterparty: "Hotel", amount: -300 }),
];

describe("liabilities transaction filters (#266)", () => {
  const index = recurringIndex([streamly]);

  it("matches a repeat by card and merchant (trimmed, any case), purchases only", () => {
    expect(recurringFor(rows[0], index)).toBe(streamly);
    expect(recurringFor(rows[4], index)).toBeNull(); // same merchant, other card
    expect(recurringFor(tx({ merchant_counterparty: "Streamly", type: "FEE" }), index)).toBeNull();
    expect(recurringFor(tx({ merchant_counterparty: null }), index)).toBeNull();
  });

  it("notable means a purchase over S$ 50, never a fee", () => {
    expect(isNotable(rows[1])).toBe(true);
    expect(isNotable(rows[2])).toBe(false); // exactly 50
    expect(isNotable(rows[3])).toBe(false); // the fee
  });

  it("counts each filter", () => {
    expect(filterCounts(rows, index)).toEqual({ all: 6, notable: 2, recurring: 1, charges: 1 });
  });

  it("lists newest first, and Notable biggest first", () => {
    expect(filterTransactions(rows, "all", index).map((t) => t.ts.slice(8, 10))).toEqual(["25", "20", "15", "12", "10", "03"]);
    expect(filterTransactions(rows, "notable", index).map((t) => t.amount)).toEqual([-900, -300]);
    expect(filterTransactions(rows, "charges", index).map((t) => t.description)).toEqual(["ANNUAL FEE"]);
    expect(filterTransactions(rows, "recurring", index)).toEqual([rows[0]]);
  });

  it("rounds with the one formatter: totals whole, single charges to the cent", () => {
    expect(formatMoney(53512.94, "SGD", { decimals: 0 })).toBe("S$ 53,513");
    expect(formatMoney(3127.25, "SGD", { decimals: 0 })).toBe("S$ 3,127");
    expect(formatMoney(196.2, "SGD", { decimals: 2 })).toBe("S$ 196.20");
  });
});
