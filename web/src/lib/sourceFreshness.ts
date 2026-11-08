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

/** The cadences the editor offers when the API sends none. */
export const DEFAULT_CADENCES = ["daily", "weekdays", "weekly", "monthly", "quarterly", "off"];

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

// ─── Upload links (#278) ─────────────────────────────────────────────────────

/** Sources whose data arrives as a statement upload: their row opens Upload. */
export const UPLOAD_KINDS: ReadonlySet<string> = new Set([
  "broker_statement",
  "bank_statement",
  "card_statement",
  "account_statement",
]);

export function isUploadSource(row: Pick<SourceFreshnessRow, "kind" | "source_key">): boolean {
  return UPLOAD_KINDS.has(row.kind) && accountIdOf(row.source_key) != null;
}

/** `account:12` → 12; anything else → null. */
export function accountIdOf(sourceKey: string): number | null {
  const m = /^account:(\d+)$/.exec(sourceKey);
  return m ? Number(m[1]) : null;
}

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** A real `YYYY-MM-DD` calendar day (rejects 2026-02-30). */
export function isIsoDate(value: string | null | undefined): value is string {
  const m = value ? ISO_DATE.exec(value) : null;
  if (!m) return false;
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  return d.getUTCFullYear() === Number(m[1]) && d.getUTCMonth() === Number(m[2]) - 1 && d.getUTCDate() === Number(m[3]);
}

/** Today in the browser's timezone, `YYYY-MM-DD`. */
export function localToday(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function toUtc(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

function fromUtc(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function daysInMonth(year: number, monthIndex: number): number {
  return new Date(Date.UTC(year, monthIndex + 1, 0)).getUTCDate();
}

/**
 * `months` calendar months after `iso`. A month-end date stays a month-end (30 Sep → 31 Oct),
 * so a month-end statement maps to the next month-end; any other day is clamped to the
 * target month's length (15 Jan → 15 Feb, 31 Jan → 28/29 Feb).
 */
function addMonthsKeepingEnd(iso: string, months: number): string {
  const d = toUtc(iso);
  const year = d.getUTCFullYear();
  const month = d.getUTCMonth();
  const day = d.getUTCDate();
  const monthEnd = day === daysInMonth(year, month);
  const index = year * 12 + month + months;
  const ty = Math.floor(index / 12);
  const tm = index % 12;
  const last = daysInMonth(ty, tm);
  return fromUtc(new Date(Date.UTC(ty, tm, monthEnd ? last : Math.min(day, last))));
}

function addDays(iso: string, days: number): string {
  const d = toUtc(iso);
  d.setUTCDate(d.getUTCDate() + days);
  return fromUtc(d);
}

function nextWeekday(iso: string): string {
  let next = addDays(iso, 1);
  while ([0, 6].includes(toUtc(next).getUTCDay())) next = addDays(next, 1);
  return next;
}

/**
 * The date of the statement that's due next (#278): one period of the source's cadence
 * after its last data date (the API's due date without the grace, D-67), never later than
 * today (a period that hasn't ended yet is uploaded "as of" today). No data yet: today.
 * Cadence `off`: null (nothing is expected; the upload keeps its own date).
 */
export function expectedStatementDate(lastData: string | null | undefined, cadence: string, today: string): string | null {
  if (cadence === "off") return null;
  if (!isIsoDate(lastData)) return today;
  let next: string;
  switch (cadence) {
    case "daily":
      next = addDays(lastData, 1);
      break;
    case "weekdays":
      next = nextWeekday(lastData);
      break;
    case "weekly":
      next = addDays(lastData, 7);
      break;
    case "quarterly":
      next = addMonthsKeepingEnd(lastData, 3);
      break;
    case "monthly":
    default:
      next = addMonthsKeepingEnd(lastData, 1);
      break;
  }
  return next > today ? today : next;
}

/**
 * Where a freshness row leads (#278): an upload source → Upload, prefilled with the account,
 * the due statement's date, and what to show about it; the quote feed → Market data; any
 * other source (IBKR Flex, wallets, FX) → null, not a link.
 */
export function sourceLink(row: SourceFreshnessRow, today: string = localToday()): string | null {
  if (row.kind === "market_data") return "/market-data";
  if (!isUploadSource(row)) return null;
  const params = new URLSearchParams({ account_id: String(accountIdOf(row.source_key)) });
  const asOf = expectedStatementDate(row.last_data_date, row.cadence, today);
  if (asOf) params.set("as_of", asOf);
  if (row.last_data_date) params.set("last_data", row.last_data_date);
  params.set("cadence", row.cadence);
  return `/ingest?${params.toString()}`;
}

/** "Upload a statement for DBS Card", "Open market data for SGX quotes": the link's name. */
export function sourceLinkLabel(row: SourceFreshnessRow): string {
  return row.kind === "market_data" ? `Open market data for ${row.label}` : `Upload a statement for ${row.label}`;
}

/**
 * The Upload page's line about what's due (#278):
 * "DBS Card: statement due for October 2026 (last data 30 Sep 2026)",
 * "DBS Card: up to date (last data 31 Oct 2026). The next statement covers November 2026.",
 * "DBS Card: no data yet. Upload its newest statement."
 * "Up to date" when the next period hasn't ended by `today`, so an on-time source never reads "due".
 */
export function uploadExpectationLine(
  accountName: string,
  asOf: string | null,
  lastData: string | null,
  cadence: string | null,
  today: string = localToday(),
): string | null {
  if (!isIsoDate(lastData)) return `${accountName}: no data yet. Upload its newest statement.`;
  if (!isIsoDate(asOf)) return null;
  const periodOf = (date: string) =>
    cadence === "monthly" || cadence === "quarterly" || cadence == null ? fmt.formatMonth(date.slice(0, 7)) : fmt.formatDate(date);
  const next = expectedStatementDate(lastData, cadence ?? "monthly", "9999-12-31");
  if (next && next > today) {
    return `${accountName}: up to date (last data ${fmt.formatDate(lastData)}). The next statement covers ${periodOf(next)}.`;
  }
  return `${accountName}: statement due for ${periodOf(asOf)} (last data ${fmt.formatDate(lastData)})`;
}
