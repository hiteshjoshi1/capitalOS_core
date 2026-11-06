# Issue 224: Missing data never reads as a value: one Delta component, honest baselines, price age per holding

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/224

## Objective
- A comparison with no baseline says "no comparison: no data for <month>", never a huge delta (UX review #131, top-10 item 2).
- Every delta shows the amount and the % in the same currency, with ▲/▼ as well as one up/down colour pair.
- A holding priced only from an old upload (#222) looks different from one with today's quote; freshness badges appear only on the live month.

## Architecture Decisions
- **One `<Delta>` component** (`web/src/components/Delta.tsx`, helpers in `web/src/lib/delta.ts`), built on `lib/format.ts` (#150). Props: `abs`, `pct` (fraction) or `compareValue` (the baseline amount in the same currency; the % is then computed from it), `baseline` (label), `currency`, `missingReason`, `show` (both/abs/pct), `variant` (inline/chip), `tone` (normal/inverse, for spending where up is bad). It replaces the `HeroMetricCard` chip, the Overview hero delta row and the page-local `formatDelta` copies (Crypto `holdingDelta`, `NetWorthHeroCard`).
- **Colours**: `--delta-up` / `--delta-down` tokens (both themes) map to `--good` / `--bad`; `.delta--up` / `.delta--down` are the only delta classes.
- **"Missing" vs "zero" comes from the backend, additively** (never inferred from `0`):
  - `NetWorthChange` gets `compare_value` and `baseline_missing` (no canonical snapshot at or before the comparison anchor *and* a zero value there). Used by summary `net_worth_change` / `current_net_worth_change` / `net_worth_component_change`, `/dashboard/net-worth-change`, `/dashboard/net-worth-since-update`.
  - Stock holdings: `stock_snapshot_missing` (no position/NAV coverage at the compare anchor and a zero stock total).
  - Cash deposits: `snapshot_missing` (no coverage at the compare anchor and a zero total).
  - Crypto summary: `snapshot_missing` + `snapshot_missing_reason` (`no_data`: no wallet snapshot by the compare anchor; `no_fx_rate`: a USD value but no USD→base rate for that date, D-30).
- **Price age per holding**: each stock holding gets `price_basis` (`quote` = the price job's quote, `statement` = the statement/upload price). Stock holdings get `quote_stale_days` (QUOTE_STALE_DAYS) and `quote_freshness_summary.no_live_price` (live view only; `null` on a past month): holdings with no fresh quote, including statement-only ones (#222).
- **Freshness only on the live month**: Stocks hides the fresh/stale counts, the per-row freshness tags and the "no live price" count on a past month (the price date and source stay). Overview's freshness chips are untouched here: Overview is always live today, and #223 (Overview follows the selected month) owns that page's month plumbing.

## Acceptance Criteria
- [x] Delta with no baseline renders "no comparison: no data for <month>" (frontend test).
- [x] % from the same currency as the amount (frontend test: compareValue path; Crypto holding).
- [x] ▲/▼ and one class pair for up/down (frontend test).
- [x] Stale price marking "stale (price from <date>, <source>)" on table and 375px cards; header count links to Data Hub (frontend tests).
- [x] No freshness badges on a past month (frontend test).
- [x] Backend: `baseline_missing`/`compare_value`, `stock_snapshot_missing`, cash `snapshot_missing`, crypto `snapshot_missing(_reason)`, `price_basis`, `no_live_price` (backend tests; goldens regenerated and reviewed).
- [ ] Hitesh: on the test instance, a past month with no prior data shows "no data for …"; a Sharekhan holding shows its upload date.

## How To Test
- `cd web && npx vitest run src/__tests__/Delta.test.tsx src/__tests__/StockHoldings.test.tsx ...`, `npx tsc -b`, `npx eslint .`.
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_missing_baselines.py tests/test_valuation_golden.py`.
- curl: `/dashboard/summary?month=<m>&compare=prev_month,prev_year` → `current_net_worth_change.vs_prev_year.baseline_missing` is `true` when there's no data a year back.

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

## Deterministic Gate Results (Codex Mutable)
- `make verify` (2026-11-06): pass. Backend 880 passed, 21 skipped (Postgres-only); frontend 57 files / 432 tests; ruff, mypy, eslint, tsc clean.
- Goldens regenerated (`make golden-update`): additions only (the new fields), no figure changed.
- Checked by hand on the isolated demo stack (screenshots, not committed): Overview "VS LAST YEAR: no comparison: no data for Oct 2025"; Stocks header "3 holdings without a live price · Fix in Data Hub"; a past month shows no freshness counts.

## Extra Files Changed (Codex Mutable)
- `web/src/routes/Dividends.tsx`, `CashFlowDetail.tsx`, `LiabilitiesOverview.tsx` — reason: they pass the `HeroMetricCard` chip, which is now a `<Delta>`; converted to the `delta` prop so there is one implementation.

## Human Action Summary (Codex Mutable)
- Next expected action: review the PR, then batch it on the test instance.
- Open questions:
  - Overview freshness chips on a past month: left to #223 (it adds Overview's month).
