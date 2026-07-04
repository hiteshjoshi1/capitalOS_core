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
- [x] Add DBS credit-card parser.
- [x] Wire parser registry and upload runner.
- [x] Add migration/signature registration.
- [x] Add DBS credit-card account/card seed setup.
- [x] Add backend parser and idempotent upload tests.
- [x] Add frontend ingest parser mapping if needed.
- [x] Run deterministic safety gates.
- [x] Verify semantic intent is achieved.

## Execution Journal (Codex Mutable)
- Current Stage: `implemented`
- Workflow Status: `complete`
- Provider/Model: `manual/task-planning`
- Last Updated: `2026-07-04T14:13:00+08:00`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `api-rebuild`: `pass` - API image rebuilt after parser/registry/test edits.
- `db-migrate`: `pass` - applied `059_register_dbs_credit_card_parser_and_account.sql`; local Postgres emitted a pre-existing collation-version warning.
- `focused DBS parser/upload tests`: `pass` - `docker compose run --rm api pytest tests/test_ingest_dbs_credit_card.py -q`.
- `adjacent ingestion tests`: `pass` - Citi CC, UOB CC, DBS bank/router, DBS Vickers.
- `contract-backend`: `pass` - 3 passed.
- `test-backend`: `pass` - 994 passed, 4 skipped.
- `web-rebuild`: `pass`.
- `lint`: `pass` - frontend eslint passed; backend ruff unavailable in image and skipped by Makefile.
- `typecheck`: `pass` - frontend tsc passed; backend mypy unavailable in image and skipped by Makefile.
- `contract-frontend`: `pass` - 6 passed.
- `test-frontend`: `pass` - 192 passed.
- `e2e`: `pass` - 17 passed after aligning stale alert ingest-link assertion with current account-aware route.
- `api-smoke`: `pass` - `/health` and `/dashboard/summary?month=2026-02` returned JSON.
- `orch-test`: `pass` - 201 passed.
- `direct DBS upload smoke`: `pass` - first upload inserted 11 transactions; second upload inserted 0 and skipped 11 duplicates.

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- `web/tests/e2e/alerts.spec.ts` - Updated stale e2e expectation from `/ingest` to `/ingest?account_id=1`, matching existing app behavior and existing unit-test coverage.

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason:
- Attempted mitigations:
- Suggested human action:

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: ship review.
- Open questions: None.

## Automation Log (Mutable)
- 2026-07-04T00:00:00+08:00 - Created DBS credit-card CSV ingestion planning issue from fixture `data/fixtures/transaction_history_04072026_105429.csv`.
- 2026-07-04T14:13:00+08:00 - Implemented DBS credit-card CSV parser, parser inference, migration/account setup, frontend mapping, tests, and full verification.

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `deterministic_gates`
**Workflow Status**: `running`

## Workflow Snapshot
- latest_outcome: Implemented DBS/POSB credit-card CSV ingestion end to end: parser, registry inference, runner wiring, default DBS Credit Card account setup, idempotent upload coverage, frontend parser approval mapping, and safety checks for masked card metadata.
- next_action: Workflow execution is in progress.
- pipeline_version: `v3`
- provider_model: `codex/gpt-5.5`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: DBS credit-card CSV fixture parses successfully with transaction and metadata counts.
- Acceptance criterion: Parser registry resolves the fixture to dbs_credit_card_csv_v1 without manual parser selection.
- Acceptance criterion: A DBS credit-card SGD account/card record exists in seed/default setup for imports.
- Acceptance criterion: Uploading the fixture inserts transactions once and skips all duplicates on repeat upload.
- Acceptance criterion: Transaction classification preserves purchases, fees, GST/tax, finance charges, payments, and credits.
- Acceptance criterion: Citi, UOB card, DBS bank, and DBS Vickers ingestion tests continue to pass.
- Acceptance criterion: No full card number is logged or displayed beyond the agreed safe masked/last-four representation.

## Prepare
Checked out `feature/issue-188-dbs-credit-card-csv-ingestion-and-account-setup` from `main` and verified task file exists.

## Plan Summary
Added a dedicated dbs_credit_card_csv_v1 parser using csv.reader; wired backend and frontend parser resolution; registered the fixture signature and demo-owned DBS Credit Card setup via migration; added parser/upload/idempotency tests; ran the full required backend, frontend, e2e, smoke, and orchestration gates.

### Architecture Decisions
- Used a new parser key, dbs_credit_card_csv_v1, instead of overloading the DBS bank transaction parser.
- Kept DBS credit cards on platform DBS with account_type CREDIT_CARD, currency SGD, and country SG.
- Stored only safe card metadata: display name without card number, last four, masked last-four form, credit limit, available limit, and export date.
- Mapped debit rows to negative transactions and credit rows to positive transactions while preserving SGD currency.
- Declared dbs_credit_card_csv_v1 as canonical target none because it emits transactions only and no positions or account-balance snapshots.
- Kept IBKR/Flex logic untouched.

### Acceptance Criteria
- DBS credit-card CSV fixture parses successfully with transaction and metadata counts.
- Parser registry resolves the fixture to dbs_credit_card_csv_v1 without manual parser selection.
- A DBS credit-card SGD account/card record exists in seed/default setup for imports.
- Uploading the fixture inserts transactions once and skips all duplicates on repeat upload.
- Transaction classification preserves purchases, fees, GST/tax, finance charges, payments, and credits.
- Citi, UOB card, DBS bank, and DBS Vickers ingestion tests continue to pass.
- No full card number is logged or displayed beyond the agreed safe masked/last-four representation.

### Planned Paths
- `api/app/ingestion/parsers/`
- `api/app/ingestion/runner.py`
- `api/app/ingestion/registry.py`
- `api/app/portfolio/upload_canonical.py`
- `api/tests/`
- `migrations/`
- `web/src/routes/ingestUtils.ts`
- `web/src/__tests__/Ingest.test.tsx`
- `tasks/issue-188-dbs-credit-card-csv-ingestion-and-account-setup.md`

## Build Summary
Implemented DBS/POSB credit-card CSV ingestion end to end: parser, registry inference, runner wiring, default DBS Credit Card account setup, idempotent upload coverage, frontend parser approval mapping, and safety checks for masked card metadata.

### Changed Files
- `api/app/ingestion/parsers/dbs_credit_card_csv_v1.py`
- `api/app/ingestion/registry.py`
- `api/app/ingestion/runner.py`
- `api/app/portfolio/upload_canonical.py`
- `api/tests/test_ingest_dbs_credit_card.py`
- `migrations/059_register_dbs_credit_card_parser_and_account.sql`
- `tasks/issue-188-dbs-credit-card-csv-ingestion-and-account-setup.md`
- `web/src/__tests__/Ingest.test.tsx`
- `web/src/routes/ingestUtils.ts`
- `web/tests/e2e/alerts.spec.ts`

## Latest Verification
- api-rebuild: PASS (exit 0)
- contract-backend: PASS (exit 0)
- test-backend: PASS (exit 0)
- api-smoke: PASS (exit 0)
- lint: PASS (exit 0)
- typecheck: PASS (exit 0)
- contract-frontend: PASS (exit 0)
- test-frontend: PASS (exit 0)
- e2e: PASS (exit 0)
- orch-test: PASS (exit 0)

## Extra Files Changed
- None

## Agent Run Summary
Implemented DBS/POSB credit-card CSV ingestion end to end: parser, registry inference, runner wiring, default DBS Credit Card account setup, idempotent upload coverage, frontend parser approval mapping, and safety checks for masked card metadata.

- semantic_intent_achieved: `True`
- provider_model: `codex/gpt-5.5`

### Semantic Checks
- `pass` DBS credit-card CSV fixture parses successfully with transaction and metadata counts.: test_parse_dbs_credit_card_csv_fixture asserts 11 transactions, section_counts {transactions: 11}, and parser metadata including masked card, limits, and export date.
- `pass` Parser registry resolves the fixture to dbs_credit_card_csv_v1 without manual parser selection.: test_dbs_credit_card_signature_resolves_to_card_parser asserts lookup_parser_key returns dbs_credit_card_csv_v1 from fixture signature_debug.
- `pass` A DBS credit-card SGD account/card record exists in seed/default setup for imports.: Migration 059 inserts demo-owned accounts.name='DBS Credit Card' platform DBS account_type CREDIT_CARD currency SGD plus credit_card_accounts metadata.
- `pass` Uploading the fixture inserts transactions once and skips all duplicates on repeat upload.: Backend test and direct smoke both verified first upload inserted 11 and second upload inserted 0 with 11 duplicates skipped.
- `pass` Transaction classification preserves purchases, fees, GST/tax, finance charges, payments, and credits.: Fixture classifications verified as 7 CreditCard::Purchase, 2 CreditCard::Fee, 1 CreditCard::Tax, and 1 CreditCard::Interest; parser includes payment/refund/credit branches for future credit rows.
- `pass` Citi, UOB card, DBS bank, and DBS Vickers ingestion tests continue to pass.: Adjacent ingestion command passed 15 tests across Citi CC, UOB CC, signature/DBS bank router, and DBS Vickers; full backend suite passed 994 tests.
- `pass` No full card number is logged or displayed beyond the agreed safe masked/last-four representation.: Parser/test assertions and production-code rg check confirm no full card number in production app/migration code; imported DB notes query showed full_card_exposed=false.

### Risk Flags
- Pre-existing Postgres collation-version mismatch warning appears during database commands.
- Backend ruff and mypy are skipped by current Makefile because those tools are not installed in the API image.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._
<!-- MACHINE_RENDERED_END -->
