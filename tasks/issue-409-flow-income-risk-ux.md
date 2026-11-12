# Issue 409: Cash Flow, Income & Risk UX (U15, U16, U18)

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/409

## Objective
- Cash Flow: compare each spending category with the same month last year, and show a twelve-month savings-rate line (U15).
- Income: when no dividend yield is stored, project expected dividends from the last 12 months' payments, and say which method was used (U16).
- Risk: show how each risk figure moved since last month (U18).

## Architecture Decisions
- D-113: additive fields on existing endpoints (`cash-flow-detail` analytics `year_over_year` + `savings_rate_trend`; expected dividends `method` + per-method counts); Risk deltas computed client-side from last month's risk summary.

## Acceptance Criteria
- [x] Cash Flow → Expenses shows "Vs. <last year's month>" with category moves both ways; open month compared day for day; "no data" when last year is empty.
- [x] Cash Flow → Overview shows the twelve-month savings rate, months without income marked.
- [x] Income's expected tile names the method; companies projected from past payments carry a "past 12 months" tag.
- [x] Risk tiles and the platform section show "+x.x pts vs <month>"; concentration rises flagged.

## How To Test
- `docker compose run --rm --no-deps api-dev pytest tests/test_cash_flow_year_over_year.py tests/test_dividend_projection.py`
- `cd web && npx vitest run src/__tests__/flowIncomeRisk409.test.tsx src/__tests__/WealthRisk.test.tsx`
- `make verify`, `make e2e-smoke`.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved
