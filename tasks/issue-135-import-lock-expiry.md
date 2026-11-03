# Issue 135: Import locks never expire; scheduler not shut down on exit

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/135

## Objective
- A reload, deploy or crash in the middle of an IBKR Flex import or a crypto wallet refresh must not wedge every later import/refresh (409 / silently skipped) until someone deletes a row by hand.
- Schedulers stop firing jobs when the API shuts down or reloads.

## Architecture Decisions
- Keep the `portfolio_import_locks` table on every backend and add a staleness rule, rather than a Postgres advisory lock. An advisory lock would need one pinned connection for the whole import (the import commits several times on a pooled session, so a session-level lock could stay on a pooled connection or be released early), plus a separate SQLite path for tests. The table approach behaves the same on Postgres and SQLite, needs no migration, and still shows who holds the lock.
- Acquire = `INSERT ... ON CONFLICT (broker_account_id) DO NOTHING`. If a row already exists and its `locked_at` is older than `IBKR_IMPORT_LOCK_STALE_MINUTES` (default 30; IBKR imports take seconds), it is taken over with a compare-and-swap `UPDATE ... WHERE lock_owner = <previous owner>`, so of two racing imports exactly one wins; a warning `ibkr_flex_stale_import_lock_taken_over` is logged. A younger lock still refuses (409).
- Crypto: one conditional `UPDATE` claims the flag when it is free, has no start time, or `refresh_started_at` is older than `CRYPTO_REFRESH_LOCK_STALE_MINUTES` (default 30); a takeover logs `crypto_stale_refresh_lock_taken_over`.
- Lifespan calls `stop_scheduler()` for all three schedulers with `shutdown(wait=False)`: no new jobs fire, and a reload is not held up by a running import. A job cut short leaves a lock that the stale rule takes over.

## Acceptance Criteria
- [x] A leftover lock row older than the threshold doesn't block an import (test).
- [x] Concurrent imports are still refused (test, incl. 409 from `/portfolio/ibkr-flex/import-now`).
- [x] Restarting the API mid-import doesn't wedge later imports (stale takeover + scheduler shutdown).
- [x] Same staleness rule for the crypto refresh flag (test).

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_import_lock_expiry.py -q`
- `make verify`

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results
- `tests`: pass — `pytest tests/test_import_lock_expiry.py tests/test_ibkr_flex_phase1.py tests/test_crypto.py tests/test_market_data.py` all pass
- `make verify`: see PR

## Extra Files Changed
- `.env.example` — reason: documents the two new threshold env vars.

## Human Action Summary
- Next expected action: review/merge; no migration.
- Open questions: none. A real import longer than 30 minutes would be taken over; raise the env var if that ever happens.
