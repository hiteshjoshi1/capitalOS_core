// #124: a live view prices an IBKR holding at IBKR's own statement price only when
// the price job had no usable quote. This "i" says so, and why, on click.
const REASON_TEXT: Record<string, string> = {
  no_quote: "the price job couldn't fetch a quote for it",
  quote_older: "the price job's latest quote is older than IBKR's statement",
  quote_implausible: "the price job's quote is far off IBKR's value (likely a wrong symbol or currency mapping), so it was ignored",
};

export function priceFallbackMessage(symbol: string, reason: string, asOf?: string | null): string {
  const why = REASON_TEXT[reason] ?? "the price job had no usable quote for it";
  const date = asOf ? ` of ${asOf.slice(0, 10)}` : "";
  return `Stale price for ${symbol}: taken from IBKR's statement${date}, because ${why}.`;
}
