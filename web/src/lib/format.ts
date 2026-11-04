/**
 * The one formatting library (#150, review #130 finding 7.4 and #131 "Numbers and
 * formatting"). Every page formats money, percentages, months and dates through here.
 *
 * Rules:
 * - A fixed locale (`en-SG`), so output never depends on the browser's locale.
 * - Money is `<prefix> <amount>` with one space: `S$ 1,234`, `USD 1,234`. The sign goes
 *   before the prefix: `-S$ 1,234`, `+S$ 1,234`. So a card's two deltas always print
 *   their signs the same way.
 * - Whole units by default. When decimals are asked for they are fixed (`S$ 53,512.90`,
 *   never `S$ 53,512.9`).
 * - Compact (`S$ 1.2M`, `S$ 35K`) is for chart labels and tight spaces only.
 * - A missing value is `—`, never `0`.
 * - Dates read `4 Nov 2026`, and date-times `4 Nov 2026, 14:05` (24-hour, local time).
 */

export const LOCALE = "en-SG";
export const MISSING = "—";

/** The base currencies a page can be shown in (one list, not one per page). */
export const CURRENCY_OPTIONS = ["SGD", "USD", "HKD", "INR"] as const;
export type BaseCurrencyCode = (typeof CURRENCY_OPTIONS)[number];
export const DEFAULT_BASE_CURRENCY: BaseCurrencyCode = "SGD";

export function isBaseCurrency(value: unknown): value is BaseCurrencyCode {
  return typeof value === "string" && (CURRENCY_OPTIONS as readonly string[]).includes(value);
}

type Amount = number | null | undefined;

function isNumber(value: Amount): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

const numberFormats = new Map<string, Intl.NumberFormat>();
function numberFormat(options: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = JSON.stringify(options);
  let format = numberFormats.get(key);
  if (!format) {
    format = new Intl.NumberFormat(LOCALE, options);
    numberFormats.set(key, format);
  }
  return format;
}

/** `S$` for SGD; the ISO code for every other currency. */
export function currencyPrefix(currency: string | null | undefined): string {
  if (!currency) return "";
  return currency.toUpperCase() === "SGD" ? "S$" : currency.toUpperCase();
}

/** A plain number: `1,234`, `0.25` (up to `maxDecimals`, trailing zeros dropped). */
export function formatNumber(value: Amount, maxDecimals = 0): string {
  if (!isNumber(value)) return MISSING;
  return numberFormat({ maximumFractionDigits: maxDecimals }).format(value);
}

export type MoneyOptions = {
  /** Fixed decimals (default 0). */
  decimals?: number;
  /** Prefix `+` on positive amounts (deltas). Zero never gets a sign. */
  signed?: boolean;
};

function withPrefix(abs: string, currency: string | null | undefined, sign: string): string {
  const prefix = currencyPrefix(currency);
  return `${sign}${prefix ? `${prefix} ` : ""}${abs}`;
}

/** `S$ 1,234`, `-S$ 1,234`, `+S$ 1,234` (signed), `—` when missing. */
export function formatMoney(value: Amount, currency: string | null | undefined, options: MoneyOptions = {}): string {
  if (!isNumber(value)) return MISSING;
  const decimals = options.decimals ?? 0;
  const formatted = numberFormat({ minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  const abs = formatted.format(Math.abs(value));
  // Rounding can turn -0.4 into "0": a zero shows no sign.
  const isZero = Number(abs.replace(/,/g, "")) === 0;
  const sign = isZero ? "" : value < 0 ? "-" : options.signed ? "+" : "";
  return withPrefix(abs, currency, sign);
}

/** A signed delta: `+S$ 1,234`, `-S$ 1,234`, `S$ 0`. */
export function formatSignedMoney(value: Amount, currency: string | null | undefined, options: Omit<MoneyOptions, "signed"> = {}): string {
  return formatMoney(value, currency, { ...options, signed: true });
}

/** Compact money for chart labels: `S$ 35K`, `S$ 1.2M`, `-S$ 950`. */
export function formatMoneyCompact(value: Amount, currency: string | null | undefined, options: { signed?: boolean } = {}): string {
  if (!isNumber(value)) return MISSING;
  const abs = numberFormat({ notation: "compact", maximumFractionDigits: 1 }).format(Math.abs(value));
  const isZero = abs === "0";
  const sign = isZero ? "" : value < 0 ? "-" : options.signed ? "+" : "";
  return withPrefix(abs, currency, sign);
}

export type PercentOptions = {
  /** Decimals (default 1). */
  decimals?: number;
  /** Prefix `+` on positive values. */
  signed?: boolean;
  /** `fraction` (default): 0.123 is 12.3%. `points`: 12.3 is 12.3%. */
  scale?: "fraction" | "points";
};

/** `12.3%`, `+12.3%` / `-4.0%` (signed), `—` when missing. */
export function formatPercent(value: Amount, options: PercentOptions = {}): string {
  if (!isNumber(value)) return MISSING;
  const decimals = options.decimals ?? 1;
  const points = options.scale === "points" ? value : value * 100;
  const formatted = numberFormat({ minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  const abs = formatted.format(Math.abs(points));
  const isZero = Number(abs.replace(/,/g, "")) === 0;
  const sign = isZero ? "" : points < 0 ? "-" : options.signed ? "+" : "";
  return `${sign}${abs}%`;
}

/**
 * A money delta with its percentage: `+S$ 1,234 (+3.1%)`. Both signs come from the
 * same rule, so they read alike on every card. Without a percentage: `+S$ 1,234`.
 */
export function formatDelta(abs: Amount, pct: Amount, currency: string | null | undefined, options: { decimals?: number } = {}): string {
  if (!isNumber(abs)) return MISSING;
  const money = formatSignedMoney(abs, currency, { decimals: options.decimals });
  return isNumber(pct) ? `${money} (${formatPercent(pct, { signed: true })})` : money;
}

/** `good` / `bad` / `""` for a direction (one rule for up and down colours everywhere). */
export function directionClass(value: Amount): "good" | "bad" | "" {
  if (!isNumber(value) || value === 0) return "";
  return value > 0 ? "good" : "bad";
}

const MONTH_PATTERN = /^(\d{4})-(\d{2})$/;

function monthDate(month: string): Date | null {
  const match = MONTH_PATTERN.exec(month);
  if (!match) return null;
  const year = Number(match[1]);
  const mon = Number(match[2]);
  if (mon < 1 || mon > 12) return null;
  return new Date(year, mon - 1, 1);
}

// Month names are spelled out here rather than taken from Intl: ICU versions disagree
// ("Sep" vs "Sept"), and dates must read the same in every browser.
const MONTHS_LONG = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * A `YYYY-MM` month: `September 2026` (long, default), `Sep 2026` (medium), `Sep '26`
 * (short, for chart axes). Anything else is returned as is.
 */
export function formatMonth(month: string | null | undefined, style: "long" | "medium" | "short" = "long"): string {
  if (!month) return MISSING;
  const date = monthDate(month);
  if (!date) return month;
  const year = date.getFullYear();
  const index = date.getMonth();
  if (style === "short") return `${MONTHS_SHORT[index]} '${String(year).slice(2)}`;
  return `${style === "long" ? MONTHS_LONG[index] : MONTHS_SHORT[index]} ${year}`;
}

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

function parseDate(value: string): Date | null {
  // A bare date is a calendar day, not UTC midnight (which would shift west of UTC).
  const date = DATE_ONLY.test(value) ? new Date(`${value}T00:00:00`) : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** `4 Nov 2026` from an ISO date or timestamp; `—` when missing or unparsable. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return MISSING;
  const date = parseDate(value);
  if (!date) return MISSING;
  return `${date.getDate()} ${MONTHS_SHORT[date.getMonth()]} ${date.getFullYear()}`;
}

/** `4 Nov 2026, 14:05` (local time, 24-hour); `—` when missing or unparsable. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return MISSING;
  const date = parseDate(value);
  if (!date) return MISSING;
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  return `${formatDate(value)}, ${hh}:${mm}`;
}

/** The current month as `YYYY-MM` (local time). */
export function currentMonth(now: Date = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

/** An API enum for display: `EXPENSE` -> `Expense`, `CARD_ISSUER` -> `Card issuer`. */
export function formatEnumLabel(value: string | null | undefined): string {
  if (!value) return MISSING;
  const words = value.toLowerCase().split(/[_\s]+/).filter(Boolean);
  if (words.length === 0) return MISSING;
  return [words[0][0].toUpperCase() + words[0].slice(1), ...words.slice(1)].join(" ");
}
