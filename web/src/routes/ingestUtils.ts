type PlatformParserConfig = { label: string; parserKey: string };
type SignatureDebug = { header?: unknown; file_kind?: unknown };

const PLATFORM_PARSERS: Record<string, PlatformParserConfig> = {
  IBKR: { label: "Approve as IBKR", parserKey: "ibkr_activity_csv_v1" },
  DBS: { label: "Approve as DBS", parserKey: "dbs_transaction_history_csv_v1" },
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
