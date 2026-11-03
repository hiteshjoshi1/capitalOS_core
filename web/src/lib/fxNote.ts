import type { FxStatus } from "./api";

/** One short sentence about FX gaps behind the totals (#139), or null. */
export function fxNoteText(...sources: Array<FxStatus | null | undefined>): string | null {
  const missing = new Set<string>();
  const stale = new Set<string>();
  for (const source of sources) {
    for (const currency of source?.fx_missing_currencies ?? []) missing.add(currency);
    for (const currency of source?.fx_stale_currencies ?? []) stale.add(currency);
  }
  for (const currency of missing) stale.delete(currency);
  const parts: string[] = [];
  if (missing.size > 0) {
    parts.push(`Excludes amounts in ${[...missing].sort().join(", ")}: no exchange rate available.`);
  }
  if (stale.size > 0) {
    parts.push(`Uses older exchange rates for ${[...stale].sort().join(", ")}.`);
  }
  return parts.length > 0 ? parts.join(" ") : null;
}
