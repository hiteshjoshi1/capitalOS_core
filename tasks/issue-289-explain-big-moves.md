# Issue 289: Overview: explain big moves next to the headline delta

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/289

## Objective
- When the headline jumps because of data (an import, a missing rate, a price fallback, a new
  position), say so next to the delta, so a +304% swing from data problems isn't read as a gain.

## Architecture Decisions
- One backend list per period, `app/valuation/move_causes.py`, computed inside the month bridge
  (D-60) from the facts the bridge already values, and returned as an added field
  `move_causes` on `GET /dashboard/month-bridge`. Overview reads it from the bridge fetch it
  already makes (shared resource key); History's drill-down fetches that month's bridge only for
  a month it flagged (unusual or catch-up).
- Causes: `first_statement` (an account not in the start figure, sized at its end value),
  `catch_up` (an account's data jumps > 45 days, sized at its change less the price/FX effect on
  its holdings), `statement` (a new statement moved an account by ≥ max(S$ 1,000, 20% of the
  change) other than the market), `new_position` (a holding not held at the start, same size
  rule, in an account that was), `fx_gap` (D-30, no size, always significant), `price_fallback`
  (D-21, live holdings at their statement price: context, never significant).
- Big move = |change| ≥ 5% of the start (never without a baseline). `none_reason` = "No data cause
  found: a market move" for a big move with no significant cause. Overview shows the note for a
  big move or any significant cause; History shows it for every month it flagged.
- `_Holding` gains `as_of` (statement date) and `fallback_reason` (D-21), both defaulted.

## Acceptance Criteria
- [x] A period with a known data cause shows it next to the delta (Overview hero, History drill-down).
- [x] Works at 375px (wrapping list, no fixed widths).
- [x] Tests per cause and for "none" (backend `test_move_causes.py`; vitest `MoveCauses.test.tsx`,
      `WealthDrilldownPanel.test.tsx`).

## How To Test
- `docker compose run --rm --no-deps api-dev pytest tests/test_move_causes.py tests/test_month_bridge.py`
- `cd web && npx vitest run src/__tests__/MoveCauses.test.tsx src/__tests__/WealthDrilldownPanel.test.tsx`

<!-- IMMUTABLE_PLAN_END -->
