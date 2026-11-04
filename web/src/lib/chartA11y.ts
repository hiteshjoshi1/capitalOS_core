/**
 * Text versions of charts for screen readers (#151; #131 "chart labels aren't announced").
 * A chart is `role="img"` with a label that carries its data, e.g.
 * "Cash by account: DBS 62.5%, OCBC 37.5%".
 */
import { formatPercent } from "./format";

/** At most this many parts are read out; the rest are summarised as "and N more". */
const MAX_PARTS = 8;

function joinParts(title: string, parts: string[]): string {
  if (parts.length === 0) return `${title}: no data`;
  const shown = parts.slice(0, MAX_PARTS);
  const more = parts.length - shown.length;
  return `${title}: ${shown.join(", ")}${more > 0 ? `, and ${more} more` : ""}`;
}

/** Shares of a whole, `percent` in points (62.5 is 62.5%). */
export function describeShares(title: string, items: ReadonlyArray<{ label: string; percent: number }>): string {
  return joinParts(
    title,
    items.map((item) => `${item.label} ${formatPercent(item.percent, { scale: "points" })}`),
  );
}

/** A series of labelled values that are already formatted (e.g. "Jun '26 S$ 2.1M"). */
export function describeSeries(title: string, items: ReadonlyArray<{ label: string; value: string }>): string {
  return joinParts(
    title,
    items.map((item) => `${item.label} ${item.value}`),
  );
}
