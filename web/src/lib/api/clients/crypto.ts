// Crypto wallets and holdings: API calls (split out of lib/api.ts, #368).
import { req } from "../http";
import type { CryptoAllowlistItem, CryptoStablecoins, CryptoSummary, CryptoWallet, CryptoWalletInitResponse, TokenVisibility, TokenVisibilityOverride } from "../types/crypto";

export const cryptoClient = {
  cryptoWallets: () => req<CryptoWallet[]>("/crypto/wallets"),
  cryptoWalletInit: (payload: { chain_type: string; chain: string; address: string; label?: string }) =>
    req<CryptoWalletInitResponse>("/crypto/wallets/init", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  cryptoWalletVerify: (payload: { chain_type: string; chain: string; address: string; signature: string; public_key?: string; verification_id?: number }) =>
    req<{ wallet_id: string; status: string }>("/crypto/wallets/verify", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  cryptoWalletVerifyOnchain: (payload: { address: string; signature: string; verification_id: number }) =>
    req<{ wallet_id: string; status: string }>("/crypto/wallets/verify-onchain", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  solanaBlockhash: () => req<{ blockhash: string }>("/crypto/solana/blockhash"),
  solanaSubmit: (payload: { tx_b64: string }) =>
    req<{ signature: string }>("/crypto/solana/submit", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  solanaPreflight: (payload: { tx_b64: string }) =>
    req<{ ok: boolean }>("/crypto/solana/preflight", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  cryptoSummary: (month?: string, baseCurrency = "USD") =>
    req<CryptoSummary>(`/crypto/summary?base_currency=${encodeURIComponent(baseCurrency)}${month ? `&month=${encodeURIComponent(month)}` : ""}`),
  cryptoStablecoins: (month?: string, baseCurrency = "USD") =>
    req<CryptoStablecoins>(`/crypto/stablecoins?base_currency=${encodeURIComponent(baseCurrency)}${month ? `&month=${encodeURIComponent(month)}` : ""}`),
  cryptoRefreshNow: (adminKey?: string) =>
    req<Record<string, unknown>>("/crypto/refresh-now", {
      method: "POST",
      headers: adminKey ? { "X-Admin-Key": adminKey } : undefined,
    }),
  cryptoAllowlist: () => req<CryptoAllowlistItem[]>("/crypto/allowlist"),
  /** #342: show ("Not spam"), hide, or reset (null) one wallet token for this user. */
  cryptoSetTokenVisibility: (payload: { chain: string; contract_or_mint: string; visibility: TokenVisibility | null }) =>
    req<{ overrides: TokenVisibilityOverride[] }>("/crypto/token-visibility", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  cryptoAllowlistAdd: (payload: { chain: string; contract_address: string }) =>
    req<CryptoAllowlistItem>("/crypto/allowlist", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
