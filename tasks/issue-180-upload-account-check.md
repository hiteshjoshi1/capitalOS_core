# Issue 180: Uploads: refuse a statement sent to the wrong account; card accounts never count as cash; undo an upload

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/180

## Objective
- A statement uploaded to the wrong account of the same bank is refused before anything is written.
- A credit-card account's balance never adds to Cash.
- A wrong upload can be undone from the Ingest page, leaving the data as if it never happened.

## Architecture Decisions
- Expected account types live next to the parser registry: `PARSER_ACCOUNT_TYPES` in
  `api/app/ingestion/account_checks.py` (a test requires an entry for every `PARSER_REGISTRY` key).
  Bank statements → BANK, card statements → CREDIT_CARD, IBKR → BROKER, holdings files → BROKER or
  MUTUAL_FUND. A parser without an entry is refused (fail closed, like the canonical registry).
- The checks run inside the runner after the parser is known and before any data write. A refused
  upload keeps its job row as `REJECTED` (new enum value) and the API answers 409 with a structured
  `detail` (`code`, `message`, `job_id`, expected types or last-4 digits, `override_field`).
- An unrecognised file that looks like a holdings export (quantity column plus a security/value
  column, no bank columns) sent to a non-broker account is refused instead of ending in NEEDS_MAPPING.
  Registering a parser for the wrong account type is refused before the shared registry is written.
- Statement identity: `account_statement_identities` (one row per account): sha256 of a constant
  prefix plus the normalised number, and the last four digits. Read from the DBS/OCBC "Account
  details for", the DBS card line and UOB's "Account Number". Not salted per account, so a refusal
  can name the user's account the statement does belong to. `allow_account_mismatch` (form field)
  imports anyway and moves the link to the new number (replaced cards); removing that upload puts the
  old link back. Refused reports leave out `signature_debug` (it can hold the header's number).
- Card accounts: every dashboard cash reader goes through `_cash_balance_rows`, which drops accounts
  in `_credit_card_account_ids` (by `account_type = 'CREDIT_CARD'`, with or without a
  `credit_card_accounts` row). #144 builds one cash scope on this.
- Removal: migration 074 adds `transactions.import_job_id`, `broker_import_runs.import_job_id`,
  `import_jobs.undo_json` / `removed_at`. Each upload writes an undo log with its rows: rows its writes
  replaced (earlier balance or holdings for the same date, an earlier identity link), authority windows
  it created, card limits before/after. `POST /ingest/jobs/{id}/remove` deletes the job's rows, puts
  the replaced rows back, restores card limits (if no later statement changed them), marks History
  dirty from the earliest affected date and sets the job REMOVED. Undo is a stack per date: a job whose
  rows a later upload replaced is refused until that one is removed. Jobs from before 074 are refused.

## Acceptance Criteria
- [x] A bank-statement CSV to a credit-card account is refused before anything is written; the same
  for a holdings file to a bank account (registered or not).
- [x] A second statement naming a different account number is refused, with a message and an
  override path ("Upload anyway").
- [x] A CREDIT_CARD account's balance never adds to Cash (net worth, cash series, cash deposits,
  geography, freshness).
- [x] An upload can be removed, leaving the data as before (tested for bank, re-upload, holdings,
  card limits), with History marked dirty from the earliest date.
- [x] Synthetic files only.

## How To Test
- `make verify` (lint, typecheck, backend and frontend tests).
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_upload_account_checks.py`.
- `cd web && npx vitest run src/__tests__/Ingest.test.tsx src/__tests__/api.uploadRefusal.test.ts`.
- Postgres: in the worktree, `make up && make db-migrate`, then upload/refuse/remove against the
  isolated stack (done with a synthetic script; see the gate results).

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results
- `lint`: pass — `make verify` (eslint, ruff "All checks passed!", pinned refs, checkout guard 14/14)
- `typecheck`: pass — mypy "no issues found in 110 source files", `tsc -b`
- `tests`: pass — backend 692 passed / 1 skipped; frontend 46 files, 311 tests
- `api-smoke`: pass — isolated Postgres stack: migration 074 applied; card←bank and bank←holdings
  REJECTED; a different number REJECTED; re-upload removal restores the earlier balance; removing
  the first while the re-upload stands is refused; holdings removal restores the replaced holdings and
  then the empty state; dirty mark `import_removed` from 2026-02-19
- `policy-checks`: pass — no real data; only migration 074

## Extra Files Changed
- `api/tests/test_canonical_adapter_registry_phase5.py`, `api/tests/test_upload_failure_rollback.py` —
  their accounts were all BANK (Sharekhan, Citi): now seeded with the right type; fake parsers
  declare an account type.
- `api/tests/conftest.py` — SQLite schema for the new columns and table.

## Human Action Summary
- Next expected action: review the PR; test-instance batch.
- Open questions:
  - Real accounts: confirm no account receives uploads of a type outside `PARSER_ACCOUNT_TYPES`
    (query in the PR).
  - The sprint 2 wrong import predates 074, so it can't be removed from the UI; its transactions on the
    card account need a one-off cleanup (its balance no longer counts as cash).
