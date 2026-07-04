# Issue 188: DBS credit card CSV ingestion and account setup

## Objective
- Add first-class ingestion support for DBS/POSB credit card transaction-history CSV files.
- Register a real `DBS Credit Card` SGD account/card setup so the import works without manual database edits.
- Make repeated imports of the same DBS credit card CSV idempotent: the second import must insert zero duplicate transactions.

## Current State
- `data/fixtures/transaction_history_04072026_105429.csv` is a DBS/POSB MasterCard Platinum credit-card transaction export.
- CapitalOS already supports credit-card accounts through `accounts.account_type = 'CREDIT_CARD'` and `credit_card_accounts`.
- Existing card import examples are Citi CSV and UOB XLS, but there is no DBS credit-card CSV parser or parser registry entry.
- DBS bank transaction CSV ingestion exists, so DBS credit-card CSV detection must not accidentally route card files to the bank-account parser.

## Architecture Decisions
- Reuse the existing ingestion pipeline: parser module, parser registry, upload endpoint, import job, transaction validation, and transaction fingerprint idempotency.
- Add a new parser key, `dbs_credit_card_csv_v1`, instead of overloading `dbs_transaction_history_csv_v1`.
- Treat the DBS credit card as platform `DBS`, account type `CREDIT_CARD`, currency `SGD`, country `SG`.
- Store only safe card metadata from the header:
  - card display name,
  - last four digits / masked card suffix when available,
  - credit limit,
  - available limit,
  - export/as-at date.
- Do not store the full displayed card number in a way that exposes more than needed in logs or UI.
- Map debit rows to negative card transactions and credit rows to positive card transactions, preserving the original posted amount and SGD currency.
- Classify:
  - `PURCHASE` as `EXPENSE` / `CreditCard::Purchase`,
  - `FEES & CHARGES` as `FEE` / `CreditCard::Fee`,
  - `GOODS AND SERVICES TAX (GST)` as `TAX` / `CreditCard::Tax`,
  - finance-charge descriptions as `INTEREST` / `CreditCard::Interest`,
  - card payments/refunds/credits as `TRANSFER` or `INCOME` based on DBS row semantics and existing credit-card conventions.

## Implementation Plan
- Add `api/app/ingestion/parsers/dbs_credit_card_csv_v1.py`.
- Parse the CSV with Python's `csv` module, not ad hoc string splitting.
- Detect the transaction header row:
  - `Transaction Date`,
  - `Transaction Posting Date`,
  - `Transaction Description`,
  - `Transaction Type`,
  - `Payment Type`,
  - `Transaction Status`,
  - `Debit Amount`,
  - `Credit Amount`.
- Extract header metadata above the transaction table:
  - `Card Transaction Details For`,
  - `Transactions as at`,
  - `Credit Limit`,
  - `Available Limit`.
- Add the parser to `api/app/ingestion/runner.py` `PARSER_REGISTRY`.
- Add conservative signature inference in `api/app/ingestion/registry.py` so this file shape resolves to `dbs_credit_card_csv_v1` even before a registered signature exists.
- Add a migration to register the fixture signature for `dbs_credit_card_csv_v1`.
- Add or update seed/default account setup so a DBS credit card SGD account exists for import:
  - `accounts.name = 'DBS Credit Card'`,
  - `accounts.platform = 'DBS'`,
  - `accounts.account_type = 'CREDIT_CARD'`,
  - `accounts.currency = 'SGD'`,
  - matching `credit_card_accounts` row with DBS issuer/card metadata.
- Ensure upload idempotency uses the existing transaction fingerprint path and does not create duplicate transactions on repeated upload.
- Add frontend upload mapping in `web/src/routes/ingestUtils.ts` so DBS credit-card CSV files can be approved as the new parser when needed.
- Keep IBKR/Flex logic untouched.

## How To Test
- Run `make api-rebuild`.
- Run focused backend parser/upload tests:
  - `docker compose run --rm api pytest tests/test_ingest_dbs_credit_card.py -q`
- Run a direct upload smoke against a local account seeded by the test or dev database:
  - upload `data/fixtures/transaction_history_04072026_105429.csv` to `/ingest/upload?account_id=<dbs_credit_card_account_id>`,
  - confirm `status=IMPORTED`,
  - confirm `parser_key=dbs_credit_card_csv_v1`,
  - confirm parsed count equals inserted count on the first run,
  - upload the same file again,
  - confirm `transactions_inserted=0` and `duplicates_skipped` equals the parsed count.
- Query the database after import and confirm:
  - all inserted rows have account type `CREDIT_CARD`,
  - all inserted rows are `SGD`,
  - debit purchases/fees/taxes are negative,
  - card payments/refunds are not incorrectly counted as purchases.
- Run `make api-smoke`.

## Acceptance Criteria
- [ ] DBS credit-card CSV fixture parses successfully with transaction and metadata counts.
- [ ] Parser registry resolves the fixture to `dbs_credit_card_csv_v1` without manual parser selection.
- [ ] A DBS credit-card SGD account/card record exists in seed/default setup for imports.
- [ ] Uploading the fixture inserts transactions once and skips all duplicates on repeat upload.
- [ ] Transaction classification preserves purchases, fees, GST/tax, finance charges, payments, and credits.
- [ ] Citi, UOB card, DBS bank, and DBS Vickers ingestion tests continue to pass.
- [ ] No full card number is logged or displayed beyond the agreed safe masked/last-four representation.

## Out Of Scope
- Changing credit-card dashboard visuals.
- Changing cash-flow, net-worth, or card page calculations.
- Backfilling historical DBS credit-card data beyond importing the provided CSV format.
- Adding a new platform code for DBS credit cards.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Add DBS credit-card parser.
- [ ] Wire parser registry and upload runner.
- [ ] Add migration/signature registration.
- [ ] Add DBS credit-card account/card seed setup.
- [ ] Add backend parser and idempotent upload tests.
- [ ] Add frontend ingest parser mapping if needed.
- [ ] Run deterministic safety gates.
- [ ] Verify semantic intent is achieved.

## Execution Journal (Codex Mutable)
- Current Stage: `planned`
- Workflow Status: `not-started`
- Provider/Model: `manual/task-planning`
- Last Updated: `2026-07-04T00:00:00+08:00`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `api-rebuild`: `pending`
- `api-smoke`: `pending`

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- None.

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason:
- Attempted mitigations:
- Suggested human action:

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: implement after current branch is clean.
- Open questions:
  - Confirm final display name if it should not be `DBS Credit Card`.

## Automation Log (Mutable)
- 2026-07-04T00:00:00+08:00 - Created DBS credit-card CSV ingestion planning issue from fixture `data/fixtures/transaction_history_04072026_105429.csv`.
