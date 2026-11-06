import { describe, expect, it } from "vitest";

import { priceFallbackMessage } from "../lib/priceFallback";

describe("priceFallbackMessage (D-21 for every holding, #144)", () => {
  it("names the platform whose statement priced the holding", () => {
    expect(priceFallbackMessage("RELIANCE", "quote_older", "2026-03-15", "SHAREKHAN")).toBe(
      "Stale price for RELIANCE: taken from SHAREKHAN's statement of 15 Mar 2026, because the price job's latest quote is older than the statement.",
    );
  });

  it("defaults to IBKR when no platform is given", () => {
    expect(priceFallbackMessage("700", "no_quote", "2026-10-30")).toBe(
      "Stale price for 700: taken from IBKR's statement of 30 Oct 2026, because the price job couldn't fetch a quote for it.",
    );
  });
});
