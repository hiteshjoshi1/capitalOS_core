import { formatDate } from "../lib/format";

type PlatformParserConfig = { label: string; parserKey: string };
type SignatureDebug = { header?: unknown; file_kind?: unknown };

const PLATFORM_PARSERS: Record<string, PlatformParserConfig> = {
  IBKR: { label: "Approve as IBKR", parserKey: "ibkr_activity_csv_v1" },
  DBS: { label: "Approve as DBS", parserKey: "dbs_transaction_history_csv_v1" },
  DBS_CC: { label: "Approve as DBS CC", parserKey: "dbs_credit_card_csv_v1" },
  SHAREKHAN: { label: "Approve as Sharekhan", parserKey: "sharekhan_holdings_xls_v1" },
  DBS_VICKERS: { label: "Approve as DBS Vickers", parserKey: "dbs_vickers_holdings_xls_v1" },
  CITI: { label: "Approve as Citi CC", parserKey: "citi_credit_card_csv_v1" },
  UOB: { label: "Approve as UOB", parserKey: "uob_account_xls_v1" },
  UOB_CC: { label: "Approve as UOB CC", parserKey: "uob_credit_card_xls_v1" },
};

const UOB_HEADERS = [
  "transaction date",
  "transaction description",
  "withdrawal",
  "deposit",
  "available balance",
] as const;

const UOB_CC_HEADERS = [
  "transaction date",
  "posting date",
  "description",
  "foreign currency type",
  "transaction amount(foreign)",
  "local currency type",
  "transaction amount(local)",
] as const;

const DBS_CC_HEADERS = [
  "transaction date",
  "transaction posting date",
  "transaction description",
  "transaction type",
  "payment type",
  "transaction status",
  "debit amount",
  "credit amount",
] as const;

export type { PlatformParserConfig, SignatureDebug };

export function hasOrderedHeaderSubset(header: unknown, expected: readonly string[]): boolean {
  if (!Array.isArray(header)) return false;
  const normalized = header
    .map((value) => String(value).trim().toLowerCase())
    .filter((value) => value && value !== "nan" && !value.startsWith("unnamed:"));
  let nextIndex = 0;
  for (const value of normalized) {
    if (value !== expected[nextIndex]) continue;
    nextIndex += 1;
    if (nextIndex === expected.length) return true;
  }
  return false;
}

export function resolvePlatformParser(
  platform: string | undefined,
  signatureDebug: SignatureDebug | undefined,
): PlatformParserConfig | undefined {
  if (
    signatureDebug?.file_kind === "flat_csv" &&
    (hasOrderedHeaderSubset(signatureDebug.header, DBS_CC_HEADERS) || hasDbsCreditCardMarker(signatureDebug.header))
  ) {
    return PLATFORM_PARSERS.DBS_CC;
  }
  if (
    signatureDebug?.file_kind === "excel" &&
    hasOrderedHeaderSubset(signatureDebug.header, UOB_HEADERS)
  ) {
    return PLATFORM_PARSERS.UOB;
  }
  if (
    signatureDebug?.file_kind === "excel" &&
    hasOrderedHeaderSubset(signatureDebug.header, UOB_CC_HEADERS)
  ) {
    return PLATFORM_PARSERS.UOB_CC;
  }
  if (!platform) return undefined;
  const normalized = platform
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (normalized === "UOB_CC" || normalized === "UOB_CREDIT_CARD") {
    return PLATFORM_PARSERS.UOB_CC;
  }
  if (normalized === "UOB" || normalized.startsWith("UOB_")) {
    return PLATFORM_PARSERS.UOB;
  }
  return PLATFORM_PARSERS[normalized];
}

function hasDbsCreditCardMarker(header: unknown): boolean {
  if (!Array.isArray(header)) return false;
  const joined = header
    .map((value) => String(value).trim().toLowerCase())
    .filter((value) => value && value !== "nan" && !value.startsWith("unnamed:"))
    .join(" ");
  return joined.includes("card transaction details for") && joined.includes("mastercard");
}

/** Today as YYYY-MM-DD in the browser's local timezone (not UTC, unlike toISOString). */
export function todayLocalYYYYMMDD(now: Date = new Date()): string {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

const MONTHS: Record<string, number> = {
  jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12,
};

function validYmd(y: number, m: number, d: number): string | null {
  if (y < 2000 || y > 2100 || m < 1 || m > 12 || d < 1 || d > 31) return null;
  const dt = new Date(y, m - 1, d);
  if (dt.getFullYear() !== y || dt.getMonth() !== m - 1 || dt.getDate() !== d) return null;
  return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

/**
 * A statement date in a file name, as brokers name their exports: `2026_10_02.xls`,
 * `2026-10-02`, `20261002`, `portfolio_23_June_2026.xls`, `23-Jun-2026`. Numeric
 * forms are read year-first only (no DD/MM vs MM/DD guessing). Null if none.
 */
export function dateFromFilename(name: string | null | undefined): string | null {
  if (!name) return null;
  const base = name.replace(/\.[A-Za-z0-9]+$/, "");
  let m = base.match(/(?:^|\D)(20\d{2})[-_. ]?(\d{2})[-_. ]?(\d{2})(?:\D|$)/);
  if (m) return validYmd(Number(m[1]), Number(m[2]), Number(m[3]));
  m = base.match(/(?:^|[^0-9])(\d{1,2})[-_. ]?([A-Za-z]{3,9})[-_. ]?(20\d{2})(?:\D|$)/);
  if (m) {
    const month = MONTHS[m[2].slice(0, 3).toLowerCase()];
    if (month) return validYmd(Number(m[3]), month, Number(m[1]));
  }
  return null;
}

export type AsOfSource = "file" | "user" | "fallback";

/** How the import report says where its snapshot date came from (#141). */
export function describeAsOf(asOfDate: string | null | undefined, source: string | null | undefined): string | null {
  if (!asOfDate) return null;
  const date = formatDate(asOfDate);
  if (source === "file") return `Dated ${date} (from the file)`;
  if (source === "user") return `Dated ${date} (the date you chose; the file states none)`;
  if (source === "fallback") return `Dated ${date} (upload day; the file states no date)`;
  return `Dated ${date}`;
}
