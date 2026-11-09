# Issue 331: Crypto prices: a held coin is never worth S$ 0 at a period start

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/331

## Root cause (real data, read-only)
- The "5 SOL with no price at the 30 Oct anchor" were never SOL: they're an **ERC-20 token named
  "SOL" on the Ethereum wallet** (contract 0x209b…1258). No price source (DefiLlama, CoinGecko)
  knows it, so it has no price in any snapshot, then or now.
- `bridge._crypto_holdings` summed **quantities by bare symbol**, so on 8 Nov the 5 unpriced "SOL"
  plus the Solana wallet's 56.86 real SOL looked like 61.86 SOL worth the real wallet's value.
  At the start the 5 counted as SOL worth 0. The price/quantity split left a phantom S$ 525
  ("Holdings without a price or quantity").
- Separately: the Nov start uses the 29 Aug snapshots, the newest before 1 Nov (the #329 stale-start
  issue), and 90 snapshot items of tokens that *are* priced elsewhere had no price on 5–8 Nov (from
  provider gaps).

## Changes
- **Bridge (one line in `_crypto_holdings`):** an unpriced item adds no quantity. Real-data
  read-only check: the S$ 525 unsplit part is gone; the Solana wallet's full value now shows under
  crypto moved (#330 turns it into "Newly tracked"). Unexplained's total is unchanged.
- **Carry at valuation time** (`carry_prices`, called by `latest_wallet_valuation`): an unpriced
  item takes the newest price of the same token stored within **7 days** before its snapshot date,
  in the user's own wallets, marked `carried:<date>`. Never a later price, never invented.
- **Back-fill** (`make crypto-price-backfill`, `GET /crypto/price-backfill-plan`,
  `POST /crypto/price-backfill`): DefiLlama historical price at noon UTC of the snapshot date for
  unpriced items whose token is priced somewhere; one request per date (coins chunked), newest
  first, capped (`CRYPTO_PRICE_BACKFILL_MAX_REQUESTS`, 30); item and snapshot total updated; History
  marked dirty from the earliest date per wallet; a `job_runs` row ("Crypto price back-fill").
  Per user (snapshots aren't shared), so not admin-only.
- D-84.

## Real data (read-only)
- Plan: 4 requests (5, 6, 7, 8 Nov), 90 items; 1,174 items of tokens no provider prices skipped.
- One real DefiLlama historical call (30 Oct, 3 coins), nothing written: SOL $96.44, ETH $2,233.98,
  stETH $2,233.24.

## Tests
`api/tests/test_crypto_price_backfill.py` (11): keys and coin ids; carry inside the window, the
newest earlier, never later; nothing beyond 7 days or for a never-priced token; never another
user's wallets; the bridge same-symbol skew; the plan (known tokens only, newest first); the cap;
dry run fetches nothing; apply stores prices, re-sums totals, marks History, records a run, then
nothing left; a failed request counted, the rest go on; endpoints scoped to the caller.

<!-- IMMUTABLE_PLAN_END -->
