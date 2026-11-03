# Issue 138: History: invalidate monthly rollups from the earliest changed date on every import

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/138

## Objective
- History (wealth_monthly_rollups) shows back-dated imports without pressing "Generate history".
- A finished month is stored at its own anchor, never at the month before's; the open month isn't stored (the live "now" point covers it).

## Architecture Decisions
- Dirty marks: new `wealth_rollup_dirty(user_id, from_date, generation, marked_at, reason)` (migration 070) plus `wealth_monthly_rollups.input_generation`. Write paths call `mark_rollups_dirty(db, earliest_changed_date, ...)` in the same transaction as their write; `from_date` keeps the minimum, `generation` goes up on every mark. A row is stale when `anchor_date >= from_date` and `input_generation < generation`. Generations (not timestamps) so a recompute racing an uncommitted import can't be counted as fresh.
- Recompute: lazily in the timeline GET (every stale month in the requested range, no cap; writes and commits only when something is stale, so a steady-state read is still a pure read and doesn't invalidate the #147 cache), and in a scheduler hook after IBKR Flex and crypto refresh jobs (all stale stored rows, all currencies). After a recompute the mark moves to the earliest row still stale (other currency / out of range) or is cleared.
- Only completed months (own anchor passed) are stored. On read, provisional rows of open months are deleted, rows stored at another anchor (old rule, SNAPSHOT_DAY change) are recomputed, and missing completed months from the user's first stored month on are filled (month rollover).
- Changes dated after the latest completed anchor mark nothing. Daily quotes never change past months (snapshot rollups use `price_overlay=False`), so the quote job marks nothing.
- Additive `now.uploads` on the timeline response: the open month's upload ticks move to the "now" marker.

## Acceptance Criteria
- [x] After a back-dated import, History shows the new value for affected months without pressing a button (test).
- [x] After a month ends, its row is recomputed at its real anchor (test with frozen clock).
- [x] No provisional current-month row is stored; old-rule rows are fixed on read.
- [x] Dirty mark cleared after recompute (only up to what was recomputed).
- [x] Works with the #147 valuation cache (no stale cached value after an import; steady-state read writes nothing).

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_wealth_rollup_invalidation.py tests/test_wealth_timeline.py -q`
- `cd web && npx vitest run src/__tests__/WealthHistoryChart.test.tsx src/__tests__/WealthHistory.test.tsx`
- `make verify`

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `lint`: pass — `make verify` (ruff, eslint, pinned refs)
- `typecheck`: pass — mypy (101 files), tsc
- `tests`: pass — backend 514 passed, frontend 42 files / 285 tests
- `api-smoke`: pass — isolated Postgres stack: migration 070 applied; mark/backfill/import/refresh/settle exercised against Postgres with a synthetic user, then `make instance-drop`
- `policy-checks`: pass

## Extra Files Changed (Codex Mutable)
- `web/src/components/WealthHistoryChart.tsx`, `web/src/lib/api.ts` — reason: the open month no longer has a stored point; its upload tick and tooltip move to "now", and the obsolete "recent uploads apply next month" caveat is removed.
