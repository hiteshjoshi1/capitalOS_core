# Issue 156: Job status: job_runs table, last success per source on Data Hub, per-account IBKR due check, partial crypto retry

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/156

## Objective
- Scheduled-job failures are visible in the app, not only in logs: every run of the IBKR Flex import, quote refresh, crypto wallet refresh and FX fill is recorded, and the Data Hub shows per source the last success, data as of, and turns red after repeated failures.
- "Done" means the data advanced: a crypto run where every wallet failed is a failure, a partial EVM refresh keeps the failed chains' holdings and stays due, an IBKR import that returns an older statement isn't the day's run, a quote refresh that got no quotes is retried.
- The IBKR due check is per account, so a failed account is retried even when another one succeeded.

## Architecture Decisions
- `job_runs` (migration 076): one row per finished run per scope (`account:<internal id>`, `exchange:<code>`, `wallet:<uuid>`, `all`), with trigger, status (`success` / `partial` / `no_new_data` / `failed`), started/finished, `data_advanced`, `data_as_of` (ISO text in the job's own unit), scrubbed `error_summary`, and `attempt` = failure streak. Rows are written after the job's own commit/rollback in the same session, and recording never raises. Runs refused by a held lock aren't recorded. Existing run tables are unchanged.
- Red after N = 3 consecutive failures of one scope (`FAILURE_THRESHOLD`): a due run that fails is retried every 30 min (D-19), so one failure is usually a hiccup the retry fixes; three in a row is an hour of failing retries. One or two show amber.
- A source's `last_success_at` / `data_as_of` are the oldest across its scopes (a source is as current as its stalest account / exchange / wallet). Only scopes that still exist for the user count (deleted wallet's old failures don't keep it red).
- IBKR: an account is done for a slot when an import completed since the scheduled time with a statement at least as new as the last weekday before New York's date at that time. A US holiday (older statement) retries at most `STALE_STATEMENT_ATTEMPTS = 3` times per slot, spaced by the retry gate.
- Crypto partial EVM: the failed chains' items are copied from the previous snapshot (`source_versions.stale_chains` records how old each is), and a partial newest snapshot keeps the wallet due.
- Quotes: an exchange whose newest run since the window's time got 0 quotes for >0 symbols is `failed` and keeps the window due.
- Error summaries are scrubbed (`safe_error_summary`): URLs, key=value secrets, 0x addresses, account-number shapes, long digit runs and long tokens are removed; capped at 300 chars.
- Smaller (#130 4.6): crypto refresh flag committed before the provider fetch; IBKR read transaction ended before the Flex fetch; bad `CRYPTO_REFRESH_HOUR_LOCAL` falls back to 0; Coinbase wallet ensure no longer writes every 5 minutes.

## Acceptance Criteria
- [x] `job_runs` table recording scheduled and manual runs of each job per scope.
- [x] Crypto run where every wallet failed logs `crypto_refresh_failed` and records failed runs.
- [x] Partial EVM refresh carries the failed chains forward and stays due.
- [x] IBKR due check per account; old statement counts as no new data.
- [x] Data Hub shows per source last success, data as of, red after 3 consecutive failures.
- [x] No secrets / tokens / account numbers in error summaries.
- [x] Existing response fields kept (job_status added only).

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_job_runs.py -q`
- `cd web && npx vitest run src/__tests__/OperationsOverview.test.tsx`
- `make verify`

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `tests (job_runs)`: pass — 18 passed
- `tests (frontend Data Hub)`: pass — 7 passed
- `make verify`: see PR

## Extra Files Changed (Codex Mutable)
- `api/app/crypto/coinbase.py` — reason: #130 4.6 no-op write every due check.
- `api/tests/test_import_lock_expiry.py`, `api/tests/test_ibkr_flex_phase1.py`, `api/tests/test_observability_logging.py`, `api/tests/test_crypto.py` — reason: patch targets moved (import now goes through `run_import_and_record`; scheduler uses the per-account due check and the crypto outcome function).

## Human Action Summary (Codex Mutable)
- Next expected action: review PR; `make db-migrate` applies 076.
- Open questions:
  - A fresh install still schedules nothing for IBKR until the first manual import creates `broker_accounts` rows (#130 4.5, second half): it needs a configured target account, not addressed here.
