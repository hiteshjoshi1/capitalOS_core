import { describe, expect, it } from "vitest";

import { CHART_COLORS, chartColor, donutGradient } from "../lib/chartColors";

describe("chartColors", () => {
  it("wraps around the palette", () => {
    expect(chartColor(0)).toBe(CHART_COLORS[0]);
    expect(chartColor(CHART_COLORS.length)).toBe(CHART_COLORS[0]);
    expect(chartColor(-1)).toBe(CHART_COLORS[CHART_COLORS.length - 1]);
  });

  it("builds slices in order and fills the remainder with the track", () => {
    const g = donutGradient([60, 30]);
    expect(g).toBe(
      `conic-gradient(${CHART_COLORS[0]} 0.00% 60.00%, ${CHART_COLORS[1]} 60.00% 90.00%, color-mix(in srgb, var(--line) 65%, transparent 35%) 90.00% 100%)`,
    );
  });

  it("ignores negative slices and caps at 100%", () => {
    expect(donutGradient([-5, 80, 40])).toBe(
      `conic-gradient(${CHART_COLORS[0]} 0.00% 0.00%, ${CHART_COLORS[1]} 0.00% 80.00%, ${CHART_COLORS[2]} 80.00% 100.00%)`,
    );
  });

  it("an empty donut is all track", () => {
    expect(donutGradient([])).toContain("0.00% 100%");
  });
});
