# Issue 243: Cash Flow: month to date vs the same day last month, formatted summary, drop Burn rate

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/243

## Objective
- Stop comparing a partial month with a full one on Cash Flow (#131 review item 7): the open
  month is "month to date (day X of Y)" and is compared with the previous month up to the same day.
- Print the "What changed" sentence with the shared money formatter, not raw numbers.
- Drop the Burn-rate tile (always 1 − savings rate).

## Architecture Decisions
- D-63 (docs/decisions.md): a new `analytics.comparison` object on `/spending/cash-flow-detail`
  carries the like-for-like figures (basis, day X of Y, the prior window, inflows/outflows/net and
  savings rate both sides, changes, category deltas and deterioration drivers). The existing
  full-month fields keep their meaning (D-24: no silent field-meaning change); `burn_rate` stays.
- The window: open month = today's month in the user's timezone (`_app_today`, D-49); prior days
  1..min(X, prior month length); rows dated by the card-month rule (`_transaction_in_month_window`).
  Past and future months: whole month vs whole month (the same rows and numbers as before).
- The page composes its sentence from `comparison` with `lib/format.ts`
  (`web/src/lib/cashFlowPeriod.ts`); the API's `answers` text is unchanged.

## Acceptance Criteria
- [x] Open month labelled "month to date (day X of Y)"; hero, KPI tiles, narrative, drivers and
      "Categories trending up" compare with the previous month's days 1..X (clamped).
- [x] Past month: whole vs whole, existing figures unchanged (golden diff is additions only).
- [x] Narrative formatted with the shared formatter.
- [x] Burn-rate tile removed; `burn_rate` still in the response.
- [x] Backend tests: month-length edges (31st vs a 30-day month, 30/31 Mar vs February, leap
      February, 30 Nov vs October, year boundary) and timezone boundaries (same instant, different
      day in New York and Singapore; the open month follows the user's today).
- [x] Frontend tests: labels and formatting.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_cash_flow_month_to_date.py tests/test_valuation_golden.py` (worktree project).
- `cd web && npx vitest run src/__tests__/CashFlowDetail.test.tsx src/__tests__/cashFlowPeriod.test.ts`.
- `make verify`.
- Test instance: open Cash Flow for the open month; check the "vs 1–X <prior month>" figures against
  the previous month's transactions up to day X; a past month should read as before.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `pr-open`
- Workflow Status: `shipped`
- Provider/Model: `anthropic/claude-opus-5-5`
- Last Updated: `2026-11-06`

## Deterministic Gate Results (Codex Mutable)
- `lint`: pass (make verify)
- `typecheck`: pass (tsc, mypy)
- `tests`: pass (make verify: backend 946 passed, 25 skipped; frontend 463 passed in 58 files)
- `e2e`: skip
- `api-smoke`: checked by hand on the worktree stack with demo data (`/spending/cash-flow-detail`)
- `policy-checks`: pass

## Extra Files Changed (Codex Mutable)
- `api/tests/golden/valuation/mid.json` — reason: the new `analytics.comparison` object appears in
  both Cash Flow responses; no existing value changed (diff is insertions only).

## Human Action Summary (Codex Mutable)
- Next expected action: test on a test instance; merge on Hitesh's word.
- Open questions:
  - The other `answers` sentences (Expenses hero "Most outflows went to Rent (64.6% / 2500)", Income
    hero) still print raw numbers; not in this issue's scope.
  - The Cash bridge for the open month (#131 item 7's last part) is not changed here.
  - No year-ago figure is shown on Cash Flow, so no same-day YoY was added.

## Automation Log (Mutable)

<!-- MACHINE_RENDERED_START -->
## Execution Journal
_Not rendered yet._
<!-- MACHINE_RENDERED_END -->
