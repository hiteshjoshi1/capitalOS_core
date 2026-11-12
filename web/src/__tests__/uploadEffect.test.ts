import { describe, expect, it } from "vitest";
import { uploadEffectLine } from "../lib/uploadEffect";

describe("uploadEffectLine (#410, U28)", () => {
  const base = {
    month: "2026-10",
    live: false,
    base_currency: "SGD",
    balance: 12300,
    balance_date: "2026-10-31",
    net_worth_before: 100000,
    net_worth_after: 101250,
    net_worth_change: 1250,
  };

  it("names the balance and the month's change", () => {
    expect(uploadEffectLine(base)).toBe(
      "Balance S$ 12,300 on 31 Oct · net worth for Oct 2026 +S$ 1,250 (S$ 100,000 → S$ 101,250)",
    );
  });

  it("says so when nothing changed, and 'so far' for the open month", () => {
    expect(uploadEffectLine({ ...base, live: true, net_worth_change: 0, net_worth_after: 100000 })).toBe(
      "Balance S$ 12,300 on 31 Oct · net worth for Oct 2026 so far unchanged",
    );
  });

  it("works without a balance (a card or holdings file)", () => {
    expect(uploadEffectLine({ ...base, balance: null, balance_date: null, net_worth_change: -40, net_worth_after: 99960 })).toBe(
      "Net worth for Oct 2026 -S$ 40 (S$ 100,000 → S$ 99,960)",
    );
  });
});
