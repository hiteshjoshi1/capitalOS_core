// Accounts & sources (#318, #309 mock-up B): one row per account, wallet, quote feed and
// FX, with its status and one primary action. Pure: the page passes in the API data.
import type { Account, DataHubUnpricedHolding, SourceFreshnessRow } from "./api";
import { formatPlatformLabel } from "./platformLabels";
import { accountIdOf, localToday, sourceLink } from "./sourceFreshness";

export type SourceType = "bank" | "broker" | "card" | "wallet" | "feed" | "other";

export const SOURCE_FILTERS: { key: "all" | SourceType; label: string }[] = [
  { key: "all", label: "All" },
  { key: "bank", label: "Banks" },
  { key: "broker", label: "Brokers" },
  { key: "card", label: "Cards" },
  { key: "wallet", label: "Wallets" },
  { key: "feed", label: "Feeds" },
  { key: "other", label: "Other" },
];

const TYPE_LABEL: Record<SourceType, string> = {
  bank: "Bank",
  broker: "Broker",
  card: "Card",
  wallet: "Wallet",
  feed: "Feed",
  other: "Account",
};

/** The primary action on a row: a link (Upload / Fix) or something to run (Refresh / Fetch past). */
export type SourceAction =
  | { kind: "link"; label: string; to: string }
  | { kind: "run"; label: string; run: "refresh_ibkr" | "refresh_crypto" | "refresh_prices" | "fx_backfill"; adminOnly: boolean; accountId?: number };

export type SourceRowModel = {
  key: string;
  type: SourceType;
  typeLabel: string;
  name: string;
  /** "DBS · SGD", "Solana", "24 symbols". */
  detail: string;
  freshness: SourceFreshnessRow;
  account?: Account;
  closed: boolean;
  action: SourceAction | null;
  /** Unpriced holdings on this exchange (quote feeds only). */
  unpriced: number;
  /** A carried-forward note from the accounts API (#207). */
  carriedNote?: string;
};

export function sourceType(row: SourceFreshnessRow, account?: Account): SourceType {
  switch (row.kind) {
    case "bank_statement":
      return "bank";
    case "broker_statement":
    case "ibkr_flex":
      return "broker";
    case "card_statement":
      return "card";
    case "crypto_wallet":
      return "wallet";
    case "market_data":
    case "fx":
      return "feed";
    default:
      if (account?.account_type === "BANK") return "bank";
      if (account?.account_type === "CREDIT_CARD") return "card";
      if (account?.account_type === "BROKER") return "broker";
      return "other";
  }
}

function exchangeOf(sourceKey: string): string | null {
  const m = /^exchange:(.+)$/.exec(sourceKey);
  return m ? m[1] : null;
}

/** One primary action per row (#309): Upload a statement, Refresh a feed or wallet,
 * Fix unpriced quotes, Fetch past FX. Closed accounts have none. */
export function primaryAction(
  row: SourceFreshnessRow,
  opts: { closed: boolean; unpriced: number; today?: string },
): SourceAction | null {
  if (opts.closed) return null;
  const today = opts.today ?? localToday();
  const accountId = accountIdOf(row.source_key);
  switch (row.kind) {
    case "ibkr_flex":
      return accountId != null ? { kind: "run", label: "Refresh", run: "refresh_ibkr", adminOnly: false, accountId } : null;
    case "crypto_wallet":
      return { kind: "run", label: "Refresh", run: "refresh_crypto", adminOnly: false };
    case "market_data":
      // #320: the Market data page's "Needs a fix" list, where a ticker can be set.
      if (opts.unpriced > 0) return { kind: "link", label: `Fix ${opts.unpriced}`, to: "/market-data#needs-fix" };
      return { kind: "run", label: "Refresh", run: "refresh_prices", adminOnly: true };
    case "fx":
      return { kind: "run", label: "Fetch past", run: "fx_backfill", adminOnly: true };
    default: {
      const link = sourceLink(row, today);
      return link ? { kind: "link", label: "Upload", to: link } : null;
    }
  }
}

function statusRank(row: SourceRowModel): number {
  if (row.closed) return 3;
  if (row.freshness.status === "overdue" || row.freshness.status === "never_loaded" || row.unpriced > 0) return 0;
  if (row.freshness.status === "no_schedule") return 2;
  return 1;
}

const TYPE_ORDER: SourceType[] = ["bank", "card", "broker", "other", "wallet", "feed"];

/** Rows for the page: what needs you first, then by type and name; closed accounts last. */
export function buildSourceRows(
  freshness: SourceFreshnessRow[],
  accounts: Account[],
  unpriced: DataHubUnpricedHolding[],
  today: string = localToday(),
): SourceRowModel[] {
  const byAccount = new Map(accounts.map((a) => [a.id, a]));
  const unpricedByExchange = new Map<string, number>();
  for (const holding of unpriced) {
    const code = (holding.exchange_code ?? "").toUpperCase();
    if (code) unpricedByExchange.set(code, (unpricedByExchange.get(code) ?? 0) + 1);
  }
  const rows = freshness.map((row): SourceRowModel => {
    const accountId = accountIdOf(row.source_key);
    const account = accountId != null ? byAccount.get(accountId) : undefined;
    const closed = Boolean(account?.closed_on);
    const exchange = exchangeOf(row.source_key);
    const unpricedHere = exchange ? unpricedByExchange.get(exchange.toUpperCase()) ?? 0 : 0;
    const type = sourceType(row, account);
    let detail: string;
    if (account) detail = `${formatPlatformLabel(account.platform)} · ${account.currency}`;
    else if (row.kind === "crypto_wallet") detail = row.platform ? formatPlatformLabel(row.platform) : "Wallet";
    else if (row.kind === "market_data") detail = "Quotes";
    else if (row.kind === "fx") detail = "Exchange rates";
    else detail = row.platform ? formatPlatformLabel(row.platform) : "";
    return {
      key: row.source_key,
      type,
      typeLabel: TYPE_LABEL[type],
      name: row.label,
      detail,
      freshness: row,
      account,
      closed,
      action: primaryAction(row, { closed, unpriced: unpricedHere, today }),
      unpriced: unpricedHere,
      carriedNote: account?.carried_forward_from
        ? `${account.data_month ?? "Last month"} shows data from ${account.carried_forward_from} (carried forward)`
        : undefined,
    };
  });
  return rows.sort(
    (a, b) =>
      statusRank(a) - statusRank(b) ||
      TYPE_ORDER.indexOf(a.type) - TYPE_ORDER.indexOf(b.type) ||
      a.name.localeCompare(b.name),
  );
}

/** The filter and search box: type, then any word in the name, platform or type. */
export function filterSourceRows(rows: SourceRowModel[], filter: "all" | SourceType, search: string): SourceRowModel[] {
  const words = search.toLowerCase().split(/\s+/).filter(Boolean);
  return rows.filter((row) => {
    if (filter !== "all" && row.type !== filter) return false;
    if (words.length === 0) return true;
    const hay = `${row.name} ${row.detail} ${row.typeLabel}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

/** Filters that have at least one row ("Other" only when something is in it). */
export function availableFilters(rows: SourceRowModel[]): typeof SOURCE_FILTERS {
  const present = new Set(rows.map((r) => r.type));
  return SOURCE_FILTERS.filter((f) => f.key === "all" || present.has(f.key));
}
