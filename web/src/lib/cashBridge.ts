import type { CashFlowWaterfall } from "./api";
import * as fmt from "./format";

function localDateToday(now: Date = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

/**
 * The dates the cash bridge spans (#265, D-72): "Cash snapshots from 6 Oct 2026 to 4 Nov 2026",
 * plus, when those aren't on the month's boundaries, which boundaries they stand in for ("the
 * newest so far" for the open month). Null when the bridge isn't available.
 */
export function cashBridgeSpanText(waterfall: CashFlowWaterfall, today: string = localDateToday()): string | null {
  const available = waterfall.bridge_available ?? waterfall.boundary_exact;
  if (!available) return null;
  const start = waterfall.span_start ?? waterfall.snapshot_start_as_of;
  const end = waterfall.span_end ?? waterfall.snapshot_end_as_of;
  if (!start || !end) return null;
  const span = `Cash snapshots from ${fmt.formatDate(start)} to ${fmt.formatDate(end)}.`;
  if (waterfall.span_basis !== "nearest") return span;
  const boundaryStart = waterfall.snapshot_start_boundary_at;
  const boundaryEnd = waterfall.snapshot_end_boundary_at;
  if (!boundaryStart || !boundaryEnd) return span;
  const endIsFuture = boundaryEnd.slice(0, 10) > today;
  return endIsFuture
    ? `${span} The nearest to ${fmt.formatDate(boundaryStart)} and the newest so far.`
    : `${span} The nearest to ${fmt.formatDate(boundaryStart)} and ${fmt.formatDate(boundaryEnd)}.`;
}
