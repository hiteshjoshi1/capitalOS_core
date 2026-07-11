import type { WealthTimelinePoint } from "./api";

export function isGapPoint(p: WealthTimelinePoint): boolean {
  return p.total === 0 && p.cash === 0 && p.stocks_funds === 0 && p.crypto === 0;
}

export function isCarriedPoint(p: WealthTimelinePoint): boolean {
  return !isGapPoint(p) && p.freshness_status !== "fresh";
}

export type ComponentDeltas = {
  stocks_funds: number;
  cash: number;
  crypto: number;
  liabilities: number;
};

export type MonthFlags = {
  /** A source's as_of jumped more than ~45 days since the prior point — this
   * month's delta likely bundles multiple months of drift from one late upload. */
  isCatchUp: boolean;
  /** |delta| exceeds 2x the trailing (up to 12mo) stdev of non-catch-up deltas. */
  isOutlier: boolean;
  /** Total delta vs. the nearest earlier non-gap point, or null if none exists. */
  delta: number | null;
  /** Per-component deltas vs. that same nearest earlier non-gap point. */
  componentDeltas: ComponentDeltas | null;
  /** The component with the largest absolute delta, for outlier attribution copy. */
  dominantComponent: "stocks_funds" | "cash" | "crypto" | null;
  /** The nearest earlier non-gap point's month key, for "vs {month}" labels. */
  comparedToMonth: string | null;
};

const CATCH_UP_JUMP_DAYS = 45;
const OUTLIER_SIGMA_MULTIPLE = 2;
const TRAILING_WINDOW = 12;
const MIN_SAMPLES_FOR_OUTLIER = 3;

function daysBetween(a: string, b: string): number {
  return (new Date(b).getTime() - new Date(a).getTime()) / 86_400_000;
}

/** Per-month analysis flags, computed once over the full point series in order. */
export function computeMonthFlags(points: WealthTimelinePoint[]): Map<string, MonthFlags> {
  const flags = new Map<string, MonthFlags>();
  const trailingDeltas: number[] = [];

  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    if (isGapPoint(p)) {
      flags.set(p.month, {
        isCatchUp: false,
        isOutlier: false,
        delta: null,
        componentDeltas: null,
        dominantComponent: null,
        comparedToMonth: null,
      });
      continue;
    }

    let prevIdx = i - 1;
    while (prevIdx >= 0 && isGapPoint(points[prevIdx])) prevIdx--;
    const prev = prevIdx >= 0 ? points[prevIdx] : null;
    const delta = prev ? p.total - prev.total : null;

    let isCatchUp = false;
    if (prev) {
      const prevByPlatform = new Map(prev.source_freshness.map((s) => [s.platform, s.as_of]));
      for (const s of p.source_freshness) {
        const prevAsOf = prevByPlatform.get(s.platform);
        if (prevAsOf && s.as_of && s.as_of !== prevAsOf && daysBetween(prevAsOf, s.as_of) > CATCH_UP_JUMP_DAYS) {
          isCatchUp = true;
          break;
        }
      }
    }

    let isOutlier = false;
    if (delta != null && trailingDeltas.length >= MIN_SAMPLES_FOR_OUTLIER) {
      const mean = trailingDeltas.reduce((a, b) => a + b, 0) / trailingDeltas.length;
      const variance = trailingDeltas.reduce((a, b) => a + (b - mean) ** 2, 0) / trailingDeltas.length;
      const sigma = Math.sqrt(variance);
      if (sigma > 0 && Math.abs(delta - mean) > OUTLIER_SIGMA_MULTIPLE * sigma) isOutlier = true;
    }

    let dominantComponent: MonthFlags["dominantComponent"] = null;
    let componentDeltas: ComponentDeltas | null = null;
    if (prev) {
      componentDeltas = componentDelta(p, prev);
      const ranked: [MonthFlags["dominantComponent"], number][] = [
        ["stocks_funds", componentDeltas.stocks_funds],
        ["cash", componentDeltas.cash],
        ["crypto", componentDeltas.crypto],
      ];
      ranked.sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
      dominantComponent = ranked[0][0];
    }

    flags.set(p.month, {
      isCatchUp,
      isOutlier,
      delta,
      componentDeltas,
      dominantComponent,
      comparedToMonth: prev?.month ?? null,
    });

    if (delta != null && !isCatchUp) {
      trailingDeltas.push(delta);
      if (trailingDeltas.length > TRAILING_WINDOW) trailingDeltas.shift();
    }
  }

  return flags;
}

export function componentDelta(current: WealthTimelinePoint, prev: WealthTimelinePoint | null) {
  const base = prev ?? { stocks_funds: 0, cash: 0, crypto: 0, liabilities: 0 };
  return {
    stocks_funds: current.stocks_funds - base.stocks_funds,
    cash: current.cash - base.cash,
    crypto: current.crypto - base.crypto,
    liabilities: current.liabilities - base.liabilities,
  };
}
