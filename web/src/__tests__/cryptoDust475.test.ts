// #475 (V12): the crypto dust threshold in the base currency. Synthetic numbers only.
import { describe, expect, it } from "vitest";

import { dustLabel, dustRule, isDust } from "../lib/cryptoDust";

describe("crypto dust rule (#475, V12)", () => {
  it("converts USD 10 at the page's own rate and rounds it", () => {
    const sgd = dustRule({ base_currency: "SGD", total_crypto_usd: 8400, total_crypto_base: 11200 });
    expect(sgd).toEqual({ currency: "SGD", amount: 10, field: "value_base" });
    expect(dustLabel(sgd)).toBe("S$ 10");
    expect(dustLabel(dustRule({ base_currency: "INR", total_crypto_usd: 1000, total_crypto_base: 83_700 }))).toBe("INR 800");
    expect(dustLabel(dustRule({ base_currency: "HKD", total_crypto_usd: 1000, total_crypto_base: 7_800 }))).toBe("HKD 80");
  });

  it("compares the base value: a holding just over S$ 10 is not dust though under USD 10", () => {
    const sgd = dustRule({ base_currency: "SGD", total_crypto_usd: 8400, total_crypto_base: 11200 });
    expect(isDust({ value_usd: 8, value_base: 10.6 }, sgd)).toBe(false);
    expect(isDust({ value_usd: 7, value_base: 9.4 }, sgd)).toBe(true);
  });

  it("stays USD 10 on the USD value for a USD page or without a rate", () => {
    const usdRule = { currency: "USD", amount: 10, field: "value_usd" };
    expect(dustRule({ base_currency: "USD", total_crypto_usd: 100, total_crypto_base: 100 })).toEqual(usdRule);
    expect(dustRule({ base_currency: "SGD", total_crypto_usd: 100, total_crypto_base: 0 })).toEqual(usdRule); // no FX rate
    expect(dustRule({ base_currency: "SGD", total_crypto_usd: 0, total_crypto_base: 0 })).toEqual(usdRule);
    expect(dustRule(null)).toEqual(usdRule);
  });
});
