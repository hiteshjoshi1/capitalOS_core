# Issue 221: Remove leftover dummy seed data from the real database

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/221

## Objective
- The real-data database no longer holds the dummy demo seed (`migrations/seed_dummy.sql`), above all the DUMMY rows in the shared `prices` table, which can value real users' past months.
- The seed can't be loaded onto the real-data stack again.

## Architecture Decisions
- Plan steps 1–2 (measure on a copy, then the owner runs the cleanup on the real app after a verified backup) are the owner's. The result of step 1 is in the issue comment. This branch covers what that run needs, plus step 3.
- **Step 3, the guard.** `demo-enable`'s refusal (#152) becomes a shared one in the Makefile (`DEMO_REFUSED`: the real-data project, or the real-data container named in `DB_CONTAINER`). It covers `demo-enable`, `db-seed-dummy` and `db-seed-demo`:
  - when make parses the command line (`$(error ...)`), so it refuses before any recipe runs, `db-wait`'s readiness probe included;
  - again inside the `demo-enable` and `db-seed-dummy` recipes, for a run that reaches them as a prerequisite. Before this change, `db-seed-demo` relied on `demo-enable` failing first, which `make -j` doesn't guarantee.
  - The test instance (`capitalos-test`) and worktree stacks are still allowed. `db-clear-dummy` stays allowed on the real-data stack: it is the owner's cleanup.
- **History.** `seed_dummy_cleanup.sql` was already on main (`make db-clear-dummy`, last changed in #158). It now writes `wealth_rollup_dirty` marks before it deletes, in the same transaction:
  - every user, from the earliest DUMMY price date (`LEAST(trade_date, ts in UTC)`), because the prices are shared;
  - the owners of the DUMMY accounts and wallets (the demo user), from 1970-01-01 (`ALL_HISTORY`), because they lose whole accounts;
  - a pending mark only moves earlier, and its generation goes up (the same upsert as migrations 075 and 078).

## Acceptance Criteria
- [x] `make db-seed-dummy`, `make db-seed-demo` and `make demo-enable` refuse on the real-data stack before any `docker` call.
- [x] They still work on a worktree stack and the test instance.
- [x] `make db-clear-dummy` marks every user's History dirty from the earliest DUMMY price date, and the demo user's from the start.
- [ ] (Owner) Run `make db-backup` then `make db-clear-dummy` on the real app. History then recomputes on its next read.

## How To Test
- `scripts/test-checkout-guard.sh` (run by `make lint`). In a throwaway clone that plays the real-data checkout, with a stub `docker` that logs its calls:
  - each guarded target is refused, and `docker` is never called;
  - the recipe guard alone refuses before `psql`;
  - `db-clear-dummy` is allowed on the real-data stack, and the seed is allowed on a worktree.
- `make db-schema-check` (throwaway Postgres): `test_the_dummy_cleanup_marks_history_dirty_from_the_earliest_dummy_price` seeds, then cleans up, and checks each user's mark. It covers no prior mark, a later pending mark moved earlier, an earlier pending mark kept, and demo from 1970-01-01.

<!-- IMMUTABLE_PLAN_END -->

## Deterministic Gate Results
- `scripts/test-checkout-guard.sh`: 27 passed, 0 failed (9 new).
- `make db-schema-check`: 58 migrations, idempotent, schema matches; Postgres tests 21 passed. With the dirty-mark INSERT removed, the new test fails (1 failed, 20 passed).
- Not run: nothing touched the real-data stack. The refusal on it is shown by the throwaway-clone test above.
