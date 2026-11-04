# Issue 170: Spending and dashboard cash flow convert at each transaction's date, not the 1st of the month

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/170

## Objective
- Apply D-30 to cash flow: every income/expense/card transaction converts at the stored FX rate for its own date (7-day lookback), not the 1st of its month.
- A currency with no rate is left out (never 1.0) and the response says so, with the FX note shown where these totals appear.

## Architecture Decisions
- `spending.py`: `_build_month_rate_map` (one `get_rates` per month, at the 1st) becomes `_build_row_rate_map`: one `get_rates_by_date` call over every row's UTC date, so one store read per request range, as dividends do. `_row_base_amount` looks a row up by `rate_date(ts)`. Used by `/spending/summary`, `/spending/cash-flow-detail` (totals, analytics, trend, prior month, cash bridge), `/spending/credit-cards` (spend), `/spending/credit-card-transactions`, `/spending/credit-card-analytics` and the recurring-charges helper.
- `dashboard._cashflow` does the same (it now selects `t.ts`). It stays `valuation_cached(shared=True)`: a missing or stale rate calls `mark_degraded`, so such a result is never shared, and `fx_status()` on `/dashboard/summary` already carries its flags.
- Card credit limits stay at the month-start rate: they are balances, not flows (D-30 values balances at their valuation date).
- The five spending responses gain `fx_incomplete`, `fx_missing_currencies`, `fx_stale_currencies` (additive, `FxStatusFields`); TS types mirror them.
- UI: the existing `FxNote` under the Overview cash-flow card, at the top of the Cash Flow pages, on Liabilities (card spend) and under History's "Income vs spending" chart. Renders nothing when FX is complete.

## Acceptance Criteria
- [x] Two transactions in one month on different dates convert at their own synthetic non-1 rates (summary, cash-flow detail, dashboard cash flow, card analytics/transactions/summary).
- [x] A missing rate is excluded (base_amount 0) and flagged, not 1.0.
- [x] Overview (`/spending/summary`), History (`cash-flow-detail` trend, including a later month's trend), Cash Flow detail and `/dashboard/summary` cash flow agree for the same month.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_cashflow_fx_dates.py -q` (both tests fail on the old code: 2400 vs 2700 income, 744 vs 843 expenses).
- `cd web && npx vitest run src/__tests__/CashFlowDetail.test.tsx src/__tests__/LiabilitiesOverview.test.tsx`.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results
`make verify` could not create its isolated compose network (Docker's address pools were exhausted by parallel worktree stacks), so its steps were run one by one with the worktree's default compose project:
- `lint`: pass — `npm run lint`, `check-pinned-refs.sh`, `test-checkout-guard.sh`, `ruff check app tests`
- `typecheck`: pass — `tsc -b`, `mypy app` (104 files)
- `tests`: pass — backend 582 passed; frontend 45 files / 299 tests passed
- `e2e`: skip
- `api-smoke`: skip

## Extra Files Changed
- None beyond the routers, schemas, API types, the four pages showing these totals, and their tests.

## Human Action Summary
- Next expected action: review PR; batch into a test instance.
- Existing test expectations did not change: the synthetic provider returns the same table for every date, so per-date and month-start conversion agree there. The new test seeds dated rates that differ.
