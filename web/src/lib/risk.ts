import type { CurrencyExposureItem, PlatformAllocation, RiskHolding, RiskThresholdsSetting } from "./api";
import { formatPercent } from "./format";

/**
 * The Risk page's concentration thresholds (#253, D-68): the percent above which a
 * figure is "concentrated". Only an upper threshold warns; a figure below it is never
 * flagged (low concentration is not a risk). Each can be changed in Settings → Risk
 * thresholds; these are the defaults a user who hasn't changed one gets (the server
 * stores null for "the default").
 */
export type RiskThresholds = {
  /** Largest position, % of net worth. */
  largestPositionWarnPct: number;
  /** Top 3 / top 5 positions together, % of net worth. */
  topNWarnPct: number;
  /** Largest platform, % of gross assets (the Overview platform donut's split). */
  platformWarnPct: number;
};

export const DEFAULT_RISK_THRESHOLDS: RiskThresholds = {
  largestPositionWarnPct: 15,
  topNWarnPct: 50,
  platformWarnPct: 50,
};

/** The useApiResource key of GET /dashboard/risk-thresholds (Risk page and Settings share it). */
export const RISK_THRESHOLDS_RESOURCE_KEY = "riskThresholds";

/** The thresholds in effect: the user's own where set, else the defaults. */
export function resolveRiskThresholds(setting?: RiskThresholdsSetting | null): RiskThresholds {
  return {
    largestPositionWarnPct: setting?.largest_position_warn_pct ?? DEFAULT_RISK_THRESHOLDS.largestPositionWarnPct,
    topNWarnPct: setting?.top_n_warn_pct ?? DEFAULT_RISK_THRESHOLDS.topNWarnPct,
    platformWarnPct: setting?.platform_warn_pct ?? DEFAULT_RISK_THRESHOLDS.platformWarnPct,
  };
}

/** "muted": no data; "ok": at or below the threshold (shown neutral); "warn": above it. */
export type RiskState = "muted" | "ok" | "warn";
export type TopN = 3 | 5;

/** Above the threshold is concentrated; at or below it is not flagged. */
export function concentrationState(percent: number, thresholdPct: number, hasData = true): RiskState {
  if (!hasData) return "muted";
  return percent > thresholdPct ? "warn" : "ok";
}

export type LargestPositionRisk = {
  symbol: string | null;
  assetClass: string | null;
  value: number;
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

/** A position as the Risk page reads it (#149: from /dashboard/risk-summary). */
type Holding = RiskHolding;

function toPercent(value: number, total: number): number {
  if (total <= 0) {
    return 0;
  }
  return (value / total) * 100;
}

/**
 * The positions in the order Overview's "Largest positions" lists them (#253): the
 * server's top_holdings, every asset class (stocks, funds, crypto), largest first.
 * The sort is stable, so ties keep the server's order, as on Overview.
 */
function rankedHoldings(holdings: Holding[]): Holding[] {
  return [...holdings].sort((a, b) => b.value - a.value);
}

/** A row's share of net worth: the server's `percent_of_networth` (the figure Overview
 * shows), else its value over the total. */
function holdingPercent(holding: Holding, netWorthTotal: number): number {
  return typeof holding.percent_of_networth === "number"
    ? holding.percent_of_networth
    : toPercent(holding.value, netWorthTotal);
}

export function computeLargestPositionRisk(
  holdings: Holding[],
  netWorthTotal: number,
  thresholdPct: number = DEFAULT_RISK_THRESHOLDS.largestPositionWarnPct,
): LargestPositionRisk {
  const ranked = rankedHoldings(holdings);
  if (ranked.length === 0 || netWorthTotal <= 0) {
    return { symbol: null, assetClass: null, value: 0, percent: 0, hasData: false, state: "muted" };
  }
  const largest = ranked[0];
  const percent = holdingPercent(largest, netWorthTotal);
  return {
    symbol: largest.symbol,
    assetClass: largest.asset_class,
    value: largest.value,
    percent,
    hasData: true,
    state: concentrationState(percent, thresholdPct),
  };
}

export function computeTopNConcentrationRisk(
  holdings: Holding[],
  netWorthTotal: number,
  n: TopN,
  thresholdPct: number = DEFAULT_RISK_THRESHOLDS.topNWarnPct,
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
  const ranked = rankedHoldings(holdings);
  const selected = ranked.slice(0, n);
  const sum = selected.reduce((acc, item) => acc + item.value, 0);
  const percent = toPercent(sum, netWorthTotal);
  return {
    percent,
    hasData: selected.length > 0,
    hasFullSelection: ranked.length >= n,
    state: concentrationState(percent, thresholdPct, selected.length > 0),
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
  return rankedHoldings(holdings)
    .slice(0, n)
    .map((item) => ({
      symbol: item.symbol,
      assetClass: item.asset_class,
      value: item.value,
      percent: holdingPercent(item, netWorthTotal),
    }));
}

/** The currency exposure bucket for crypto other than USD stablecoins (not a currency). */
export const CRYPTO_EXPOSURE_KEY = "CRYPTO";

export type CurrencyExposureRow = {
  currency: string;
  label: string;
  value: number;
  percent: number;
  /** What the row is made of, for its caption ("Stocks S$ 1,200 · Cash S$ 300"). */
  parts: Array<{ key: "stocks_funds" | "cash" | "stablecoins" | "crypto" | "liabilities"; label: string; value: number }>;
};

const CURRENCY_PART_LABELS = {
  stocks_funds: "Stocks",
  cash: "Cash",
  stablecoins: "Stablecoins",
  crypto: "Crypto",
  liabilities: "Cards owed",
} as const;

/** Currency exposure rows, largest share first (the server's order). */
export function buildCurrencyExposureRows(items: CurrencyExposureItem[] | null | undefined): CurrencyExposureRow[] {
  return (items ?? []).map((item) => ({
    currency: item.currency,
    label: item.currency === CRYPTO_EXPOSURE_KEY ? "Crypto (not stablecoins)" : item.currency,
    value: item.value,
    percent: item.percent,
    parts: (Object.keys(CURRENCY_PART_LABELS) as Array<keyof typeof CURRENCY_PART_LABELS>)
      .filter((key) => Math.abs(item[key] ?? 0) > 0.005)
      .map((key) => ({ key, label: CURRENCY_PART_LABELS[key], value: item[key] })),
  }));
}

export type PlatformConcentrationRisk = {
  platform: string | null;
  percent: number;
  hasData: boolean;
  state: RiskState;
};

/** The largest platform's share of gross assets, against the platform threshold. */
export function computePlatformConcentrationRisk(
  platforms: Pick<PlatformAllocation, "total" | "items"> | null | undefined,
  thresholdPct: number = DEFAULT_RISK_THRESHOLDS.platformWarnPct,
): PlatformConcentrationRisk {
  const items = [...(platforms?.items ?? [])].sort((a, b) => b.value - a.value);
  if (items.length === 0 || !platforms || platforms.total <= 0) {
    return { platform: null, percent: 0, hasData: false, state: "muted" };
  }
  const largest = items[0];
  return {
    platform: largest.platform,
    percent: largest.percent,
    hasData: true,
    state: concentrationState(largest.percent, thresholdPct),
  };
}

/** A share as the page shows it, with the shared formatter (one decimal). */
export function formatRiskPercent(percent: number): string {
  return formatPercent(percent, { scale: "points" });
}

export function formatLargestPosition(risk: LargestPositionRisk): string {
  if (!risk.hasData || !risk.symbol) {
    return "—";
  }
  return `${risk.symbol} — ${formatRiskPercent(risk.percent)}`;
}

/** The CSS class for a state: a warning above the threshold, never "bad" (#253). */
export function riskStateClassName(state: RiskState): "muted" | "warn" | "" {
  switch (state) {
    case "warn":
      return "warn";
    case "muted":
      return "muted";
    default:
      return "";
  }
}

/** "Above 15%: concentrated", the rule a card states under its figure. */
export function thresholdRule(thresholdPct: number): string {
  return `Above ${formatPercent(thresholdPct, { scale: "points", decimals: Number.isInteger(thresholdPct) ? 0 : 1 })}: concentrated`;
}
