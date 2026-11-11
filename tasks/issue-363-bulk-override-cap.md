# Issue #363: cap the number of IDs in override-bulk

From #353 T6 (#130 §5.6). `POST /categories/override-bulk` accepted any number of transaction IDs.

## Change
- `CategoryOverrideBulkCreate.transaction_ids` has `max_length=1000` (`MAX_BULK_OVERRIDE_IDS`); more is a 422 (FastAPI validation), nothing applied.
- The only caller, Map Transactions, sends the rows selected from one month's unmapped list, far below the cap.

## Tests
- `test_bulk_override_rejects_more_than_the_cap` in `api/tests/test_categories.py`.
