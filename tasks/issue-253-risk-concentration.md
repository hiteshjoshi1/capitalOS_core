# Issue 253: Risk: largest position across asset classes, no red for low concentration, currency and platform concentration

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/253

## Objective
- Risk's largest position and top N are the same positions, with the same shares, as Overview's "Largest positions" (every asset class; #131: Overview said ETH, Risk a stock).
- Low concentration is never coloured as bad: only an upper threshold warns, and the thresholds are the user's to change.
- Two missing views: currency exposure and platform (custodian) concentration, at the page's one point in time (D-61).

## Where the difference came from (finding)
- `/dashboard/risk-summary.top_holdings` already had every class `/summary.top_holdings` has (stocks, funds and wallet tokens; there are no CASH rows). `web/src/lib/risk.ts` dropped CRYPTO (and CASH) before ranking and re-sorted ties by symbol. Overview shows `summary.top_holdings.slice(0, 4)` as served. Nothing needed adding to the response for positions.
- Top N was "in band" (green) inside 35–55% and "out of band" (red) outside it, so 20% (well diversified) was red.

## Architecture Decisions
- **D-68.** Positions: `risk.ts` ranks `top_holdings` as served (stable sort by value, so ties keep the server's order) and shows each row's `percent_of_networth`, the figure Overview formats; top N sums values over `view_net_worth.total`.
- **Upper thresholds only.** States are `ok` (no colour) / `warn` (amber, above the threshold) / `muted` (no data); "bad" is gone. Defaults in `lib/risk.ts`: largest position 15%, top N 50% (of net worth), one platform 50% (of gross assets). Each card states its rule ("Above 15%: concentrated · Change in Settings").
- **Thresholds per user, server-side**: three nullable `user_preferences` columns (migration 080, CHECK 0 < x <= 100; NULL = the default), `GET`/`PUT /dashboard/risk-thresholds` (`app/services/risk_thresholds.py`; PUT replaces, null resets one). Settings gets its own card (`components/RiskThresholdsCard.tsx`); it saves through the same `useApiResource` key the Risk page reads. `/auth/preferences` is untouched (#252 may add a Settings section too).
- **Currency exposure** (`risk-summary.currency_exposure`, `valuation/exposure._currency_exposure`): net worth at `view_anchor`, by currency: stocks/funds by the currency each holding trades in (`_stock_exposure` gains `by_currency`, the same values as its country split, an IBKR NAV split by its holdings), cash by its currency (`_cash_positions`), USDC/USDT as USD, other crypto as one `CRYPTO` row (not a currency), and each card's liability off the card's own currency (`_credit_card_liability_details` entries gain `currency`). Items add up to `view_net_worth.total`; `percent` is the share of net worth.
- **Platform concentration** (`risk-summary.platform_concentration`): `_platform_allocation` at `view_anchor`, the Overview platform donut's split (gross assets), so the two never differ.
- Only fields added (`RiskSummaryResponse.currency_exposure`, `.platform_concentration`); TS types mirror them.

## Acceptance Criteria
- [x] Largest position / top N over every asset class, equal to Overview's largest positions (contract test).
- [x] Only an upper threshold warns; thresholds editable in Settings, persisted per user, defaults in `lib/risk.ts`.
- [x] Currency exposure (stablecoins as USD) and platform concentration cards, same point in time as the page.
- [x] `test_one_number_contract.py` extended: Risk's ranked positions and shares = Overview's first four, top 3/5 equal, crypto present when the headline has crypto; currency exposure splits the headline (each part sums to its component; stablecoins only in USD, other crypto only in CRYPTO); platform concentration = `/dashboard/platform-allocation`.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_risk_concentration.py tests/test_one_number_contract.py tests/test_lean_payloads.py tests/test_past_months_history.py`
- `cd web && npx vitest run src/__tests__/risk.test.ts src/__tests__/WealthRisk.test.tsx src/__tests__/RiskThresholdsCard.test.tsx`
- `cd web && npx playwright test` (incl. mobile-no-overflow; Risk and Settings also checked at 340px).
- On a test instance with the real data: Risk's largest position and its share equal Overview's first "Largest positions" row for the same month; the currency rows add up to the net worth shown under Cash buffer; the platform rows equal Overview's platform donut.

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
- Last Updated: `2026-11-06`

### What changes, on the demo data (dev stack, 6 Nov 2026, SGD, live)
- Largest position: 0700, 16.6% (unchanged; it is also Overview's first row). Now amber with "Above 15%: concentrated" instead of "Comfort threshold".
- Top 5: 42.9% (0700, 9988, 0388, D05, U11) → **44.5%** (0700, 9988, 0388, **ETH**, D05), the same five as Overview's list; no colour (below 50%), was green "in band". Top 3 unchanged (36.7%).
- New: currency exposure HKD 36.7%, USD 36.1% (incl. S$ 498K stablecoins), SGD 19.1% (less the card balance), crypto other than stablecoins 8.2%; platform concentration IBKR 69.6% (amber, above 50%), crypto wallets 11.2%, DBS Vickers 10.9%, banks 4.3% / 2.2% / 1.9% (= Overview's platform donut).

### Golden files
None changed (`risk-summary` is not in the goldens; `_stock_exposure`'s new `by_currency` and the card details' `currency` are internal and not in any response that is).

### Notes
- `migrations/schema.sql` was regenerated by dumping the migrated dev stack with the same `pg_dump` command `scripts/db-schema-check.sh` uses (the only difference from the committed file is 080's columns and constraint): `make db-schema-update` could not create its throwaway container's network on this machine ("all predefined address pools have been fully subnetted"). CI's `postgres` job runs the real check.
- The e2e fixture (`web/tests/e2e/fixtures/demo-api.json`) gained `/dashboard/risk-thresholds` and the two new `risk-summary` fields (platform rows copied from its own platform-allocation entry, currency rows from the demo stack); the rest was not re-recorded.

## Deterministic Gate Results (Codex Mutable)
- see the PR description for the commands and counts.
