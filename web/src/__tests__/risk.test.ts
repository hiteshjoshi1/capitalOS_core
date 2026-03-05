import { describe, expect, it } from "vitest";

import {
  computeLargestPositionRisk,
  computeTop5ConcentrationRisk,
  formatLargestPosition,
  formatRiskPercent,
} from "../lib/risk";
import type { DashboardSummary } from "../lib/api";

type Holding = DashboardSummary["top_holdings"][number];

function holding(symbol: string, value: number): Holding {
  return {
    asset_id: value,
    symbol,
    asset_class: "STOCK",
    value,
    percent_of_networth: 0,
  };
}

describe("risk helpers", () => {
  it("computes largest position and top-5 concentration for populated holdings", () => {
    const holdings = [
      holding("AAPL", 120),
      holding("MSFT", 95),
      holding("NVDA", 90),
      holding("AMZN", 80),
      holding("GOOG", 70),
      holding("TSLA", 45),
    ];

    const largest = computeLargestPositionRisk(holdings, 700);
    expect(largest.hasData).toBe(true);
    expect(largest.symbol).toBe("AAPL");
    expect(largest.percent).toBeCloseTo(17.1428, 3);
    expect(formatLargestPosition(largest)).toBe("AAPL — 17.1%");

    const top5 = computeTop5ConcentrationRisk(holdings, 700);
    expect(top5.hasData).toBe(true);
    expect(top5.percent).toBeCloseTo(65.0, 4);
    expect(formatRiskPercent(top5.percent)).toBe("65.0%");
  });

  it("returns no-data state for empty holdings", () => {
    const largest = computeLargestPositionRisk([], 1000);
    expect(largest.hasData).toBe(false);
    expect(largest.symbol).toBeNull();
    expect(largest.percent).toBe(0);
    expect(formatLargestPosition(largest)).toBe("—");

    const top5 = computeTop5ConcentrationRisk([], 1000);
    expect(top5.hasData).toBe(false);
    expect(top5.percent).toBe(0);
    expect(formatRiskPercent(top5.percent)).toBe("0.0%");
  });

  it("guards against zero net worth", () => {
    const holdings = [holding("AAPL", 100)];

    const largest = computeLargestPositionRisk(holdings, 0);
    expect(largest.hasData).toBe(false);
    expect(largest.percent).toBe(0);

    const top5 = computeTop5ConcentrationRisk(holdings, 0);
    expect(top5.hasData).toBe(false);
    expect(top5.percent).toBe(0);
  });

  it("treats fewer than five holdings as insufficient top-5 data", () => {
    const holdings = [holding("AAPL", 100), holding("MSFT", 80), holding("NVDA", 60), holding("AMZN", 40)];
    const top5 = computeTop5ConcentrationRisk(holdings, 500);

    expect(top5.hasData).toBe(false);
    expect(top5.percent).toBe(0);
    expect(formatRiskPercent(top5.percent)).toBe("0.0%");
  });
});
