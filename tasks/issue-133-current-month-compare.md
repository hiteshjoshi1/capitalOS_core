# Issue 133: Current month: "vs last month", "vs last year", component changes and movers compare the wrong anchors

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/133

## Objective
- For the current (open) month, "vs last month" must not be 0 by construction, and "vs last year" must span 12 months.
- The numbers next to the live CURRENT NET WORTH headline compare the live value, not a month-end snapshot.

## Architecture Decisions
- Every comparison is like for like. A snapshot value is compared with the completed anchors one and twelve
  months before the month whose anchor it was actually taken at (`_completed_snapshot_month_start`). Past
  months use their own anchor, so their output is unchanged; the open month uses last month's completed
  anchor and now compares with the one before it. Applied to `/dashboard/summary` (`net_worth_change`,
  `net_worth_component_change`, `top_movers`), `/dashboard/net-worth-change` and
  `/dashboard/net-worth-timeline/{month}/movers`.
- The live headline gets its own additive field, `current_net_worth_change` on `/dashboard/summary`: live now vs
  the latest completed month-end anchor (`vs_prev_month`) and that month-end a year earlier (`vs_prev_year`),
  independent of the requested month (the headline is too). The hero on Wealth Overview uses it.
  `net_worth_change` keeps its snapshot meaning. Proposed as a D-n entry in the PR.
- Out of scope: the provisional current-month rollup row (#130 finding 1.2) and the anchor/valuation refactor (#143).

## Acceptance Criteria
- [x] A test with the clock frozen inside the current month shows a non-zero month-on-month change when the data changed.
- [x] `vs_prev_year` spans exactly 12 months.
- [x] Past-month results are unchanged (existing tests pass; a new test checks a past month with the clock in the current month).

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_dashboard.py tests/test_wealth_timeline.py -q`
- `cd web && npx vitest run src/__tests__/WealthOverview.test.tsx src/__tests__/contracts.test.tsx`
- `make verify`

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `lint`: pass — `make verify`
- `typecheck`: pass — `make verify`
- `tests`: pass — backend 481 passed, frontend 285 passed (42 files), `make verify` exit 0
- `e2e`: skip
- `api-smoke`: skip
- `policy-checks`: pass — pinned-refs check in `make verify`

## Extra Files Changed (Codex Mutable)
- `web/src/routes/WealthOverview.tsx`, `web/src/lib/api.ts` — reason: the hero shows the new live comparison field.

## Human Action Summary (Codex Mutable)
- Next expected action: review PR; accept or amend the proposed decision.
- Open questions:
  - The Movers tab on Wealth Overview (current month) now shows last completed month's movers (vs the month
    before) instead of nothing. A live month-to-date movers list would need another additive field.
  - With `SNAPSHOT_DAY` > today's day of month, `_completed_snapshot_anchor_ts` still steps back only one month
    and can return a future anchor (pre-existing; not changed here). The live comparison handles it.
