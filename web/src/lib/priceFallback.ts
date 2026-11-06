import { formatDate } from "./format";

// D-21 (#124; every holding since #144): a live view prices a holding at its own
// statement price (IBKR's Flex report, an uploaded holdings file) only when the
// price job had no usable quote. This "i" says so, and why, on click.
const REASON_TEXT: Record<string, string> = {
  no_quote: "the price job couldn't fetch a quote for it",
  quote_older: "the price job's latest quote is older than the statement",
  quote_implausible: "the price job's quote is far off the statement's value (likely a wrong symbol or currency mapping), so it was ignored",
};

export function priceFallbackMessage(
  symbol: string,
  reason: string,
  asOf?: string | null,
  platform?: string | null,
): string {
  const why = REASON_TEXT[reason] ?? "the price job had no usable quote for it";
  const date = asOf ? ` of ${formatDate(asOf.slice(0, 10))}` : "";
  const source = platform && platform.trim() ? platform.trim() : "IBKR";
  return `Stale price for ${symbol}: taken from ${source}'s statement${date}, because ${why}.`;
}
