import type { DashboardSummary } from "./api";

export const RISK_LARGEST_POSITION_WARN_PCT = 15;
export const RISK_TOP5_TARGET_MIN_PCT = 35;
export const RISK_TOP5_TARGET_MAX_PCT = 55;

export type RiskState = "muted" | "in_band" | "warn" | "out_of_band";
export type TopN = 3 | 5;

export type LargestPositionRisk = {
  symbol: string | null;
  percent: number;
  hasData: boolean;
  state: RiskState;
};

export type Top5ConcentrationRisk = {
  percent: number;
  hasData: boolean;
  state: RiskState;
};

export type TopNConcentrationRisk = {
  percent: number;
  hasData: boolean;
  hasFullSelection: boolean;
  state: RiskState;
  selectedN: TopN;
  availableCount: number;
};

export type RiskDistributionItem = {
  symbol: string;
  assetClass: string;
  value: number;
  percent: number;
};

type Holding = DashboardSummary["top_holdings"][number];

function toPercent(value: number, total: number): number {
  if (total <= 0) {
    return 0;
  }
  return (value / total) * 100;
}

function noLargestPositionData(): LargestPositionRisk {
  return {
    symbol: null,
    percent: 0,
    hasData: false,
    state: "muted",
  };
}

function sortHoldingsForRisk(holdings: Holding[]): Holding[] {
  return [...holdings].sort((a, b) => {
    if (b.value !== a.value) {
      return b.value - a.value;
    }
    return a.symbol.localeCompare(b.symbol);
  });
}

export function computeLargestPositionRisk(holdings: Holding[], netWorthTotal: number): LargestPositionRisk {
  if (holdings.length === 0 || netWorthTotal <= 0) {
    return noLargestPositionData();
  }

  // Exclude CASH from risk calculations
  const filtered = holdings.filter((h) => h.asset_class !== "CASH");
  if (filtered.length === 0) {
    return noLargestPositionData();
  }

  const largest = filtered.reduce((max, item) => (item.value > max.value ? item : max), filtered[0]);
  const percent = toPercent(largest.value, netWorthTotal);
  return {
    symbol: largest.symbol,
    percent,
    hasData: true,
    state: percent >= RISK_LARGEST_POSITION_WARN_PCT ? "warn" : "in_band",
  };
}

export function computeTop5ConcentrationRisk(holdings: Holding[], netWorthTotal: number): Top5ConcentrationRisk {
  const top5 = computeTopNConcentrationRisk(holdings, netWorthTotal, 5);
  return {
    percent: top5.percent,
    hasData: top5.hasData,
    state: top5.state,
  };
}

export function computeTopNConcentrationRisk(
  holdings: Holding[],
  netWorthTotal: number,
  n: TopN,
): TopNConcentrationRisk {
  if (holdings.length === 0 || netWorthTotal <= 0) {
    return {
      percent: 0,
      hasData: false,
      hasFullSelection: false,
      state: "muted",
      selectedN: n,
      availableCount: holdings.length,
    };
  }

  // Exclude CASH from risk calculations
  const filtered = holdings.filter((h) => h.asset_class !== "CASH");
  const sorted = sortHoldingsForRisk(filtered);
  const selected = sorted.slice(0, n);
  const sum = selected.reduce((acc, item) => acc + item.value, 0);
  const percent = toPercent(sum, netWorthTotal);
  const inBand = percent >= RISK_TOP5_TARGET_MIN_PCT && percent <= RISK_TOP5_TARGET_MAX_PCT;
  return {
    percent,
    hasData: selected.length > 0,
    hasFullSelection: filtered.length >= n,
    state: inBand ? "in_band" : "out_of_band",
    selectedN: n,
    availableCount: selected.length,
  };
}

export function buildTopNDistribution(
  holdings: Holding[],
  netWorthTotal: number,
  n: TopN,
): RiskDistributionItem[] {
  if (holdings.length === 0 || netWorthTotal <= 0) {
    return [];
  }

  // Exclude CASH from risk calculations
  const filtered = holdings.filter((h) => h.asset_class !== "CASH");
  return sortHoldingsForRisk(filtered)
    .slice(0, n)
    .map((item) => ({
      symbol: item.symbol,
      assetClass: item.asset_class,
      value: item.value,
      percent: toPercent(item.value, netWorthTotal),
    }));
}

export function formatRiskPercent(percent: number): string {
  return `${percent.toFixed(1)}%`;
}

export function formatLargestPosition(risk: LargestPositionRisk): string {
  if (!risk.hasData || !risk.symbol) {
    return "—";
  }
  return `${risk.symbol} — ${formatRiskPercent(risk.percent)}`;
}

export function riskStateClassName(state: RiskState): "muted" | "good" | "warn" | "bad" {
  switch (state) {
    case "in_band":
      return "good";
    case "warn":
      return "warn";
    case "out_of_band":
      return "bad";
    default:
      return "muted";
  }
}
