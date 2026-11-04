import { describe, expect, it } from "vitest";

import {
  CURRENCY_OPTIONS,
  currencyPrefix,
  currentMonth,
  directionClass,
  formatDate,
  formatDateTime,
  formatDelta,
  formatMoney,
  formatMoneyCompact,
  formatMonth,
  formatNumber,
  formatPercent,
  formatSignedMoney,
  isBaseCurrency,
} from "../lib/format";

describe("formatMoney", () => {
  it("prefixes S$ for SGD and the ISO code for every other currency, with one space", () => {
    expect(formatMoney(1234, "SGD")).toBe("S$ 1,234");
    expect(formatMoney(1234, "USD")).toBe("USD 1,234");
    expect(formatMoney(1234, "HKD")).toBe("HKD 1,234");
    expect(formatMoney(1234, "INR")).toBe("INR 1,234");
    expect(formatMoney(1234, "usd")).toBe("USD 1,234");
    for (const ccy of CURRENCY_OPTIONS) {
      expect(formatMoney(1, ccy)).toMatch(/^\S+ 1$/);
    }
  });

  it("puts the sign before the prefix", () => {
    expect(formatMoney(-1234, "SGD")).toBe("-S$ 1,234");
    expect(formatMoney(-1234, "USD")).toBe("-USD 1,234");
  });

  it("shows zero without a sign, including values that round to zero", () => {
    expect(formatMoney(0, "SGD")).toBe("S$ 0");
    expect(formatMoney(-0.4, "SGD")).toBe("S$ 0");
    expect(formatSignedMoney(0, "SGD")).toBe("S$ 0");
  });

  it("returns a dash for missing values, never zero", () => {
    expect(formatMoney(null, "SGD")).toBe("—");
    expect(formatMoney(undefined, "SGD")).toBe("—");
    expect(formatMoney(Number.NaN, "SGD")).toBe("—");
  });

  it("rounds to whole units by default and fixes decimals when asked", () => {
    expect(formatMoney(1234.56, "SGD")).toBe("S$ 1,235");
    expect(formatMoney(53512.9, "SGD", { decimals: 2 })).toBe("S$ 53,512.90");
    expect(formatMoney(11163859.85, "SGD", { decimals: 2 })).toBe("S$ 11,163,859.85");
  });

  it("does not depend on the browser locale", () => {
    expect(formatMoney(1234567, "SGD")).toBe("S$ 1,234,567");
  });

  it("signed money", () => {
    expect(formatSignedMoney(1234, "SGD")).toBe("+S$ 1,234");
    expect(formatSignedMoney(-1234, "SGD")).toBe("-S$ 1,234");
    expect(formatSignedMoney(null, "SGD")).toBe("—");
  });

  it("works without a currency", () => {
    expect(formatMoney(12, null)).toBe("12");
    expect(currencyPrefix(undefined)).toBe("");
  });
});

describe("formatMoneyCompact", () => {
  it("compacts thousands and millions", () => {
    expect(formatMoneyCompact(35000, "SGD")).toBe("S$ 35K");
    expect(formatMoneyCompact(1234567, "SGD")).toBe("S$ 1.2M");
    expect(formatMoneyCompact(11170000, "USD")).toBe("USD 11.2M");
    expect(formatMoneyCompact(950, "HKD")).toBe("HKD 950");
  });
  it("negative, zero, signed and missing", () => {
    expect(formatMoneyCompact(-35000, "SGD")).toBe("-S$ 35K");
    expect(formatMoneyCompact(0, "SGD")).toBe("S$ 0");
    expect(formatMoneyCompact(35000, "SGD", { signed: true })).toBe("+S$ 35K");
    expect(formatMoneyCompact(null, "SGD")).toBe("—");
  });
});

describe("formatPercent", () => {
  it("formats fractions by default, points on request", () => {
    expect(formatPercent(0.123)).toBe("12.3%");
    expect(formatPercent(62.5, { scale: "points" })).toBe("62.5%");
    expect(formatPercent(0.5, { decimals: 0 })).toBe("50%");
  });
  it("signs, zero and missing", () => {
    expect(formatPercent(0.031, { signed: true })).toBe("+3.1%");
    expect(formatPercent(-0.04, { signed: true })).toBe("-4.0%");
    expect(formatPercent(-0.04)).toBe("-4.0%");
    expect(formatPercent(0, { signed: true })).toBe("0.0%");
    expect(formatPercent(-0.0001, { signed: true })).toBe("0.0%");
    expect(formatPercent(null)).toBe("—");
  });
});

describe("formatDelta", () => {
  it("prints both signs the same way (the #130 7.4 mismatch)", () => {
    expect(formatDelta(-1234, -0.05, "SGD")).toBe("-S$ 1,234 (-5.0%)");
    expect(formatDelta(1234, 0.05, "SGD")).toBe("+S$ 1,234 (+5.0%)");
    expect(formatDelta(1234, null, "USD")).toBe("+USD 1,234");
    expect(formatDelta(0, 0, "SGD")).toBe("S$ 0 (0.0%)");
    expect(formatDelta(null, 0.1, "SGD")).toBe("—");
  });
});

describe("directionClass", () => {
  it("one rule for up/down colour", () => {
    expect(directionClass(5)).toBe("good");
    expect(directionClass(-5)).toBe("bad");
    expect(directionClass(0)).toBe("");
    expect(directionClass(null)).toBe("");
  });
});

describe("formatNumber", () => {
  it("formats plain numbers", () => {
    expect(formatNumber(250000)).toBe("250,000");
    expect(formatNumber(0.123456, 4)).toBe("0.1235");
    expect(formatNumber(-3)).toBe("-3");
    expect(formatNumber(undefined)).toBe("—");
  });
});

describe("months and dates", () => {
  it("formats YYYY-MM months", () => {
    expect(formatMonth("2026-09")).toBe("September 2026");
    expect(formatMonth("2026-09", "medium")).toBe("Sep 2026");
    expect(formatMonth("2026-09", "short")).toBe("Sep '26");
    expect(formatMonth("not-a-month")).toBe("not-a-month");
    expect(formatMonth(null)).toBe("—");
  });

  it("formats dates as day month year, never a raw ISO string", () => {
    expect(formatDate("2026-11-04")).toBe("4 Nov 2026");
    expect(formatDate("2026-09-04")).toBe("4 Sep 2026");
    expect(formatDate("2026-10-06T00:00:00")).toBe("6 Oct 2026");
    expect(formatDate("garbage")).toBe("—");
    expect(formatDate(null)).toBe("—");
  });

  it("formats date-times with a 24-hour local time", () => {
    const local = new Date(2026, 9, 29, 11, 50, 12).toISOString();
    expect(formatDateTime(local)).toBe("29 Oct 2026, 11:50");
    expect(formatDateTime(undefined)).toBe("—");
  });

  it("current month", () => {
    expect(currentMonth(new Date(2026, 0, 15))).toBe("2026-01");
  });

  it("currency list", () => {
    expect(isBaseCurrency("HKD")).toBe(true);
    expect(isBaseCurrency("EUR")).toBe(false);
    expect(isBaseCurrency(null)).toBe(false);
  });
});

describe("formatEnumLabel", () => {
  it("humanises API enums", async () => {
    const { formatEnumLabel } = await import("../lib/format");
    expect(formatEnumLabel("EXPENSE")).toBe("Expense");
    expect(formatEnumLabel("CARD_ISSUER")).toBe("Card issuer");
    expect(formatEnumLabel("")).toBe("—");
    expect(formatEnumLabel(null)).toBe("—");
  });
});
