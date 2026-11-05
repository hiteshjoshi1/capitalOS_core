# Issue 190: Uploads: mask account numbers in the app's own copies of statement headers (reports, upload responses)

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/190

## Objective
- Import reports (`data/reports/<job>.json`) and the upload / register responses carry statement account and card numbers only as their last 4 digits.
- Existing reports can be brought in line by a one-off, dry-run-by-default script.

## Architecture Decisions
- One helper, `app/ingestion/masking.py`: `mask_account_numbers` masks every digit run of 8+ symbols (digits, X, *; grouped by single spaces/dashes; starting and ending with a digit; not glued to letters; dash dates excluded) to its last 4 digits, keeping separators ("5555-5555-5555-4444" -> "****-****-****-4444"). Idempotent.
- Applied in one place, `runner._report`, so the report file and every response built from it (upload, /ingest/ibkr, register, refusal) are masked: `parser_meta`'s identifier keys (`account_number`, `account_name`, `card_number`, `card_display_name`, `card_masked`) and every string in `signature_debug`.
- The runner keeps the unmasked values for its own work: `statement_identity` (#180, sha256 + last 4) hashes the raw header / parser_meta value before any report is built; registry inference reads the raw `signature_debug`.
- Out of scope (as the issue says): transaction descriptions (`merchant_counterparty`, `notes`, `preview_transactions`), dedup keys (D-35), `import_jobs.error_message`.
- Script `app/scripts/mask_reports.py` via `make reports-mask [APPLY=1]` (runs in the api container, guarded like the other data targets): lists files and field names, never values; refuses any directory other than `$DATA_DIR/reports`; skips symlinks / files resolving outside it; writes atomically.

## Acceptance Criteria
- [x] Every registered parser, on a synthetic statement with a fake full number: the number appears in no report header/metadata field and no upload response field outside transaction descriptions (response and stored report file).
- [x] The NEEDS_MAPPING response (DBS card header line) and the register response are masked.
- [x] Script: dry run reports what it would change; APPLY=1 changes only those fields; refuses other directories; skips links outside.
- [x] #180's link still links (hash equals the unmasked number's) and still refuses a different account.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_account_number_masking.py -q`
- `make reports-mask` (dry run) / `make reports-mask APPLY=1` in a checkout.
- `make verify`

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results
- `make verify`: pass. Backend 794 passed, 1 skipped, 2 xfailed (pre-existing on main); frontend 315 passed.
- New tests: 33 passed; with the runner change reverted, the 4 leaking parsers (DBS card, OCBC, UOB account, UOB card), the NEEDS_MAPPING/register test and the UOB identity test fail.
- `make reports-mask` / `APPLY=1` run in this worktree on one synthetic report: listed, then masked only `parser_meta.account_number` and `signature_debug.header`.

## Extra Files Changed
- `Makefile` — reason: the `reports-mask` target (added to the guarded targets).

## Human Action Summary
- Next expected action: after deploy, in the main checkout: `make reports-mask` (review the list), then `make reports-mask APPLY=1`.
