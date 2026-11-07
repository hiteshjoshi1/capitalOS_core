import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Delta from "../components/Delta";
import { deltaDirection, deltaPercent, missingBaselineReason, noDataFor, noRateFor } from "../lib/delta";
import { hasLivePrice, holdingPriceAge, priceBasis, priceSourceLabel } from "../lib/priceAge";

// #224: one <Delta> for every change (UX review #131, "Honest comparisons").

function deltaEl(container: HTMLElement): HTMLElement {
  const el = container.querySelector(".delta");
  if (!el) throw new Error("no .delta rendered");
  return el as HTMLElement;
}

describe("<Delta>", () => {
  it("says there is no comparison when the baseline is missing, never a number", () => {
    const { container } = render(
      <Delta abs={11_200_000} pct={null} currency="SGD" missingReason={noDataFor("2025-11")} />,
    );
    expect(screen.getByText("no comparison: no data for Nov 2025")).toBeInTheDocument();
    expect(deltaEl(container)).toHaveClass("delta--missing");
    expect(container).not.toHaveTextContent("11,200,000");
    expect(container).not.toHaveTextContent("▲");
  });

  it("computes the % from the baseline in the same currency as the amount", () => {
    // A holding down S$ 13,764 from S$ 444,000 is -3.1%, whatever its USD % was (#131).
    const { container } = render(<Delta abs={-13_764} pct={0.031} compareValue={444_000} currency="SGD" />);
    expect(deltaEl(container)).toHaveTextContent("▼-S$ 13,764 (-3.1%)");
  });

  it("uses ▲ and the up colour for a rise, ▼ and the down colour for a fall", () => {
    const up = render(<Delta abs={1234} pct={0.031} currency="SGD" />);
    expect(deltaEl(up.container)).toHaveClass("delta", "delta--up");
    expect(deltaEl(up.container)).toHaveAttribute("data-direction", "up");
    expect(deltaEl(up.container)).toHaveTextContent("▲+S$ 1,234 (+3.1%)");
    up.unmount();

    const down = render(<Delta abs={-50} pct={-0.004} currency="USD" />);
    expect(deltaEl(down.container)).toHaveClass("delta--down");
    expect(deltaEl(down.container)).toHaveTextContent("▼-USD 50.00 (-0.4%)");
  });

  it("shows no arrow and a neutral colour for no change", () => {
    const { container } = render(<Delta abs={0} pct={0} currency="SGD" />);
    expect(deltaEl(container)).toHaveClass("delta--flat");
    expect(container).not.toHaveTextContent(/[▲▼]/);
  });

  it("shows — for a missing amount", () => {
    const { container } = render(<Delta abs={null} currency="SGD" />);
    expect(deltaEl(container)).toHaveTextContent("—");
    expect(deltaEl(container)).toHaveClass("delta--missing");
  });

  it("inverse tone keeps the arrow and flips the colour (spending: up is bad)", () => {
    const { container } = render(<Delta abs={120} currency="SGD" show="abs" tone="inverse" baseline="vs Oct" />);
    expect(deltaEl(container)).toHaveClass("delta--down");
    expect(deltaEl(container)).toHaveTextContent("▲+S$ 120.00vs Oct");
  });

  it("pct mode falls back to the amount when there is no %", () => {
    const { container } = render(<Delta abs={500} compareValue={0} currency="SGD" show="pct" variant="chip" />);
    expect(deltaEl(container)).toHaveClass("deltaChip");
    expect(deltaEl(container)).toHaveTextContent("▲+S$ 500");
  });

  it("one up/down colour pair, defined for both themes", () => {
    const css = readFileSync(resolve(__dirname, "..", "App.css"), "utf8");
    const darkRoot = css.slice(css.indexOf(":root {"), css.indexOf("}", css.indexOf(":root {")));
    const lightRoot = css.slice(css.indexOf('[data-theme="light"] {'), css.indexOf("}", css.indexOf('[data-theme="light"] {')));
    for (const block of [darkRoot, lightRoot]) {
      expect(block).toContain("--delta-up: var(--good)");
      expect(block).toContain("--delta-down: var(--bad)");
    }
    expect(css).toMatch(/\.delta--up \{\s*color: var\(--delta-up\);/);
    expect(css).toMatch(/\.delta--down \{\s*color: var\(--delta-down\);/);
  });

  it("the pages it covers carry no delta colouring of their own", () => {
    const pages = ["WealthOverview", "StockHoldings", "CryptoHoldings", "CashOverview"];
    for (const page of pages) {
      const source = readFileSync(resolve(__dirname, "..", "routes", `${page}.tsx`), "utf8");
      expect(source, page).not.toMatch(/coChipPositive|coChipNegative|wealthTrendPositive|wealthTrendNegative|formatDelta\(/);
    }
  });
});

describe("lib/delta", () => {
  it("direction and percent", () => {
    expect(deltaDirection(3)).toBe("up");
    expect(deltaDirection(-3)).toBe("down");
    expect(deltaDirection(0)).toBe("flat");
    expect(deltaDirection(null)).toBe("flat");
    expect(deltaPercent(50, 200)).toBe(0.25);
    expect(deltaPercent(50, 0)).toBeNull();
    expect(deltaPercent(50, -10)).toBeNull();
    expect(deltaPercent(null, 10)).toBeNull();
  });

  it("missing-baseline sentences", () => {
    expect(noDataFor("2026-10")).toBe("no data for Oct 2026");
    expect(noDataFor("2026-10-06")).toBe("no data for 6 Oct 2026");
    expect(noDataFor(null)).toBe("no data for the comparison period");
    expect(noRateFor("2026-10")).toBe("no exchange rate for Oct 2026");
    expect(missingBaselineReason({ baseline_missing: true, compare_month: "2025-05" })).toBe("no data for May 2025");
    // A zero baseline alone is not "missing": only the backend's flag says so.
    expect(missingBaselineReason({ baseline_missing: false, compare_month: "2025-05" })).toBeNull();
    expect(missingBaselineReason({ compare_month: "2025-05" })).toBeNull();
    expect(missingBaselineReason(null)).toBeNull();
  });
});

describe("lib/priceAge", () => {
  const quote = {
    platform: "IBKR",
    latest_trade_date: "2026-11-05",
    price_source: "yfinance_market",
    price_provider: "yfinance",
    price_basis: "quote" as const,
    quote_freshness_status: "fresh",
  };
  const upload = {
    platform: "SHAREKHAN",
    latest_trade_date: "2026-07-31",
    price_source: "canonical_snapshot",
    price_provider: "canonical",
    price_basis: "statement" as const,
    quote_freshness_status: "stale",
  };

  it("names the source: the price job's provider or the platform's statement", () => {
    expect(priceSourceLabel(quote)).toBe("Yahoo Finance");
    expect(priceSourceLabel(upload)).toBe("SHAREKHAN statement");
    expect(priceSourceLabel({ ...upload, platform: "DBS_VICKERS" })).toBe("DBS Vickers statement");
    // Older API without price_basis: inferred from the source.
    expect(priceBasis({ price_source: "ibkr_flex" })).toBe("statement");
    expect(priceBasis({ price_source: "finnhub_market" })).toBe("quote");
    expect(priceBasis({})).toBeNull();
  });

  it("marks a price older than the stale window as stale, on the live month only", () => {
    expect(holdingPriceAge(quote, true)).toEqual({ stale: false, text: "price from 5 Nov 2026, Yahoo Finance" });
    expect(holdingPriceAge(upload, true)).toEqual({
      stale: true,
      text: "stale (price from 31 Jul 2026, SHAREKHAN statement)",
    });
    expect(holdingPriceAge(upload, false)).toEqual({ stale: false, text: "price from 31 Jul 2026, SHAREKHAN statement" });
  });

  it("a live price is a fresh quote; a fresh statement price is not live", () => {
    expect(hasLivePrice(quote)).toBe(true);
    expect(hasLivePrice(upload)).toBe(false);
    expect(hasLivePrice({ ...upload, quote_freshness_status: "fresh" })).toBe(false);
    expect(hasLivePrice({ ...quote, quote_freshness_status: "stale" })).toBe(false);
  });
});
