/**
 * One chart palette and one donut-gradient builder (#150, review #130 finding 7.4: there
 * were 7 copies). Colours are assigned by position, so a legend dot and its slice match.
 */
export const CHART_COLORS = [
  "#4f8cff",
  "#1fb981",
  "#f59f43",
  "#7d67ff",
  "#ef6ca8",
  "#2ebac6",
  "#f4cf5d",
  "#8f9db2",
] as const;

/** The colour of the `index`-th series (wraps around the palette). */
export function chartColor(index: number): string {
  return CHART_COLORS[((index % CHART_COLORS.length) + CHART_COLORS.length) % CHART_COLORS.length];
}

/** The track colour for the part of a donut no slice covers. */
const DONUT_TRACK = "color-mix(in srgb, var(--line) 65%, transparent 35%)";

/**
 * A `conic-gradient(...)` for a donut from slice percentages (0-100 points). Negative
 * slices count as 0, the total is capped at 100%, and any remainder is the grey track.
 */
export function donutGradient(percents: readonly number[]): string {
  let offset = 0;
  const parts = percents.map((percent, idx) => {
    const next = Math.min(100, offset + Math.max(0, percent));
    const part = `${chartColor(idx)} ${offset.toFixed(2)}% ${next.toFixed(2)}%`;
    offset = next;
    return part;
  });
  if (offset < 100) {
    parts.push(`${DONUT_TRACK} ${offset.toFixed(2)}% 100%`);
  }
  return `conic-gradient(${parts.join(", ")})`;
}
