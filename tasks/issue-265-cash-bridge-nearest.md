# Issue 265: Cash bridge for this month, from the nearest snapshots

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/265

## Objective
- Cash Flow's cash bridge draws mid-month and with month-end statements, instead of
  "needs exact cash snapshots on the 1st".
- It says which dates it actually spans.

## Architecture Decisions
- D-72. `_cash_bridge_span` (`api/app/routers/spending.py`): the newest cash fact (cash-only
  `canonical_snapshot_coverage_as_of`) at or before each anchor. Not available when either is missing,
  when the end isn't newer than the start, or when the start is more than 5 months back (the transactions
  loaded). Flows are those between the two snapshots, with the existing boundary convention.
- New `waterfall` fields: `bridge_available`, `span_start`, `span_end`, `span_basis`. `availability_message` =
  why it can't draw, or null. Existing fields keep their values/meaning (goldens: only the message changed).
- Frontend: `lib/cashBridge.ts` `cashBridgeSpanText`; `CashBridgeSection` draws when available
  (falls back to `boundary_exact` for an older API).

## Acceptance Criteria
- [x] The open month shows the bridge with its real start/end dates (demo: 6 Oct → 6 Nov).
- [x] Past months with exact snapshots are unchanged; month-end statements now draw too.
- [x] Missing, not-newer and too-old starts say why.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_cash_bridge_span.py tests/test_spending.py`
- `cd web && npx vitest run src/__tests__/cashBridge.test.ts`

<!-- IMMUTABLE_PLAN_END -->
