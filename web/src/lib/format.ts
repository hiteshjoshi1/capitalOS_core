/**
 * The one formatting library (#150, review #130 finding 7.4 and #131 "Numbers and
 * formatting"). Every page formats money, percentages, months and dates through here.
 *
 * Rules:
 * - A fixed locale (`en-SG`), so output never depends on the browser's locale.
 * - Money is `<prefix> <amount>` with one space: `S$ 1,234`, `USD 1,234`. The sign goes
 *   before the prefix: `-S$ 1,234`, `+S$ 1,234`. So a card's two deltas always print
 *   their signs the same way.
 * - Decimals follow the size of the amount (#254, D-69): whole units from 1,000 up
 *   (`S$ 53,513`), 2 decimals below it (`S$ 12.40`, a price, a small dividend). Zero is
 *   `S$ 0`. A caller can still fix the decimals (`decimals: 2` for transactions and
 *   prices of any size); they are always fixed, never `S$ 53,512.9`.
 * - Compact (`S$ 1.2M`, `S$ 35K`, `S$ 537`) is for chart labels and donut totals only,
 *   never in a sentence or a table.
 * - A missing value is `—`, never `0`.
 * - Dates read `4 Nov 2026`; date-times `4 Nov, 14:05` in the current year and
 *   `4 Nov 2025, 14:05` before it (24-hour, local time).
 * - CSV cells are plain numbers (`1234.50`): `formatCsvNumber`.
 *
 * `__tests__/formatGuard.test.ts` fails on number or date formatting anywhere else
 * (`toFixed`, `toLocaleString`, `Intl.NumberFormat`, ...).
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
  /** Fixed decimals, or `auto` (default): 0 from 1,000 up, 2 below it, 0 for zero. */
  decimals?: number | "auto";
  /** Prefix `+` on positive amounts (deltas). Zero never gets a sign. */
  signed?: boolean;
};

function withPrefix(abs: string, currency: string | null | undefined, sign: string): string {
  const prefix = currencyPrefix(currency);
  return `${sign}${prefix ? `${prefix} ` : ""}${abs}`;
}

/** The decimals an amount is shown with: fixed when asked, else by its size. */
export function moneyDecimals(value: number, decimals: number | "auto" = "auto"): number {
  if (decimals !== "auto") return decimals;
  const cents = Math.round(Math.abs(value) * 100);
  return cents === 0 || cents >= 100_000 ? 0 : 2;
}

/** `S$ 1,234`, `S$ 12.40`, `-S$ 1,234`, `+S$ 1,234` (signed), `—` when missing. */
export function formatMoney(value: Amount, currency: string | null | undefined, options: MoneyOptions = {}): string {
  if (!isNumber(value)) return MISSING;
  const decimals = moneyDecimals(value, options.decimals);
  const formatted = numberFormat({ minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  const abs = formatted.format(Math.abs(value));
  // Rounding can turn -0.004 into "0": a zero shows no sign.
  const isZero = Number(abs.replace(/,/g, "")) === 0;
  const sign = isZero ? "" : value < 0 ? "-" : options.signed ? "+" : "";
  return withPrefix(abs, currency, sign);
}

/** A signed delta: `+S$ 1,234`, `-S$ 1,234`, `S$ 0`. */
export function formatSignedMoney(value: Amount, currency: string | null | undefined, options: Omit<MoneyOptions, "signed"> = {}): string {
  return formatMoney(value, currency, { ...options, signed: true });
}

/** Compact money for chart labels: `S$ 35K`, `S$ 1.2M`, `-S$ 950` (whole units below 1,000). */
export function formatMoneyCompact(value: Amount, currency: string | null | undefined, options: { signed?: boolean } = {}): string {
  if (!isNumber(value)) return MISSING;
  const n = Math.abs(value);
  const abs =
    n < 999.5
      ? numberFormat({ maximumFractionDigits: 0 }).format(n)
      : numberFormat({ notation: "compact", maximumFractionDigits: 1 }).format(Math.max(n, 1000));
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
export function formatDelta(abs: Amount, pct: Amount, currency: string | null | undefined, options: { decimals?: number | "auto" } = {}): string {
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

/** `4 Nov` (no year: an upcoming due date, a recent day); `—` when missing or unparsable. */
export function formatDayMonth(value: string | null | undefined): string {
  if (!value) return MISSING;
  const date = parseDate(value);
  if (!date) return MISSING;
  return `${date.getDate()} ${MONTHS_SHORT[date.getMonth()]}`;
}

/**
 * `4 Nov, 14:05` in the current year, `4 Nov 2025, 14:05` before or after it (local time,
 * 24-hour); `—` when missing or unparsable. A bare date (`2026-11-04`) is a date: `4 Nov 2026`.
 */
export function formatDateTime(value: string | null | undefined, now: Date = new Date()): string {
  if (!value) return MISSING;
  if (DATE_ONLY.test(value)) return formatDate(value);
  const date = parseDate(value);
  if (!date) return MISSING;
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  const day = date.getFullYear() === now.getFullYear() ? formatDayMonth(value) : formatDate(value);
  return `${day}, ${hh}:${mm}`;
}

/** A number for a CSV cell: `1234.50` (fixed decimals, no separators, no prefix); `""` when missing. */
export function formatCsvNumber(value: Amount, decimals = 2): string {
  if (!isNumber(value)) return "";
  return value.toFixed(decimals);
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
