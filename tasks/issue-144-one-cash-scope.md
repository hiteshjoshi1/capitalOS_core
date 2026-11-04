# Issue 144: One cash scope, one allocation/geography total, D-21 price rules for every holding and dividends

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/144

From the technical review in #130, findings 2.4, 2.5, 2.6, 2.7, 2.8 and 2.10.
Based on #189 (issue #180: card accounts never count as cash) and #187 (issue #142:
valuation goldens and invariants); the PR's diff includes them until they merge.

## Objective
- Cash is one figure: the Cash page, its trend, the summary's cash by currency,
  allocation, geography and the cash freshness all read the same cash as net worth.
- Every breakdown (platform allocation, the summary's geography, geography
  exposure) adds up to the same gross assets as net worth.
- Every holding (not only IBKR's) and the dividend yields follow D-21's price rule;
  a holding with no market value is valued at cost; a failed crypto refresh no
  longer rewrites the newest snapshot's prices in place.

## Architecture Decisions
- `_cash_positions(db, anchor, base_currency, user, scope=net_worth|cash_page)` in
  `api/app/routers/dashboard.py` is the one cash function. Scope `net_worth`: every
  non-card account's cash-type balance rows, except NAV accounts (IBKR Flex), whose
  cash is the NAV's cash, split by currency with the broker cash rows of the NAV's
  own report date; any part those rows don't cover is in the NAV's base currency,
  so the entries always add up to the NAV's cash. Scope `cash_page` adds stablecoins.
  Net worth, `_cash_balances`, `_cash_deposits`, `_cash_trend` (through
  `_cash_balances`), History rollups (through net worth), allocation, geography and
  the cash freshness read it.
- Base currency of a cash row: broker cash (IBKR) is `balance_base` in the Flex base
  currency (`account_base_currency`, now returned by `canonical_account_balance_rows`
  for broker rows), the same figure as the NAV; every other balance is
  `balance_local` in its own currency at the anchor rate (D-30). The double
  conversion of IBKR cash (2.4) and the "already converted" foreign-currency upload
  (2.8) both go away. No migration (the stored `balance_base` stays as written).
- `api/app/portfolio/position_pricing.py` holds the price rule for every holding:
  `latest_quotes` (deterministic tie-break between sources: newest `ts`, then source,
  then id), `price_position` (D-21: a quote at least as recent as the holding's
  report date and within 2x of its statement value; else the statement value with
  `no_quote | quote_older | quote_implausible`; no market value: cost, flagged
  `valued_at_cost`, and no 2x check against a cost). The dashboard and
  `dividends._latest_asset_market_values` use it.
- The summary's geography is derived from `_geography_exposure` at the same anchor
  (crypto included, shares of gross assets). `/dashboard/geography-exposure` values a
  completed month at its statements (no live overlay), like that month's net worth.
  Allocation and geography take crypto from the same wallet valuation as net worth.
- `refresh_latest_snapshot_prices` (after a failed holdings refresh) writes a new
  prices-only snapshot dated today (holdings copied, `prices_only` and the source
  snapshot in `source_versions`), and marks History dirty from today only. If the
  newest snapshot is already today's it is repriced in place. No fresh price: nothing
  is written (it used to re-stamp old prices as fresh). `refresh.py` is untouched, so
  #156 (PR #186) merges cleanly.

## Acceptance Criteria
- [x] Invariant tests from the harness pass: the five #144 strict xfails (and #180's,
      fixed by #189) pass and their markers are removed; #140, #143 and the FX-cache
      xfail stay strict xfails.
- [x] One cash function with explicit scope and base currency.
- [x] All breakdowns from one state; they sum to net worth (+ liabilities).
- [x] One quote selection for all holdings and dividends, deterministic ranking.
- [x] Real cost fallback with a flag (`valued_at_cost`).
- [x] Crypto price refresh writes a new snapshot.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_valuation_invariants.py tests/test_valuation_golden.py tests/test_one_cash_scope.py tests/test_crypto.py tests/test_dashboard.py -q`
- `cd web && npx vitest run src/__tests__/priceFallback.test.ts src/__tests__/StockHoldings.test.tsx`
- `make verify`

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `pr`
- Workflow Status: `shipped`
- Provider/Model: `claude-code/claude-opus-5-5`
- Last Updated: `2026-11-04`

## Deterministic Gate Results (Codex Mutable)
- `make verify`: exit 0 (backend 726 passed, 1 skipped, 3 xfailed; frontend 313 passed; lint, typecheck pass).
- Goldens regenerated with `make golden-update`; every changed number is explained in the PR.

## Extra Files Changed (Codex Mutable)
- `api/app/crypto/valuation.py` — reason: finding 2.10 (failed refresh rewrote history).
- `web/src/lib/priceFallback.ts`, `web/src/components/PriceFallbackInfo.tsx`,
  `web/src/routes/StockHoldings.tsx` — reason: the "i" now names the holding's own
  platform's statement (D-21 applies to every holding).

## Human Action Summary (Codex Mutable)
- Next expected action: review the golden diff and the proposed decision (D-n extending D-21) in the PR.
- Open questions:
  - Should `/dashboard/platform-allocation` and `/dashboard/stock-exposure` honour `month` (2.5 notes they ignore it)? Left as is.
