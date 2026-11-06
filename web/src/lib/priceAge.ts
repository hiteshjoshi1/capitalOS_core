/**
 * Price age per holding (#224): where a holding's price comes from and how old it is,
 * so a holding priced only from an old upload (#222) never looks like one with today's
 * quote. Staleness itself is the backend's call (`quote_freshness_status`, against
 * QUOTE_STALE_DAYS); this only words it.
 */
import { formatDate } from "./format";
import { formatPlatformLabel } from "./platformLabels";

export type PricedHolding = {
  platform?: string | null;
  latest_trade_date?: string | null;
  price_source?: string | null;
  price_provider?: string | null;
  price_basis?: "quote" | "statement" | null;
  quote_freshness_status?: string | null;
};

// Sources that are a statement's own price, not the price job's quote.
const STATEMENT_SOURCES = new Set(["ibkr_flex", "canonical_snapshot"]);

const PROVIDER_LABELS: Record<string, string> = {
  yfinance: "Yahoo Finance",
  yahoo: "Yahoo Finance",
  finnhub: "Finnhub",
  eodhd: "EODHD",
};

/** `quote` (the price job), `statement` (the holding's statement or upload), or null (no price). */
export function priceBasis(holding: PricedHolding): "quote" | "statement" | null {
  if (holding.price_basis) return holding.price_basis;
  if (!holding.price_source) return null;
  return STATEMENT_SOURCES.has(holding.price_source) ? "statement" : "quote";
}

/** `Sharekhan statement`, `Yahoo Finance`, …: where the shown price comes from. */
export function priceSourceLabel(holding: PricedHolding): string {
  if (priceBasis(holding) === "statement") {
    return holding.platform && holding.platform !== "UNKNOWN"
      ? `${formatPlatformLabel(holding.platform)} statement`
      : "statement";
  }
  const provider = (holding.price_provider ?? holding.price_source?.split("_", 1)[0] ?? "").toLowerCase();
  return PROVIDER_LABELS[provider] ?? (provider || "unknown source");
}

/** A live price: a fresh quote from the price job (the backend's `no_live_price` rule). */
export function hasLivePrice(holding: PricedHolding): boolean {
  return priceBasis(holding) === "quote" && (holding.quote_freshness_status ?? "").toLowerCase() === "fresh";
}

export type PriceAge = { stale: boolean; text: string };

/**
 * `price from 4 Nov 2026, Yahoo Finance`, or on the live month, when older than the
 * quote-stale window, `stale (price from 30 Oct 2026, Sharekhan statement)`. A past
 * month is valued at its statements, so it is never "stale" (#224: freshness only on
 * the live month).
 */
export function holdingPriceAge(holding: PricedHolding, isLive: boolean): PriceAge {
  const source = priceSourceLabel(holding);
  if (!holding.latest_trade_date) {
    return { stale: isLive, text: isLive ? `stale (no price date, ${source})` : `no price date, ${source}` };
  }
  const priceFrom = `price from ${formatDate(holding.latest_trade_date)}, ${source}`;
  const stale = isLive && (holding.quote_freshness_status ?? "").toLowerCase() !== "fresh";
  return { stale, text: stale ? `stale (${priceFrom})` : priceFrom };
}
