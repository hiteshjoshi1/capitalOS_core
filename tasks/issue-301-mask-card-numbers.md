# Issue 301: Mask card numbers in transaction notes

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/301

## Objective
- No full card or account number in `transactions.notes`, for new imports and for stored rows.

## Architecture Decisions
- One step in the runner: `mask_transaction_notes` (masking.py, the D-48 rule: last 4 kept,
  separators kept, dates and short numbers untouched) on every parser's output, before the
  `| fp:<hash>` suffix and the report preview. The UOB and Citi card parsers also write
  `card_number=` masked, so their own output is clean too.
- Notes are not in the dedup key or the fingerprint (D-35: ts/type/amount/currency/merchant), so
  masking changes no dedup. `merchant_counterparty` is left as the bank wrote it (it is the key).
- Migration 082: a plpgsql port of the same token rule (temporary functions, nothing left in the
  schema), applied to the parser part of each note; the fp suffix kept byte for byte. Idempotent.
  On the real data on 2026-11-07: 265 rows (261 card, 4 bank GIRO lines), none left with a 12+ digit run.

## Acceptance Criteria
- [x] Every registered parser: stored notes and preview notes hold no full number, no 12+ digit run.
- [x] 082 masks like masking.py, keeps the fp suffix, a second run changes nothing (Postgres test).
- [x] Re-importing a file before and after the repair adds no rows.

## How To Test
- `pytest tests/test_account_number_masking.py tests/test_ingest_uob_cc.py tests/test_ingest_citi_cc.py`
- `make db-schema-check` (runs tests/test_postgres_mask_card_notes.py)

<!-- IMMUTABLE_PLAN_END -->
