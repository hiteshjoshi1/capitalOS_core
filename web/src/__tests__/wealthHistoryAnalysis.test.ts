import { describe, expect, it } from "vitest";
import {
  componentDelta,
  computeMonthFlags,
  isCarriedPoint,
  isGapPoint,
} from "../lib/wealthHistoryAnalysis";
import type { WealthTimelinePoint } from "../lib/api";

function point(overrides: Partial<WealthTimelinePoint> & { month: string }): WealthTimelinePoint {
  return {
    anchor_date: `${overrides.month}-01`,
    total: 0,
    cash: 0,
    stocks_funds: 0,
    crypto: 0,
    liabilities: 0,
    source_freshness: [],
    freshness_status: "fresh",
    computed_at: null,
    uploads: [],
    ...overrides,
  };
}

describe("isGapPoint", () => {
  it("is true when every component is zero", () => {
    expect(isGapPoint(point({ month: "2026-01" }))).toBe(true);
  });

  it("is false when any component is non-zero", () => {
    expect(isGapPoint(point({ month: "2026-01", cash: 1 }))).toBe(false);
    expect(isGapPoint(point({ month: "2026-01", stocks_funds: 1 }))).toBe(false);
    expect(isGapPoint(point({ month: "2026-01", crypto: 1 }))).toBe(false);
    expect(isGapPoint(point({ month: "2026-01", total: 1 }))).toBe(false);
  });

  it("ignores liabilities — a leverage-only month is still a gap", () => {
    expect(isGapPoint(point({ month: "2026-01", liabilities: 500 }))).toBe(true);
  });
});

describe("isCarriedPoint", () => {
  it("is false for gap points regardless of freshness_status", () => {
    expect(isCarriedPoint(point({ month: "2026-01", freshness_status: "stale" }))).toBe(false);
  });

  it("is true for a non-gap point whose freshness_status isn't fresh", () => {
    expect(isCarriedPoint(point({ month: "2026-01", total: 100, cash: 100, freshness_status: "stale" }))).toBe(true);
  });

  it("is false for a fresh non-gap point", () => {
    expect(isCarriedPoint(point({ month: "2026-01", total: 100, cash: 100, freshness_status: "fresh" }))).toBe(false);
  });
});

describe("componentDelta", () => {
  it("diffs each component against the previous point", () => {
    const current = point({ month: "2026-02", stocks_funds: 120, cash: 40, crypto: 10, liabilities: 5 });
    const prev = point({ month: "2026-01", stocks_funds: 100, cash: 50, crypto: 8, liabilities: 2 });
    expect(componentDelta(current, prev)).toEqual({
      stocks_funds: 20,
      cash: -10,
      crypto: 2,
      liabilities: 3,
    });
  });

  it("treats a null previous point as a zero baseline", () => {
    const current = point({ month: "2026-01", stocks_funds: 100, cash: 50, crypto: 8, liabilities: 2 });
    expect(componentDelta(current, null)).toEqual({
      stocks_funds: 100,
      cash: 50,
      crypto: 8,
      liabilities: 2,
    });
  });
});

describe("computeMonthFlags", () => {
  it("marks the first point as the start of history — no delta, no comparison month", () => {
    const points = [point({ month: "2026-01", total: 100, cash: 100 })];
    const flags = computeMonthFlags(points);
    expect(flags.get("2026-01")).toMatchObject({
      delta: null,
      componentDeltas: null,
      dominantComponent: null,
      comparedToMonth: null,
      isCatchUp: false,
      isOutlier: false,
    });
  });

  it("gap points always get null/false flags", () => {
    const points = [
      point({ month: "2026-01", total: 100, cash: 100 }),
      point({ month: "2026-02" }),
    ];
    const flags = computeMonthFlags(points);
    expect(flags.get("2026-02")).toEqual({
      isCatchUp: false,
      isOutlier: false,
      delta: null,
      componentDeltas: null,
      dominantComponent: null,
      comparedToMonth: null,
    });
  });

  it("skips over gap points when finding the nearest earlier point to compare against", () => {
    const points = [
      point({ month: "2026-01", total: 100, cash: 100 }),
      point({ month: "2026-02" }), // gap
      point({ month: "2026-03", total: 150, cash: 150 }),
    ];
    const flags = computeMonthFlags(points);
    const march = flags.get("2026-03")!;
    expect(march.comparedToMonth).toBe("2026-01");
    expect(march.delta).toBe(50);
  });

  it("computes per-component deltas and picks the dominant component by largest absolute move", () => {
    const points = [
      point({ month: "2026-01", total: 100, stocks_funds: 60, cash: 30, crypto: 10 }),
      point({ month: "2026-02", total: 160, stocks_funds: 110, cash: 32, crypto: 18 }),
    ];
    const flags = computeMonthFlags(points);
    const feb = flags.get("2026-02")!;
    expect(feb.componentDeltas).toEqual({ stocks_funds: 50, cash: 2, crypto: 8, liabilities: 0 });
    expect(feb.dominantComponent).toBe("stocks_funds");
  });

  it("flags a catch-up month when a source's as_of jumps more than 45 days since the prior point", () => {
    const points = [
      point({
        month: "2026-01",
        total: 100,
        cash: 100,
        source_freshness: [{ platform: "OCBC", as_of: "2026-01-01", days_old: 0, status: "fresh" }],
      }),
      point({
        month: "2026-03",
        total: 400,
        cash: 400,
        source_freshness: [{ platform: "OCBC", as_of: "2026-03-10", days_old: 0, status: "fresh" }],
      }),
    ];
    const flags = computeMonthFlags(points);
    expect(flags.get("2026-03")!.isCatchUp).toBe(true);
  });

  it("does not flag catch-up when the same source's as_of is unchanged or within the window", () => {
    const points = [
      point({
        month: "2026-01",
        total: 100,
        cash: 100,
        source_freshness: [{ platform: "OCBC", as_of: "2026-01-01", days_old: 0, status: "fresh" }],
      }),
      point({
        month: "2026-02",
        total: 110,
        cash: 110,
        source_freshness: [{ platform: "OCBC", as_of: "2026-01-20", days_old: 0, status: "fresh" }],
      }),
    ];
    const flags = computeMonthFlags(points);
    expect(flags.get("2026-02")!.isCatchUp).toBe(false);
  });

  it("flags an outlier delta once enough trailing samples exist and the move is far from the mean", () => {
    const points = [
      point({ month: "2026-01", total: 100, cash: 100 }),
      point({ month: "2026-02", total: 110, cash: 110 }), // delta 10
      point({ month: "2026-03", total: 124, cash: 124 }), // delta 14
      point({ month: "2026-04", total: 132, cash: 132 }), // delta 8
      point({ month: "2026-05", total: 502, cash: 502 }), // delta 370 — way outside trailing stdev
    ];
    const flags = computeMonthFlags(points);
    expect(flags.get("2026-02")!.isOutlier).toBe(false); // not enough trailing samples yet
    expect(flags.get("2026-05")!.isOutlier).toBe(true);
  });

  it("excludes catch-up deltas from the trailing outlier baseline", () => {
    const points = [
      point({
        month: "2026-01",
        total: 100,
        cash: 100,
        source_freshness: [{ platform: "OCBC", as_of: "2026-01-01", days_old: 0, status: "fresh" }],
      }),
      point({
        month: "2026-02",
        total: 110,
        cash: 110,
        source_freshness: [{ platform: "OCBC", as_of: "2026-02-01", days_old: 0, status: "fresh" }],
      }),
      point({
        month: "2026-03",
        total: 118,
        cash: 118,
        source_freshness: [{ platform: "OCBC", as_of: "2026-03-01", days_old: 0, status: "fresh" }],
      }),
      // Catch-up month: huge delta driven by a stale source finally reporting.
      point({
        month: "2026-04",
        total: 600,
        cash: 600,
        source_freshness: [{ platform: "OCBC", as_of: "2026-04-20", days_old: 0, status: "fresh" }],
      }),
    ];
    const flags = computeMonthFlags(points);
    expect(flags.get("2026-04")!.isCatchUp).toBe(true);
    // The catch-up month's huge delta must not be folded into the trailing baseline
    // used to judge later months as outliers.
    const points2 = [...points, point({ month: "2026-05", total: 610, cash: 610 })];
    const flags2 = computeMonthFlags(points2);
    expect(flags2.get("2026-05")!.isOutlier).toBe(false);
  });
});
