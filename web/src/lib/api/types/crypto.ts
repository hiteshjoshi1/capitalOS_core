// Crypto wallets and holdings: response and request types (split out of lib/api.ts, #368).
import type { FxStatus } from "./common";
import type { MiniTrendPoint } from "./wealth";

export type CryptoWallet = {
  id: string;
  chain_type: string;
  chain: string;
  address: string;
  label?: string | null;
  status: string;
  created_at?: string | null;
  verified_at?: string | null;
};

export type CryptoWalletInitResponse = {
  verification_id?: number;
  chain_type: string;
  chain: string;
  address: string;
  message_to_sign: string;
  message_bytes_b64?: string;
  message_hash?: string;
  nonce: string;
  expires_at: string;
};

export type TokenVisibility = "shown" | "hidden";
export type TokenVisibilityOverride = { chain: string; contract_or_mint: string; visibility: TokenVisibility };

export type CryptoSummary = FxStatus & {
  month?: string;
  is_live?: boolean;
  compare_month?: string | null;
  as_of?: string | null;
  snapshot_day?: number | null;
  snapshot_as_of?: string | null;
  total_crypto_usd: number;
  total_crypto_base: number;
  snapshot_total_base?: number;
  snapshot_total_usd?: number;
  snapshot_delta_base?: number;
  snapshot_delta_pct?: number | null;
  /** Nothing to compare with for compare_month (#224): no_data, or no_fx_rate (D-30). */
  snapshot_missing?: boolean;
  snapshot_missing_reason?: "no_data" | "no_fx_rate" | null;
  base_currency: string;
  eth_exposure_usd?: number;
  eth_exposure_base?: number;
  token_exposure_usd?: number;
  token_exposure_base?: number;
  token_count?: number;
  priced_token_count?: number;
  trend?: MiniTrendPoint[];
  eth: { balance: number; value_usd: number; value_base: number };
  sol: { balance: number; value_usd: number; value_base: number };
  top5_holdings: Array<{
    symbol: string;
    chain: string;
    amount: number;
    value_usd: number;
    value_base: number;
    wallet_id?: string;
  }>;
  top_holdings: Array<{
    symbol: string;
    chain: string;
    amount: number;
    value_usd: number;
    value_base: number;
    asset_class: string;
    wallet_id?: string;
    wallet_label?: string | null;
    wallet_address?: string | null;
    price_usd?: number | null;
    price_change_usd?: number | null;
    price_change_pct?: number | null;
    value_change_base?: number | null;
    value_change_pct?: number | null;
    snapshot_value_base?: number | null;
    snapshot_delta_base?: number | null;
    snapshot_delta_pct?: number | null;
    holdings_as_of?: string | null;
    price_as_of?: string | null;
    holdings_provider?: string | null;
    price_provider?: string | null;
    /** #342: the token's contract/mint and "chain:contract" key (null for a native coin). */
    contract_or_mint?: string | null;
    token_key?: string | null;
    /** Never priced in any snapshot and not allowlisted: likely airdropped spam. */
    unknown_token?: boolean;
    /** The user's own choice: "shown" (not spam), "hidden", or null (automatic). */
    visibility_override?: TokenVisibility | null;
    /** Hidden from the lists by default (unknown, or hidden by the user). */
    hidden?: boolean;
    hidden_reason?: "unknown_token" | "user_hidden" | null;
  }>;
  /** #342: how many of top_holdings are hidden. */
  hidden_token_count?: number;
  wallet_exposure?: Array<{
    wallet_id: string;
    label?: string | null;
    address: string;
    chain_type: string;
    chain: string;
    total_usd: number;
    total_base: number;
    percent?: number;
    holdings_as_of?: string | null;
    price_as_of?: string | null;
    holdings_provider?: string | null;
    price_provider?: string | null;
    stale_holdings?: boolean;
    stale_prices?: boolean;
  }>;
  chain_exposure?: Array<{
    chain: string;
    total_usd: number;
    total_base: number;
    percent: number;
  }>;
  wallet_chain_exposure?: Array<{
    wallet_id: string;
    chain: string;
    total_usd: number;
    total_base: number;
  }>;
  last_refreshed_at: string | null;
  holdings_as_of?: string | null;
  price_as_of?: string | null;
  stale_holdings?: boolean;
  stale_prices?: boolean;
  is_stale: boolean;
  refresh_triggered: boolean;
};

/** One stablecoin row: the same values as its row in `CryptoSummary.top_holdings`. */
export type StablecoinHolding = {
  symbol: string;
  chain: string;
  amount: number;
  value_usd: number;
  value_base: number;
  asset_class: string;
  wallet_id: string;
  wallet_label?: string | null;
  holdings_as_of?: string | null;
  price_as_of?: string | null;
};

/** GET /crypto/stablecoins (#149): the stablecoin rows of /crypto/summary's top_holdings
 * (same month, anchor and FX rate) and their total, for the Cash page. */
export type CryptoStablecoins = FxStatus & {
  month: string;
  is_live: boolean;
  as_of: string;
  base_currency: string;
  /** The symbols counted as stablecoins, in display order. */
  symbols: string[];
  total_base: number;
  holdings: StablecoinHolding[];
};

export type CryptoAllowlistItem = {
  id: number;
  chain: string;
  contract_address: string;
  symbol?: string | null;
  name?: string | null;
  created_at?: string | null;
};
