import type { DashboardSummary } from "./api";

export const RISK_LARGEST_POSITION_WARN_PCT = 15;
export const RISK_TOP5_TARGET_MIN_PCT = 35;
export const RISK_TOP5_TARGET_MAX_PCT = 55;

export type RiskState = "muted" | "in_band" | "warn" | "out_of_band";

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

function noTop5Data(): Top5ConcentrationRisk {
  return {
    percent: 0,
    hasData: false,
    state: "muted",
  };
}

export function computeLargestPositionRisk(holdings: Holding[], netWorthTotal: number): LargestPositionRisk {
  if (holdings.length === 0 || netWorthTotal <= 0) {
    return noLargestPositionData();
  }

  const largest = holdings.reduce((max, item) => (item.value > max.value ? item : max), holdings[0]);
  const percent = toPercent(largest.value, netWorthTotal);
  return {
    symbol: largest.symbol,
    percent,
    hasData: true,
    state: percent >= RISK_LARGEST_POSITION_WARN_PCT ? "warn" : "in_band",
  };
}

export function computeTop5ConcentrationRisk(holdings: Holding[], netWorthTotal: number): Top5ConcentrationRisk {
  if (holdings.length < 5 || netWorthTotal <= 0) {
    return noTop5Data();
  }

  const sumTop5 = [...holdings]
    .sort((a, b) => b.value - a.value)
    .slice(0, 5)
    .reduce((acc, item) => acc + item.value, 0);
  const percent = toPercent(sumTop5, netWorthTotal);
  const inBand = percent >= RISK_TOP5_TARGET_MIN_PCT && percent <= RISK_TOP5_TARGET_MAX_PCT;
  return {
    percent,
    hasData: true,
    state: inBand ? "in_band" : "out_of_band",
  };
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
