# Issue 197: IBKR statement FX rates don't clear the FX cache (same gap as #188)

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/197

## Objective
- A corrected IBKR Flex statement FX rate reaches History (and the cached dashboard) on the next read,
  the same as a fresh process computes it.
- An identical re-import changes nothing FX-wise: no cache drop, no FX dirty mark.

## Architecture Decisions
- `_insert_statement_facts` compares each statement rate with the stored IBKR row for the same
  (report date, pair) before replacing it, and returns the earliest date whose rate is new or changed.
  Equal means equal within 1e-12 (Postgres NUMERIC(38,18) pads zeros, SQLite returns a float).
- On a successful import with a changed rate: `fx.forget_rates_from(date)` and
  `mark_rollups_dirty(db, date, reason="fx")` for every user (FX rates are shared, as in
  `fx._store_rows`), then `forget_rates_from` again after the commit (#188's pattern).
  A failed import rolls back, so nothing is dropped or marked.
- Valuation cache (#147): the import's commit bumps the write generation, so shared entries computed
  before it aren't reused; the test checks a cached `/dashboard/summary` after the import equals a
  fresh process.
- Lookup rules unchanged (D-30/D-44): the newest stored day on or before D wins, whatever the source.

## Acceptance Criteria
- [x] New or changed statement rates drop the FX cache from the earliest changed date (before and after commit).
- [x] History is marked dirty from that date for every user (D-29); identical rates mark nothing extra.
- [x] Test: a corrected statement rate reaches History and the cached dashboard on the next read.
- [x] Test: importing an older Flex report after newer ones leaves the newer dates' rates and History unchanged.
- [x] Test: a statement rate for day D does not override a provider rate for a later day.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_fx.py tests/test_wealth_rollup_invalidation.py tests/test_valuation_invariants.py`
- `make verify`

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results
- New tests without the fix: all 4 fail (stale 1.35 rate served, other user not marked, History stale).
- With the fix: `test_fx.py`, `test_wealth_rollup_invalidation.py`, `test_valuation_invariants.py` pass.
- `make verify`: exit 0 (backend 808 passed, 1 skipped; frontend 394 passed in 55 files; lint + typecheck clean).

## Extra Files Changed
- None outside `api/app/portfolio/ibkr_flex.py` and tests.
