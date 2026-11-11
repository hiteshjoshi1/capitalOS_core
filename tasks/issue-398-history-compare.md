# Issue 398: History: compare two months, and a year-on-year overlay (UX U20, U21)

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/398

## Objective
- Pick two months on History and see what moved net worth between their closes, as a bridge (U20).
- Overlay last year's net worth on the History chart (U21).

## Architecture Decisions
- D-110: the span bridge is the sum of the month bridges A+1 … B; Unexplained closes it exactly.
- The last-year line reuses the timeline API (fetched 12 months further back); no new endpoint.

## Acceptance Criteria
- [x] `GET /dashboard/bridge?from=&to=` adds up exactly; A→C = A→B + B→C line by line; A = B no change; A > B, future, > 60 months refused (422).
- [x] History: "Over time | Compare" view toggle; Compare has two month pickers and the bridge card; phone and desktop.
- [x] "vs last year" checkbox (Total mode) draws a dashed last-year line, legend and tooltip row.

## How To Test
- `docker compose run --rm --no-deps api-dev pytest tests/test_span_bridge.py`
- `cd web && npx vitest run src/__tests__/CompareMonths.test.tsx src/__tests__/WealthHistory.test.tsx`
- History → Compare → Aug → Oct: the lines equal Overview's Sep + Oct bridges added up.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved
