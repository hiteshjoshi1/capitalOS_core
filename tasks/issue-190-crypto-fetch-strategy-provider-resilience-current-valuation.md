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
- Add optional EVM portfolio provider:
  - `moralis`: optional EVM wallet token-balance/provider adapter enabled when `MORALIS_API_KEY` is configured; do not make the app depend on a paid plan.
- Provider ordering must be configurable, for example:
  - `CRYPTO_EVM_HOLDINGS_PROVIDERS=moralis,alchemy`
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
- [ ] EVM holdings provider order is configurable and supports optional Moralis plus existing Alchemy fallback.
- [ ] The app runs without a Moralis key and falls back to existing providers.
- [ ] Alchemy `429` or provider failure does not write partial/zero snapshots.
- [ ] Provider retries/backoff/rate limiting are bounded and tested.
- [ ] Dashboard current crypto value and `/crypto/summary` current crypto value come from the same service.
- [ ] UI shows stale holdings/prices clearly when refreshes fail or are older than 24 hours.

## Risks
- Moralis limits/pricing may change; the integration must be optional and configurable.
- Aggregator providers may disagree on token lists/values; tests should assert internal consistency, not provider-specific live prices.
- Current valuation with stale holdings is better than stale snapshot value, but still not proof that holdings are current.
- More providers add configuration and observability requirements.

## Open Questions
- Should Moralis be the preferred EVM holdings provider whenever configured, with Alchemy as fallback?
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
**Current Stage**: `done`
**Workflow Status**: `shipped`

## Workflow Snapshot
- latest_outcome: Pushed branch `feature/issue-190-crypto-fetch-strategy-provider-resilience-current-valuation`.
- next_action: No action required.
- pipeline_version: `v3`
- provider_model: `codex/gpt-5.5`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: Crypto scheduler performs daily refresh and startup catch-up for all active crypto wallets, not just Coinbase.
- Acceptance criterion: Startup catch-up queues work in the background and never blocks dashboard or crypto page load.
- Acceptance criterion: Current crypto valuation uses latest known holdings plus latest available prices.
- Acceptance criterion: API exposes separate holdings freshness and price freshness.
- Acceptance criterion: EVM holdings provider order is configurable and supports optional Moralis plus existing Alchemy fallback.
- Acceptance criterion: The app runs without a Moralis key and falls back to existing providers.
- Acceptance criterion: Alchemy 429 or provider failure does not write partial/zero snapshots.
- Acceptance criterion: Provider retries/backoff/rate limiting are bounded and tested.
- Acceptance criterion: Dashboard current crypto value and /crypto/summary current crypto value come from the same service.
- Acceptance criterion: UI shows stale holdings/prices clearly when refreshes fail or are older than 24 hours.

## Prepare
Checked out `feature/issue-190-crypto-fetch-strategy-provider-resilience-current-valuation` from `main` and verified task file exists.

## Plan Summary
Added configurable holdings/price provider strategy, introduced a read-only current valuation layer using latest complete holdings plus latest available prices, wired dashboard and crypto summary to shared valuation, made startup catch-up cover all active crypto wallets, surfaced separate holdings/price freshness and provider metadata, and verified with required make targets.

### Architecture Decisions
- Added app.crypto.providers with CryptoHoldingsProvider-style adapters for Alchemy, optional Moralis, and Helius while keeping Coinbase exchange ingestion separate.
- Kept Moralis optional: it is only used when MORALIS_API_KEY is configured; configured order defaults to moralis,alchemy and falls back safely.
- Did not add a new valuation table; current valuation is computed from latest complete snapshot items, with background refresh jobs allowed to overlay fresh prices onto latest holdings metadata.
- Stored holdings_as_of and price_as_of in crypto_wallet_snapshots.source_versions to avoid schema churn and preserve existing historical snapshots.
- Kept page reads provider-free; provider calls happen only in scheduler/manual refresh paths.
- Dashboard current net worth and /crypto/summary now use the same crypto valuation helper for current crypto value.

### Acceptance Criteria
- Crypto scheduler performs daily refresh and startup catch-up for all active crypto wallets, not just Coinbase.
- Startup catch-up queues work in the background and never blocks dashboard or crypto page load.
- Current crypto valuation uses latest known holdings plus latest available prices.
- API exposes separate holdings freshness and price freshness.
- EVM holdings provider order is configurable and supports optional Moralis plus existing Alchemy fallback.
- The app runs without a Moralis key and falls back to existing providers.
- Alchemy 429 or provider failure does not write partial/zero snapshots.
- Provider retries/backoff/rate limiting are bounded and tested.
- Dashboard current crypto value and /crypto/summary current crypto value come from the same service.
- UI shows stale holdings/prices clearly when refreshes fail or are older than 24 hours.

### Planned Paths
- `api/app/crypto/`
- `api/app/routers/crypto.py`
- `api/app/routers/dashboard.py`
- `api/app/schemas/dashboard.py`
- `api/tests/test_crypto.py`
- `api/tests/test_dashboard.py`
- `web/src/lib/api.ts`
- `web/src/routes/CryptoHoldings.tsx`
- `web/src/__tests__/CryptoHoldings.test.tsx`
- `config/crypto.env.example`
- `tasks/issue-190-crypto-fetch-strategy-provider-resilience-current-valuation.md`

## Build Summary
Implemented Issue 190 crypto provider resilience and current valuation changes across backend, scheduler, API contract, UI, tests, and env examples.

### Changed Files
- `api/app/crypto/adapters.py`
- `api/app/crypto/ingest.py`
- `api/app/crypto/pricing.py`
- `api/app/crypto/providers.py`
- `api/app/crypto/refresh.py`
- `api/app/crypto/scheduler.py`
- `api/app/crypto/valuation.py`
- `api/app/routers/crypto.py`
- `api/app/routers/dashboard.py`
- `api/app/schemas/dashboard.py`
- `api/tests/test_crypto.py`
- `api/tests/test_dashboard.py`
- `config/crypto.env.example`
- `tasks/issue-190-crypto-fetch-strategy-provider-resilience-current-valuation.md`
- `web/src/__tests__/CryptoHoldings.test.tsx`
- `web/src/lib/api.ts`
- `web/src/routes/CryptoHoldings.tsx`

## Latest Verification
- api-rebuild: PASS (exit 0)
- contract-backend: PASS (exit 0)
- test-backend: PASS (exit 0)
- api-smoke: PASS (exit 0)
- lint: PASS (exit 0)
- typecheck: PASS (exit 0)
- contract-frontend: PASS (exit 0)
- test-frontend: PASS (exit 0)
- e2e: PASS (exit 0)
- orch-test: PASS (exit 0)

## Extra Files Changed
- None

## Agent Run Summary
Implemented Issue 190 crypto provider resilience and current valuation changes across backend, scheduler, API contract, UI, tests, and env examples.

- semantic_intent_achieved: `True`
- provider_model: `codex/gpt-5.5`

### Semantic Checks
- `pass` Crypto scheduler performs daily refresh and startup catch-up for all active crypto wallets, not just Coinbase.: Scheduler _startup_catchup_due and _refresh_due_wallets now inspect all active wallets; test_crypto verifies stale EVM and Coinbase wallets are both refreshed.
- `pass` Startup catch-up queues work in the background and never blocks dashboard or crypto page load.: Startup catch-up remains scheduled via APS DateTrigger; /crypto/summary still returns refresh_triggered false and no DB refresh mutation in tests.
- `pass` Current crypto valuation uses latest known holdings plus latest available prices.: latest_wallet_valuation reads latest complete snapshot items as quantity source; failed holdings refresh test overlays ETH price from 100 to 150 and summary total changes to 300 while holdings_as_of remains old.
- `pass` API exposes separate holdings freshness and price freshness.: /crypto/summary and dashboard freshness include holdings_as_of/price_as_of fields; make crypto-smoke and api-smoke showed those fields in live JSON.
- `pass` EVM holdings provider order is configurable and supports optional Moralis plus existing Alchemy fallback.: CRYPTO_EVM_HOLDINGS_PROVIDERS controls provider order; test_evm_provider_order_falls_back_from_moralis_to_alchemy passes.
- `pass` The app runs without a Moralis key and falls back to existing providers.: Moralis provider is skipped when MORALIS_API_KEY is absent; full backend, frontend, e2e, and smoke suites passed without requiring Moralis.
- `pass` Alchemy 429 or provider failure does not write partial/zero snapshots.: Failed holdings tests assert refresh returns false and no new/lower partial snapshot is persisted.
- `pass` Provider retries/backoff/rate limiting are bounded and tested.: request_with_retry bounds max_attempts and exponential sleeps; test_crypto_http_retry_is_bounded_for_rate_limits asserts exactly 3 attempts and [0.25, 0.5] sleeps for 429.
- `pass` Dashboard current crypto value and /crypto/summary current crypto value come from the same service.: Dashboard _networth_components uses latest_wallet_valuation for current price_overlay path; dashboard test asserts current_net_worth.crypto equals crypto summary total.
- `pass` UI shows stale holdings/prices clearly when refreshes fail or are older than 24 hours.: CryptoHoldings renders separate holdings/prices freshness labels; CryptoHoldings tests assert Stale holdings and Fresh prices (refreshing).

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Ship Result
Pushed branch `feature/issue-190-crypto-fetch-strategy-provider-resilience-current-valuation`.
<!-- MACHINE_RENDERED_END -->
