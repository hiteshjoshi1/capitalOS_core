# Issue 342: Wallets: hide spam/unknown tokens by default

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/342

## Objective
- The crypto lists show real holdings; the airdropped tokens nobody prices are hidden, one toggle away.

## Architecture Decisions (D-87)
- `app/crypto/token_visibility.py`: a contract token is **unknown** when no snapshot of the user's own
  wallets ever priced it and it isn't allowlisted; natives/exchange balances never are. Per-user override
  table `crypto_token_visibility` (migration 083: shown / hidden; no row = automatic). Key = #331 token_key
  (chain + lower-cased contract), never symbol.
- API (fields only added): `/crypto/summary` top_holdings get contract_or_mint, token_key, unknown_token,
  visibility_override, hidden, hidden_reason, plus `hidden_token_count`; `top5_holdings` skips hidden;
  `/crypto/tokens` items the same plus `hidden_count`; `GET/PUT /crypto/token-visibility` (per user).
- Crypto Holdings: hidden tokens left out; "Show hidden (N)" toggle; "Not spam" / "Hide" / "Show" per
  contract token; the dust toggle is unchanged. Valuation untouched.

## Real data (read-only, 2026-11-09)
- 301 latest wallet items: 204 hidden (173 distinct tokens), 68 distinct contract tokens kept, 13 native /
  exchange items. No priced item hidden; hidden value US$ 0.

## Tests
- `tests/test_token_visibility.py` (7): never-priced hidden; priced, once-priced, allowlisted and native kept;
  same symbol on another chain/contract; overrides win and reset; bad input; summary flags + totals unchanged;
  per-user overrides. CryptoHoldings.test.tsx: toggle + "Not spam" call.

## After deploy
- `make deploy` applies migration 083 (verified backup first). Nothing else to run.

<!-- IMMUTABLE_PLAN_END -->
