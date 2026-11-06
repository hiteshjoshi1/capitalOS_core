import { describe, expect, it } from "vitest";

import {
  buildCurrencyExposureRows,
  buildTopNDistribution,
  computeLargestPositionRisk,
  computePlatformConcentrationRisk,
  computeTopNConcentrationRisk,
  concentrationState,
  DEFAULT_RISK_THRESHOLDS,
  formatLargestPosition,
  formatRiskPercent,
  resolveRiskThresholds,
  riskStateClassName,
  thresholdRule,
} from "../lib/risk";
import type { RiskHolding } from "../lib/api";

function holding(symbol: string, value: number, assetClass = "STOCK", percent?: number): RiskHolding {
  return {
    asset_id: value,
    symbol,
    asset_class: assetClass,
    value,
    // As the server sends it when given; else the helpers divide by the total.
    percent_of_networth: percent as number,
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
    expect(largest.value).toBe(120);
    expect(largest.percent).toBeCloseTo(17.1428, 3);
    expect(formatLargestPosition(largest)).toBe("AAPL — 17.1%");

    const top3 = computeTopNConcentrationRisk(holdings, 700, 3);
    expect(top3.hasData).toBe(true);
    expect(top3.hasFullSelection).toBe(true);
    expect(top3.percent).toBeCloseTo(43.5714, 3);

    const top5 = computeTopNConcentrationRisk(holdings, 700, 5);
    expect(top5.hasData).toBe(true);
    expect(top5.percent).toBeCloseTo(65.0, 4);
    expect(formatRiskPercent(top5.percent)).toBe("65.0%");
  });

  it("returns no-data state for empty holdings", () => {
    const largest = computeLargestPositionRisk([], 1000);
    expect(largest.hasData).toBe(false);
    expect(largest.symbol).toBeNull();
    expect(largest.percent).toBe(0);
    expect(largest.state).toBe("muted");
    expect(formatLargestPosition(largest)).toBe("—");

    const top5 = computeTopNConcentrationRisk([], 1000, 5);
    expect(top5.hasData).toBe(false);
    expect(top5.percent).toBe(0);
    expect(top5.state).toBe("muted");
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

  it("keeps the server's order for ties, as Overview does", () => {
    const holdings = [holding("TSLA", 100), holding("AAPL", 100), holding("MSFT", 100)];
    const distribution = buildTopNDistribution(holdings, 1000, 3);
    expect(distribution.map((item) => item.symbol)).toEqual(["TSLA", "AAPL", "MSFT"]);
  });

  // #253: the same set as Overview's largest holdings, every asset class.
  it("counts crypto positions in the largest position and the top N", () => {
    const holdings = [holding("AAPL", 120), holding("ETH", 300, "CRYPTO"), holding("MSFT", 80)];

    const largest = computeLargestPositionRisk(holdings, 1000);
    expect(largest.symbol).toBe("ETH");
    expect(largest.assetClass).toBe("CRYPTO");
    expect(largest.percent).toBeCloseTo(30.0, 4);

    const top3 = computeTopNConcentrationRisk(holdings, 1000, 3);
    expect(top3.percent).toBeCloseTo(50.0, 4);

    const distribution = buildTopNDistribution(holdings, 1000, 3);
    expect(distribution.map((item) => [item.symbol, item.assetClass])).toEqual([
      ["ETH", "CRYPTO"],
      ["AAPL", "STOCK"],
      ["MSFT", "STOCK"],
    ]);
  });

  it("shows the server's percent_of_networth for a row, the figure Overview shows", () => {
    // 56.49 / 1000 would round to 5.6%; the server's 5.65 shows as Overview shows it.
    const holdings = [holding("ETH", 56.49, "CRYPTO", 5.65)];
    const largest = computeLargestPositionRisk(holdings, 1000);
    expect(largest.percent).toBe(5.65);
    expect(buildTopNDistribution(holdings, 1000, 3)[0].percent).toBe(5.65);
  });

  it("only an upper threshold warns: low concentration is never flagged", () => {
    const holdings = [holding("AAPL", 10), holding("MSFT", 10), holding("NVDA", 10)];
    // 30% over three positions: below the default 50% for the top N, and 10% each below 15%.
    const top3 = computeTopNConcentrationRisk(holdings, 100, 3);
    expect(top3.state).toBe("ok");
    expect(riskStateClassName(top3.state)).toBe("");
    expect(computeLargestPositionRisk(holdings, 100).state).toBe("ok");

    const concentrated = computeTopNConcentrationRisk([holding("AAPL", 60)], 100, 3);
    expect(concentrated.state).toBe("warn");
    expect(riskStateClassName(concentrated.state)).toBe("warn");

    // At the threshold is not above it.
    expect(concentrationState(15, 15)).toBe("ok");
    expect(concentrationState(15.01, 15)).toBe("warn");
    // A user's own threshold.
    expect(computeLargestPositionRisk([holding("AAPL", 12)], 100, 10).state).toBe("warn");
    expect(computeTopNConcentrationRisk([holding("AAPL", 40)], 100, 3, 35).state).toBe("warn");
  });

  it("resolves the user's thresholds over the defaults", () => {
    expect(resolveRiskThresholds(undefined)).toEqual(DEFAULT_RISK_THRESHOLDS);
    expect(
      resolveRiskThresholds({ largest_position_warn_pct: 20, top_n_warn_pct: null, platform_warn_pct: 65.5 }),
    ).toEqual({ largestPositionWarnPct: 20, topNWarnPct: DEFAULT_RISK_THRESHOLDS.topNWarnPct, platformWarnPct: 65.5 });
    expect(thresholdRule(15)).toBe("Above 15%: concentrated");
    expect(thresholdRule(12.5)).toBe("Above 12.5%: concentrated");
  });

  it("finds the largest platform and flags it only above its threshold", () => {
    const platforms = {
      total: 1000,
      items: [
        { platform: "DBS", platform_type: "BANK", country: "SG", value: 300, percent: 30 },
        { platform: "IBKR", platform_type: "BROKER", country: "US", value: 700, percent: 70 },
      ],
    };
    const risk = computePlatformConcentrationRisk(platforms);
    expect(risk).toEqual({ platform: "IBKR", percent: 70, hasData: true, state: "warn" });
    expect(computePlatformConcentrationRisk(platforms, 75).state).toBe("ok");
    expect(computePlatformConcentrationRisk(null).hasData).toBe(false);
  });

  it("labels currency exposure rows and lists what each is made of", () => {
    const rows = buildCurrencyExposureRows([
      { currency: "USD", cash: 100, stocks_funds: 400, stablecoins: 50, crypto: 0, liabilities: 0, value: 550, percent: 55 },
      { currency: "SGD", cash: 300, stocks_funds: 0, stablecoins: 0, crypto: 0, liabilities: 20, value: 280, percent: 28 },
      { currency: "CRYPTO", cash: 0, stocks_funds: 0, stablecoins: 0, crypto: 170, liabilities: 0, value: 170, percent: 17 },
    ]);
    expect(rows.map((row) => row.label)).toEqual(["USD", "SGD", "Crypto (not stablecoins)"]);
    expect(rows[0].parts.map((part) => part.label)).toEqual(["Stocks", "Cash", "Stablecoins"]);
    expect(rows[1].parts).toEqual([
      { key: "cash", label: "Cash", value: 300 },
      { key: "liabilities", label: "Cards owed", value: 20 },
    ]);
    expect(buildCurrencyExposureRows(null)).toEqual([]);
  });
});
