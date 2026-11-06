// Source freshness (#252, D-67): labels for the Data Hub table and the Overview line.
import type { SourceFreshness, SourceFreshnessRow } from "./api";
import { formatPlatformLabel } from "./platformLabels";
import * as fmt from "./format";

/** The shared cache key: Data Hub and Overview read one resource. */
export const SOURCE_FRESHNESS_KEY = "sourceFreshness";

const KIND_LABELS: Record<string, string> = {
  ibkr_flex: "IBKR Flex",
  broker_statement: "Broker statement",
  bank_statement: "Bank statement",
  card_statement: "Card statement",
  account_statement: "Statement",
  crypto_wallet: "Wallet refresh",
  market_data: "Quote feed",
  fx: "FX feed",
};

export const CADENCE_LABELS: Record<string, string> = {
  daily: "Daily",
  weekdays: "Weekdays",
  weekly: "Weekly",
  monthly: "Monthly",
  quarterly: "Quarterly",
  off: "Not tracked",
};

export function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? fmt.formatEnumLabel(kind);
}

/** "IBKR Flex · IBKR", "Card statement · DBS": what the source is. */
export function sourceDetail(row: SourceFreshnessRow): string {
  const kind = kindLabel(row.kind);
  if (!row.platform || row.kind === "market_data") return kind;
  return `${kind} · ${formatPlatformLabel(row.platform)}`;
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** "Monthly · 10 days' grace", "Weekdays · 2 weekdays' grace", "Not tracked". */
export function cadenceLabel(cadence: string, graceDays: number): string {
  const label = CADENCE_LABELS[cadence] ?? fmt.formatEnumLabel(cadence);
  if (cadence === "off") return label;
  if (graceDays <= 0) return label;
  const unit = cadence === "weekdays" ? ["weekday's", "weekdays'"] : ["day's", "days'"];
  return `${label} · ${plural(graceDays, unit[0], unit[1])} grace`;
}

/** The grace field's unit in the editor. */
export function graceUnit(cadence: string): string {
  return cadence === "weekdays" ? "weekdays" : "days";
}

export function statusLabel(row: SourceFreshnessRow): string {
  switch (row.status) {
    case "overdue":
      return row.days_overdue != null ? `${plural(row.days_overdue, "day", "days")} overdue` : "Overdue";
    case "never_loaded":
      return "No data yet";
    case "no_schedule":
      return "Not tracked";
    default:
      return "On time";
  }
}

/** A StatusPill tone. */
export function statusTone(row: SourceFreshnessRow): "good" | "warn" | "bad" | "neutral" {
  if (row.status === "overdue") return "bad";
  if (row.status === "never_loaded") return "warn";
  if (row.status === "no_schedule") return "neutral";
  return "good";
}

/** "Next due by 10 Dec 2026" / "Was due 25 Sep 2026" / null. */
export function dueLabel(row: SourceFreshnessRow): string | null {
  if (!row.due_date) return null;
  return row.status === "overdue" ? `Was due ${fmt.formatDate(row.due_date)}` : `Next due by ${fmt.formatDate(row.due_date)}`;
}

/** One overdue source for the Overview line: "DBS Card (12 days)", "FX rates (no data yet)". */
function overdueItem(row: SourceFreshnessRow): string {
  if (row.status === "never_loaded") return `${row.label} (no data yet)`;
  return row.days_overdue != null ? `${row.label} (${plural(row.days_overdue, "day", "days")})` : row.label;
}

/**
 * "2 sources overdue: DBS Card (12 days), FX rates (no data yet)"; the first `max` by
 * the API's order (overdue first), then "and N more". Null when nothing is overdue.
 */
export function overdueSummary(data: SourceFreshness | undefined, max = 3): string | null {
  const overdue = (data?.sources ?? []).filter((row) => row.overdue);
  if (overdue.length === 0) return null;
  const shown = overdue.slice(0, max).map(overdueItem);
  const rest = overdue.length - shown.length;
  const list = rest > 0 ? `${shown.join(", ")} and ${rest} more` : shown.join(", ");
  return `${plural(overdue.length, "source", "sources")} overdue: ${list}`;
}
