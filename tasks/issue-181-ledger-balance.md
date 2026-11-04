# Issue 181: Bank uploads store the ledger balance, not the available balance

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/181

## Objective
- A bank statement's cash is the **ledger** balance. Available = ledger minus funds on hold, which still belong to the owner; storing available understated Cash, net worth and History for as long as a hold lasted.

## Architecture Decisions
- Owner's call: ledger is the account's cash; available is kept as information (snapshot metadata: `available_balance`, `ledger_balance`, `held_amount` when they differ).
- DBS and OCBC CSV parsers both changed (same two header lines, same reasoning). UOB account XLS unchanged: its balance column is a per-row running balance, not an available/ledger pair.
- Fallback: a file with only one of the two lines uses that one.
- Past snapshots are corrected by re-uploading the affected statements (balance upserts on account/date/currency, History marked dirty, #157 dedup inserts no transactions). No migration: the raw files are the source, not a guess in SQL.

## Acceptance Criteria
- [x] DBS/OCBC fixtures with available < ledger store ledger; parse result carries both.
- [x] One-line files still work (ledger-only, available-only).
- [x] Stored snapshot metadata records both balances and the held amount.
- [x] Re-uploading a statement replaces that date's balance and inserts no transactions.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_bank_ledger_balance.py -q` (6 tests).
- After deploy: re-upload the affected DBS statements to the savings account; the Cash page shows the ledger amount.

<!-- IMMUTABLE_PLAN_END -->

## Deterministic Gate Results
- `make verify`: exit 0. Backend 670 passed, 1 skipped; frontend 304 passed (45 files); lint and typecheck clean.
