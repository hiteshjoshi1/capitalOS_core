// Shared response pieces: response and request types (split out of lib/api.ts, #368).

/** Additive FX fields (#139) on responses with base-currency totals.
 * fx_incomplete: a value had no FX rate at all and is left out of the totals
 * (never counted 1:1); fx_missing_currencies names those currencies.
 * fx_stale_currencies: converted with a stored rate older than the lookback. */
export type FxStatus = {
  fx_incomplete?: boolean;
  fx_missing_currencies?: string[];
  fx_stale_currencies?: string[];
};
