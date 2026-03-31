import { describe, expect, it } from "vitest";

import {
  buildTopNDistribution,
  computeLargestPositionRisk,
  computeTopNConcentrationRisk,
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
  it("computes largest position and top-3/top-5 concentration", () => {
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

    const top3 = computeTopNConcentrationRisk(holdings, 700, 3);
    expect(top3.hasData).toBe(true);
    expect(top3.hasFullSelection).toBe(true);
    expect(top3.percent).toBeCloseTo(43.5714, 3);

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

    const top5 = computeTopNConcentrationRisk([], 1000, 5);
    expect(top5.hasData).toBe(false);
    expect(top5.percent).toBe(0);
    expect(formatRiskPercent(top5.percent)).toBe("0.0%");
  });

  it("guards against zero or negative net worth", () => {
    const holdings = [holding("AAPL", 100)];

    const largest = computeLargestPositionRisk(holdings, 0);
    expect(largest.hasData).toBe(false);
    expect(largest.percent).toBe(0);

    const top5 = computeTopNConcentrationRisk(holdings, 0, 5);
    expect(top5.hasData).toBe(false);
    expect(top5.percent).toBe(0);

    const top3Negative = computeTopNConcentrationRisk(holdings, -1, 3);
    expect(top3Negative.hasData).toBe(false);
    expect(top3Negative.percent).toBe(0);
  });

  it("handles fewer-than-N holdings by using available rows", () => {
    const holdings = [holding("AAPL", 100), holding("MSFT", 80), holding("NVDA", 60), holding("AMZN", 40)];
    const top5 = computeTopNConcentrationRisk(holdings, 500, 5);

    expect(top5.hasData).toBe(true);
    expect(top5.hasFullSelection).toBe(false);
    expect(top5.availableCount).toBe(4);
    expect(top5.percent).toBeCloseTo(56.0, 4);
    expect(formatRiskPercent(top5.percent)).toBe("56.0%");
  });

  it("sorts ties deterministically by symbol asc", () => {
    const holdings = [
      holding("TSLA", 100),
      holding("AAPL", 100),
      holding("MSFT", 100),
    ];
    const distribution = buildTopNDistribution(holdings, 1000, 3);

    expect(distribution.map((item) => item.symbol)).toEqual(["AAPL", "MSFT", "TSLA"]);
  });

  it("excludes CASH holdings from concentration and distribution", () => {
    const cashHolding: Holding = {
      asset_id: 100,
      symbol: "CASH",
      asset_class: "CASH",
      value: 200,
      percent_of_networth: 0,
    };
    const holdings = [holding("AAPL", 100), cashHolding, holding("MSFT", 50)];

    const top3 = computeTopNConcentrationRisk(holdings, 500, 3);
    expect(top3.hasData).toBe(true);
    // CASH should be excluded, so only AAPL (100) + MSFT (50) = 150
    expect(top3.percent).toBeCloseTo(30.0, 4);

    const distribution = buildTopNDistribution(holdings, 500, 3);
    // CASH should not appear in distribution
    expect(distribution.length).toBe(2);
    expect(distribution[0].symbol).toBe("AAPL");
    expect(distribution[0].assetClass).toBe("STOCK");
    expect(distribution[1].symbol).toBe("MSFT");
    expect(distribution[1].assetClass).toBe("STOCK");
  });

  it("excludes CRYPTO holdings from concentration and distribution", () => {
    const cryptoHolding: Holding = {
      asset_id: 101,
      symbol: "ETH",
      asset_class: "CRYPTO",
      value: 300,
      percent_of_networth: 0,
    };
    const holdings = [holding("AAPL", 120), cryptoHolding, holding("MSFT", 80)];

    const top3 = computeTopNConcentrationRisk(holdings, 1000, 3);
    expect(top3.hasData).toBe(true);
    // CRYPTO should be excluded, so only AAPL + MSFT = 200
    expect(top3.percent).toBeCloseTo(20.0, 4);

    const distribution = buildTopNDistribution(holdings, 1000, 3);
    expect(distribution.length).toBe(2);
    expect(distribution.map((item) => item.symbol)).toEqual(["AAPL", "MSFT"]);
  });
});
