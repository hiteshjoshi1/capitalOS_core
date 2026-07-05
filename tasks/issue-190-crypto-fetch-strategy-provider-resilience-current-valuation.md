# Issue 190: Crypto fetch strategy, provider resilience, and current valuation

## Objective
- Revamp crypto ingestion and valuation so current crypto net worth is based on latest known holdings plus current prices, not stale wallet snapshot values pretending to be current.
- Make crypto refresh behavior match the stock/IBKR freshness contract: run once per day, record last run time, and if a refresh has not run in the last 24 hours, queue a background catch-up when the API starts without blocking page load.
- Add a provider strategy that reduces dependence on Alchemy for every EVM wallet/chain query and prevents provider failures from corrupting net worth.

## Current State
- Coinbase custodial balances are fetched through Coinbase and scheduled with a startup catch-up.
- Non-custodial EVM wallets use Alchemy for balances/token discovery and DefiLlama/CoinGecko for prices.
- Solana wallets use Helius for balances and prices, with DefiLlama/CoinGecko fallback for prices.
- The scheduler runs a daily crypto refresh at `CRYPTO_REFRESH_HOUR_LOCAL`, but startup catch-up currently checks Coinbase only.
- Current net worth reads the latest wallet snapshot value per wallet. If a wallet snapshot is old, the old value is treated as current.
- A recent Alchemy `429 Too Many Requests` response caused a partial EVM refresh to omit stETH/WSTETH. The immediate bug was fixed to fail closed, but the broader strategy still needs work.

## Provider Notes
- Keep all provider integrations behind narrow interfaces with provider selection via env/config.
- Existing providers:
  - `coinbase`: Coinbase exchange balances and public product prices.
  - `helius`: Solana holdings and prices.
  - `alchemy`: EVM native/token balances and metadata.
  - `defillama`: crypto price lookup.
  - `coingecko`: crypto price lookup fallback.
- Add optional EVM portfolio providers:
  - `moralis`: optional EVM wallet token-balance/provider adapter. Treat as free-tier-capable only when `MORALIS_API_KEY` is configured; do not make the app depend on a paid plan.
  - `debank`: optional EVM portfolio provider only when `DEBANK_ACCESS_KEY` is configured. Do not assume a free tier; implementation must degrade cleanly if no key/plan is present.
- Provider ordering must be configurable, for example:
  - `CRYPTO_EVM_HOLDINGS_PROVIDERS=moralis,debank,alchemy`
  - `CRYPTO_PRICE_PROVIDERS=defillama,coingecko`

## Architecture Decisions
- Separate holdings freshness from price freshness:
  - `holdings_as_of`: when balances/token quantities were last fetched.
  - `price_as_of`: when token prices were last fetched.
- Current net worth should use latest known holdings plus current prices when prices are fresher than holdings.
- If holdings refresh fails, retain the last complete holdings snapshot and surface a stale-holdings warning instead of writing a partial snapshot.
- If price refresh succeeds while holdings refresh fails, update valuation using stale holdings and fresh prices.
- Page reads must not trigger live provider calls. Scheduler/manual refresh jobs do provider work in the background.
- All provider failures must be visible in logs and API freshness fields; no silent fallback to zero holdings.
- The refresh job must be idempotent and safe to rerun.
- Do not delete historical crypto snapshots; they remain useful for trend charts and audit.

## Implementation Plan
- Add a provider abstraction for crypto holdings:
  - `CryptoHoldingsProvider` interface with `provider_name`, supported chains, `fetch_wallet_holdings`.
  - Existing Alchemy adapter becomes one provider, not hardcoded pipeline logic.
  - Add optional Moralis provider if `MORALIS_API_KEY` is present.
  - Add optional DeBank provider if `DEBANK_ACCESS_KEY` is present.
  - Keep Helius as the Solana provider and Coinbase as the exchange provider.
- Add provider selection/config:
  - provider order from env,
  - per-provider enabled/disabled flags,
  - per-provider timeout,
  - per-provider retry/backoff,
  - per-provider rate-limit spacing.
- Add provider-level resilience:
  - bounded retries with exponential backoff for `429`, `5xx`, and transient network failures,
  - per-provider request pacing,
  - metadata caching for token metadata,
  - no snapshot writes when a configured holdings provider returns incomplete or failed data.
- Add current valuation layer:
  - latest complete holdings snapshot per wallet is the quantity source,
  - a price refresh service fetches current prices for those holdings,
  - current crypto net worth uses quantity * latest current price,
  - API returns both `holdings_as_of` and `price_as_of`.
- Update scheduler:
  - daily crypto refresh runs all active crypto wallets once per day,
  - startup catch-up checks all active crypto wallets, not Coinbase only,
  - catch-up queues background jobs when any wallet or price refresh is older than 24 hours,
  - page load remains read-only and non-blocking.
- Update dashboard/crypto APIs:
  - expose wallet-level freshness,
  - expose provider/source used for holdings and prices,
  - flag stale holdings and stale prices separately,
  - dashboard current net worth uses the same crypto valuation service as `/crypto/summary`.
- Update UI:
  - show current crypto value using current valuation,
  - show stale holdings/prices warnings when relevant,
  - show provider and freshness per wallet/token where useful.
- Add docs/env examples:
  - `MORALIS_API_KEY`,
  - `DEBANK_ACCESS_KEY`,
  - `CRYPTO_EVM_HOLDINGS_PROVIDERS`,
  - `CRYPTO_PRICE_PROVIDERS`,
  - provider rate-limit/backoff knobs.

## How To Test
- Run backend unit tests:
  - `docker compose run --rm api pytest tests/test_crypto.py -q`
  - add focused tests for provider selection, provider fallback, stale holdings, fresh prices, and no partial snapshot writes.
- Run scheduler tests:
  - verify startup catch-up queues all stale active crypto wallets, not only Coinbase,
  - verify wallets fetched within the last 24 hours are skipped,
  - verify catch-up is background-only and page reads do not call providers.
- Run provider failure tests:
  - simulate Alchemy `429`,
  - assert no lower/partial snapshot is persisted,
  - assert the last complete holdings snapshot remains the current quantity source,
  - assert a stale-holdings warning is returned.
- Run current valuation tests:
  - seed old holdings with stale prices,
  - seed/fetch fresh prices,
  - assert crypto net worth changes from fresh price overlay while holdings_as_of remains old.
- Run integration smoke:
  - `make api-rebuild`
  - `make api-smoke`
  - `curl "http://localhost:8000/crypto/summary?base_currency=SGD"` and confirm `holdings_as_of`, `price_as_of`, provider, and stale flags are present.
  - `curl "http://localhost:8000/dashboard/summary?month=2026-07&base_currency=SGD"` and confirm dashboard crypto equals the crypto summary current valuation.
- Run frontend tests:
  - `npm --prefix web test -- CryptoHoldings`
  - add assertions for stale holdings/prices indicators and provider labels.

## Acceptance Criteria
- [ ] Crypto scheduler performs daily refresh and startup catch-up for all active crypto wallets, not just Coinbase.
- [ ] Startup catch-up queues work in the background and never blocks dashboard or crypto page load.
- [ ] Current crypto valuation uses latest known holdings plus latest available prices.
- [ ] API exposes separate holdings freshness and price freshness.
- [ ] EVM holdings provider order is configurable and supports optional Moralis and optional DeBank adapters.
- [ ] The app runs without Moralis/DeBank keys and falls back to existing providers.
- [ ] Alchemy `429` or provider failure does not write partial/zero snapshots.
- [ ] Provider retries/backoff/rate limiting are bounded and tested.
- [ ] Dashboard current crypto value and `/crypto/summary` current crypto value come from the same service.
- [ ] UI shows stale holdings/prices clearly when refreshes fail or are older than 24 hours.

## Risks
- Moralis and DeBank limits/pricing may change; integrations must be optional and configurable.
- Aggregator providers may disagree on token lists/values; tests should assert internal consistency, not provider-specific live prices.
- Current valuation with stale holdings is better than stale snapshot value, but still not proof that holdings are current.
- More providers add configuration and observability requirements.

## Open Questions
- Should Moralis or DeBank be the preferred EVM holdings provider once configured?
- Should DeBank be included only after confirming account access/cost for this deployment?
- Should crypto current valuation be persisted in a new table, or computed on read from latest holdings plus cached prices?
- What staleness threshold should the UI use for warning vs error: 24 hours, 48 hours, or per-wallet/provider-specific?

## Out Of Scope
- Deleting old crypto snapshots.
- Replacing Helius for Solana unless it becomes unreliable.
- Rebuilding the full net-worth snapshot model.
- Adding trading, realized P&L, or tax-lot tracking for crypto.

<!-- IMMUTABLE_PLAN_END -->

<!-- MACHINE_RENDERED_START -->
## Execution Journal
_Not rendered yet._
<!-- MACHINE_RENDERED_END -->
