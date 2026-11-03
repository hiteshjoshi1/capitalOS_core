# Issue 136: Upload runner commits partial work on failure; IBKR raw XML stored only after parsing

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/136

## Objective
- A failed upload keeps none of its work: no transactions it inserted, no snapshots it deleted.
- A failed IBKR Flex import always leaves evidence: a failed run row, the raw XML and a data-quality event.
- Rows and attributes the Flex parser can't read are reported, never silently dropped or zeroed.

## Architecture Decisions
- Upload runner: the catch-all rolls back first, then records the FAILED job. When the failure came from the canonical
  adapter, the adapter tags the exception with a `CanonicalUploadFailure` (what is needed to re-record it), and the
  runner writes a failed `broker_import_runs` row, its raw document and a `canonical_write_failed` error event in the
  fresh transaction (`record_upload_canonical_failure`). The adapter's snapshot clear moved inside its try so a
  failure there is recorded too. The "canonical adapter missing" fail-closed path also rolls back first.
- IBKR Flex: the run row (broker account filled in if the legacy account already has one) and the raw XML are
  committed before `parse_flex_statement`. After parsing, `_attach_statement_to_run` sets the broker account and report
  dates on the run and the document. Anything failing before the lock is held (parse, account setup, a live lock)
  rolls back, marks the run failed with `error_code` = the parser's code (or `parse_failed`; `import_in_progress` for a
  held lock) and `error_message` = error class + text (capped at 500 chars; the Flex token never reaches the parser),
  and records an error event. The lock and its stale takeover (#135) are unchanged; the lock is still taken after
  parsing because it is keyed by the broker account the statement names.
- `IbkrFlexImportError` after the lock (validation) now rolls back before recording, like the generic branch.
- Parser: `FlexStatement.data_quality_warnings` (new). Skipped `OpenPosition` rows (no conid, currency or report date)
  give one `skipped_position_row` warning per reason with a count and up to 5 symbols. A missing `cash` or `stock`
  attribute on an equity-summary row gives a `missing_nav_component` warning (read as 0; the total is unaffected).
- A NAV row with no total attribute (`total`/`totalNav`/`totalEquity`/`netLiquidation`) now fails the import with
  `missing_nav_total` instead of summing components. Reason: the total is the account's net worth; the components
  themselves default to 0 when absent, so the sum would fabricate a value (canonical-model principle 7). IBKR always
  sends `total` on these rows, so a missing one means a format change, which should stop the import. Rejected:
  summing with a warning (stores a possibly wrong net worth that History then rolls up). The rebuild tool already
  rejects statements with `data_quality_errors`, so it skips such documents too.

## Acceptance Criteria
- [x] A parser error mid-upload leaves no new transactions and no deleted snapshots (test).
- [x] A malformed Flex XML leaves a failed run row and the stored raw document (test).
- [x] Skipped position rows become data-quality warnings (test).

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_upload_failure_rollback.py -q`
- `make verify`

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `tests`: pass — new `tests/test_upload_failure_rollback.py` (9 tests); with the runner rollback removed, the two
  runner tests fail, so they test the fix.
- `make verify`: frontend lint, pinned refs and checkout-guard (14/14) passed; the backend lint step then hit a
  host Docker error ("all predefined address pools have been fully subnetted": too many parallel worktree networks),
  so the same steps ran on the worktree's existing compose network: ruff pass, mypy pass (104 files), pytest 589
  passed, `tsc -b` pass, vitest 296 passed (45 files).

## Extra Files Changed (Codex Mutable)
- None outside runner.py, upload_canonical.py, ibkr_flex.py and the new test.
