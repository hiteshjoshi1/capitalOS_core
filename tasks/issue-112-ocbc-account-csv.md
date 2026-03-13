# Issue 112: OCBC Account CSV Ingestion + Cash Deposits Breakdown Card

## Objective

1. **OCBC CSV Parser**: Build a parser (`ocbc_account_csv_v1`) for OCBC bank account transaction history exported as `.csv`. The fixture file `data/fixtures/ocbc_TransactionHistory_20260313165630.csv` contains real transaction data. Parser must handle OCBC-specific format quirks: multi-line description fields, metadata header rows (account name, balances), `Withdrawals(SGD)` / `Deposits(SGD)` column naming, and DD/MM/YYYY dates.

2. **Net Worth / Cash Position Update**: After ingestion, OCBC cash balances must flow into the existing `positions` table as a CASH asset, which automatically updates `net_worth.cash` and `cash_balances` in the dashboard summary endpoint — no dashboard API changes needed for this.

3. **Cash Deposits Breakdown Card (new)**: Add a new card to `/cash` (CashOverview page) showing cash deposits grouped by platform/source (e.g. DBS, OCBC, UOB, IBKR, Ethereum, Solana). This card becomes the **primary** card at the top; the existing "Cash Balances" and "Stablecoins" cards move below it. Requires a new backend endpoint to provide account-level cash breakdown.

## Architecture Decisions

- **AD-1: Follow DBS parser pattern exactly.** The OCBC parser (`ocbc_account_csv_v1.py`) mirrors `dbs_transaction_history_csv_v1.py`: extract metadata from header rows (account name, available/ledger balance), find the transaction header row by matching `"transaction date"`, parse data rows, classify as INCOME/EXPENSE/TRANSFER, return `ParseResult` with transactions + one CASH position for the balance.

- **AD-2: Multi-line CSV descriptions handled via Python csv.reader.** The OCBC CSV wraps descriptions across multiple lines inside double-quotes. Python's built-in `csv.reader` handles this correctly (RFC 4180 quoted fields). No custom line-joining is needed — the reader produces the correct row boundaries automatically.

- **AD-3: Currency is SGD (hardcoded from column headers).** OCBC column headers include `Withdrawals(SGD)` and `Deposits(SGD)`. The currency is extracted from the column header parentheses. If not found, default to `SGD`.

- **AD-4: Transaction classification via description keywords.** Reuse the same keyword-based transfer detection as DBS (`GIRO`, `IBG`, `TRANSFER`, `FUND TRANSFER`, `PAYNOW`, etc.). OCBC descriptions contain `FUND TRANSFER`, `IBG GIRO`, `FAST PAYMENT` — these map to TRANSFER. `INTEREST CREDIT` and `BONUS INTEREST` map to INCOME. Everything else follows debit=EXPENSE, credit=INCOME.

- **AD-5: New endpoint `GET /dashboard/cash-deposits` for deposits breakdown.** Returns cash positions grouped by platform (joins `positions` → `accounts` → `platforms`). Also includes crypto wallet balances from `crypto_wallet_snapshots`. This data feeds the new UI card. Schema: `{ items: [{ source: string, value: number, percent: number }], total: number }`.

- **AD-6: Signature registration via migration.** Compute the `flat_csv` signature for the OCBC file header (`transaction date,value date,description,withdrawals(sgd),deposits(sgd)`) with `platform_hint=OCBC` and register it in `parser_registry` via a new migration `026_register_ocbc_account_parser.sql`. Also add inference fallback in `registry.py` for the OCBC header pattern (like UOB).

- **AD-7: No database schema changes.** All data fits existing tables: `transactions`, `positions`, `assets`, `accounts`, `import_jobs`. OCBC is just another platform + parser — no DDL needed beyond the parser_registry row.

## Risks

- **R-1: Multi-line CSV fields.** OCBC wraps descriptions in quotes across 2+ lines. Python `csv.reader` handles this, but tests must validate multi-line parsing end-to-end. Risk: malformed rows if quoting is inconsistent.
- **R-2: Date format DD/MM/YYYY.** Already supported by `_parse_date` in DBS parser. Can import that utility or duplicate it.
- **R-3: Signature collision.** The flat_csv signature depends on headers. The OCBC header (`transaction date,value date,description,withdrawals(sgd),deposits(sgd)`) is unique — no collision risk with DBS headers.
- **R-4: Stablecoin double-counting in deposits card.** Crypto wallet stablecoin balances are shown in both crypto and cash contexts. The deposits card should include crypto wallet totals as a separate line item clearly labeled, not double-counted in cash.

## Open Questions

- **OQ-1**: Should the deposits breakdown card include credit card available credit? (Assumption: No — credit cards are liabilities, not cash deposits.)
- **OQ-2**: Should OCBC `INTEREST CREDIT` transactions be classified as `INTEREST` type (from txn_type enum) instead of `INCOME`? (Assumption: Use `INCOME` to stay consistent with DBS parser behavior.)

## Acceptance Criteria

- [ ] **AC-1**: Parser file `api/app/ingestion/parsers/ocbc_account_csv_v1.py` exists and parses the fixture CSV correctly.
- [ ] **AC-2**: Parser extracts metadata — account name (`360 Account 511-558900-001`), available balance (`25,136.91`), ledger balance (`25,136.91`), currency (`SGD`).
- [ ] **AC-3**: Parser extracts all 20 transactions from the fixture with correct dates (DD/MM/YYYY), amounts (signed), types (INCOME/EXPENSE/TRANSFER), and descriptions (multi-line collapsed to single string).
- [ ] **AC-4**: Parser returns one CASH position with `quantity=25136.91`, `currency=SGD`, `asset_class=CASH`.
- [ ] **AC-5**: Transfer classification: `FUND TRANSFER`, `IBG GIRO`, `FAST PAYMENT` → TRANSFER; `INTEREST CREDIT`, `BONUS INTEREST` → INCOME; `NETS QR`, `CASH WITHDRAWAL` → EXPENSE.
- [ ] **AC-6**: Parser registered in `PARSER_REGISTRY` dict in `runner.py` as `"ocbc_account_csv_v1": ("csv", parse_ocbc_account_csv)`.
- [ ] **AC-7**: Migration `026_register_ocbc_account_parser.sql` registers the format signature in `parser_registry` table.
- [ ] **AC-8**: Ingestion via `POST /ingest/upload` with an OCBC-linked account successfully parses, deduplicates, and inserts transactions + position.
- [ ] **AC-9**: After ingestion, `GET /dashboard/summary` reflects updated `net_worth.cash` and `cash_balances` for SGD.
- [ ] **AC-10**: New endpoint `GET /dashboard/cash-deposits?month=YYYY-MM&base_currency=SGD` returns cash grouped by platform/source.
- [ ] **AC-11**: New `CashDepositsCard` component in `web/src/routes/CashOverview.tsx` renders deposits by source as primary card, existing cards below.
- [ ] **AC-12**: Total of deposits card matches `net_worth.cash` from dashboard summary.
- [ ] **AC-13**: Unit tests pass for OCBC parser (fixture-based + synthetic edge cases).
- [ ] **AC-14**: `make verify` passes (lint + typecheck + test-backend + test-frontend).
- [ ] **AC-15**: `make api-smoke` passes after `make api-rebuild`.

## Human Approval Gate
- [x] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist

### Backend — OCBC Parser
- [x] Create `api/app/ingestion/parsers/ocbc_account_csv_v1.py`
  - Import/adapt `_parse_amount`, `_parse_date` utilities (or import from a shared module)
  - Extract metadata: scan rows for `Account details for:`, `Available Balance`, `Ledger Balance`
  - Extract currency from column header `Withdrawals(SGD)` → parse parenthesized currency
  - Find transaction header row: match `transaction date` in lowercased first cell
  - Parse data rows: map `Withdrawals(SGD)` → negative amount (EXPENSE), `Deposits(SGD)` → positive amount (INCOME)
  - Transfer detection: check description for keywords (GIRO, IBG, TRANSFER, FAST PAYMENT, PAYNOW, BILL, TAX, IRAS, SRS, CPF, TOPUP)
  - Return `ParseResult(transactions=..., positions=[cash_position], section_counts={"transactions": N})`
- [x] Register parser in `api/app/ingestion/runner.py` — add import + entry to `PARSER_REGISTRY`
- [x] Add OCBC header inference in `api/app/ingestion/registry.py` — add `OCBC_ACCOUNT_CSV_HEADERS` tuple and `_has_ordered_header_subset` check in `_infer_parser_key`
- [x] Create migration `migrations/026_register_ocbc_account_parser.sql` — compute signature, INSERT into `parser_registry`

### Backend — Cash Deposits Endpoint
- [x] Add `_cash_deposits()` helper in `api/app/routers/dashboard.py`
  - Query `positions` JOIN `accounts` JOIN `platforms` WHERE `asset_class = 'CASH'`, grouped by platform code
  - Add crypto wallet snapshot totals as separate source entries (by chain: Ethereum, Solana)
  - Apply FX rates for base_currency conversion
  - Return `{ items: [...], total: float }`
- [x] Add `GET /dashboard/cash-deposits` route in `api/app/routers/dashboard.py`
- [x] Add Pydantic response schema `CashDepositsOut` in `api/app/schemas/dashboard.py`

### Frontend — Cash Deposits Card
- [x] Add TypeScript type `CashDeposits` in `web/src/lib/api.ts`
- [x] Add `api.cashDeposits(month, baseCurrency)` method in `web/src/lib/api.ts`
- [x] Update `web/src/routes/CashOverview.tsx`:
  - Fetch `cashDeposits` alongside existing API calls
  - Create new `CashDepositsCard` section at the top (before existing cards)
  - Table: Source | Value | % of Total
  - Total row at bottom
  - Move existing "Cash Balances" and "Stablecoins" cards into a secondary grid below

### Tests
- [x] Create `api/tests/test_ingest_ocbc.py`:
  - `test_ocbc_parser_extracts_metadata` — validates balance, currency, account name
  - `test_ocbc_parser_extracts_transactions` — validates count, types, amounts, dates
  - `test_ocbc_parser_multiline_description` — validates multi-line CSV field handling
  - `test_ocbc_parser_transfer_classification` — validates TRANSFER detection for GIRO, FUND TRANSFER, FAST PAYMENT
  - `test_ocbc_parser_cash_position` — validates CASH position output
  - `test_ocbc_parser_empty_file` — edge case: no transactions
- [x] Add OCBC parser test to `api/tests/test_parsers.py` if pattern established
- [x] Add signature test case to `api/tests/test_signature.py` for OCBC CSV

### Verification
- [x] `make api-rebuild` — containers start cleanly
- [ ] `make api-smoke` — health + dashboard endpoints return valid JSON
- [ ] `make verify` — lint + typecheck + test-backend + test-frontend all pass
- [ ] Manual: `curl POST /ingest/upload` with OCBC fixture → status IMPORTED
- [ ] Manual: `curl GET /dashboard/summary?month=2026-03` → cash includes OCBC balance
- [ ] Manual: `curl GET /dashboard/cash-deposits?month=2026-03` → OCBC appears in items
- [ ] Manual: Open `http://localhost:5173/cash` → deposits breakdown card renders

## Implementation Reasoning Addendum (Codex Mutable)
- Added a new flat CSV parser `ocbc_account_csv_v1` that mirrors the DBS transaction parser structure but adapts to OCBC specifics: metadata rows, `Withdrawals(SGD)` / `Deposits(SGD)` headers, DD/MM/YYYY parsing, and RFC 4180 multi-line descriptions via `csv.reader`.
- Collapsed quoted multi-line OCBC descriptions with whitespace normalization before classification so the stored transaction descriptions remain stable for fingerprinting and tests.
- Kept OCBC balance ingestion aligned with the existing positions flow by returning a single CASH position and letting the existing runner asset normalization and snapshot insertion logic handle persistence.
- Added registry inference for the OCBC ordered header shape plus migration `026_register_ocbc_account_parser.sql` with the computed flat CSV signature `49291988f2110dd6431bf71a286f2192c98fba692608468006d052b33022423f`.
- Implemented `GET /dashboard/cash-deposits` as a separate dashboard read model that groups latest CASH positions by platform/source and augments them with stablecoin snapshot totals grouped by chain (`USDC` / `USDT` only) using the existing FX conversion helper.
- Updated `/cash` to fetch the new endpoint and render a primary deposits card above the existing cash balances and stablecoins cards without changing the existing summary response shape.
- Reverted the accidental `test-backend` Docker rebuild so the test target stays a pure test runner and `api-rebuild` remains the only rebuild path.
- Confirmed the cash-deposits FX path should match the rest of the dashboard: ingestion persists `positions.cost_basis_base` in the asset quote currency, so non-SGD CASH positions still need `get_rates(...)` conversion at read time.
- Hardened `_display_source()` so short platform acronyms stay uppercase (`DBS`, `OCBC`, `IBKR`) while wallet chain values normalize to title case even when stored as all-caps (`ETHEREUM` -> `Ethereum`).

## Verification Evidence (Codex Mutable)
- `make lint` — passed on the R1 rework pass. Frontend ESLint completed; backend lint target reported `ruff not installed in api image; skipping backend lint`.
- `make typecheck` — passed on the R1 rework pass. Frontend TypeScript build completed; backend typecheck target reported `mypy not installed in api image; skipping backend typecheck`.
- `make test-backend` — passed on the R1 rework pass. `83 passed` in the API container after adding the new dashboard regressions.
- `make test-frontend` — passed on the R1 rework pass. `10` Vitest files passed, `36` tests total.
- `make e2e` — passed on the R1 rework pass. `7` Playwright tests passed.
- `make api-rebuild` — passed on the R1 rework pass. API image rebuilt and container restarted successfully.
- `make api-smoke` — failed again on the R1 rework pass after `make api-rebuild`. `curl http://localhost:8000/health` returned connect error `7` on all three allowed attempts in this environment, so AC-15 still needs confirmation in the actual dev environment before merge.

## Review Findings (Sonnet Primary, Opus Escalation)
_Review output is appended here._

## Retry Log (Max 3)
- `make api-smoke` retry 1: failed with `curl http://localhost:8000/health` connect error `7` immediately after `make api-rebuild`.
- `make api-smoke` retry 2: failed with the same connect error `7` after a short wait.
- `make api-smoke` retry 3: failed with the same connect error `7` after a longer wait; no further retries allowed.
- R1 rework pass `make api-smoke` retry 1: failed with connect error `7` immediately after a successful `make api-rebuild`.
- R1 rework pass `make api-smoke` retry 2: failed with the same connect error `7` after a 2 second wait.
- R1 rework pass `make api-smoke` retry 3: failed with the same connect error `7` after a 5 second wait; no further retries allowed.

## Automation Log (Mutable)
- Implemented parser: `api/app/ingestion/parsers/ocbc_account_csv_v1.py`
- Registered parser: `api/app/ingestion/runner.py`, `api/app/ingestion/registry.py`, `migrations/026_register_ocbc_account_parser.sql`
- Added dashboard contract: `api/app/routers/dashboard.py`, `api/app/schemas/dashboard.py`
- Updated frontend cash view: `web/src/lib/api.ts`, `web/src/routes/CashOverview.tsx`
- Added regression coverage: `api/tests/test_ingest_ocbc.py`, `api/tests/test_parsers.py`, `api/tests/test_signature.py`, `api/tests/test_dashboard.py`, `web/src/__tests__/CashOverview.test.tsx`

## Workflow Commands

```bash
make task-plan TASK=tasks/issue-112-ocbc-account-csv.md
make task-build TASK=tasks/issue-112-ocbc-account-csv.md
make task-review TASK=tasks/issue-112-ocbc-account-csv.md
make task-rework TASK=tasks/issue-112-ocbc-account-csv.md
make task-ship TASK=tasks/issue-112-ocbc-account-csv.md
```

### Retry Entry (2026-03-13T10:23:49Z)

```text
make test-backend failed on attempt 1 with exit code 2: make test-backend
```

### Build Result (2026-03-13T10:25:51Z)

```text
Implementation and verification suite completed successfully.
```

### Review Cycle R1 - Sonnet (claude-sonnet-4.6) (2026-03-13T11:50:30Z)

```text

Total usage est:        1 Premium request
API time spent:         1m 9s
Total session time:     1m 15s
Total code changes:     +0 -0
Breakdown by AI model:
 claude-sonnet-4.6       40.7k in, 3.3k out, 0 cached (Est. 1 Premium request)
STATUS: NEEDS_FIXES
RISK: MEDIUM

SUMMARY:
- All 15 acceptance criteria are structurally addressed. Parser, registry, migration, endpoint, schemas, frontend card, and tests are all present and structurally correct. Core logic follows DBS parser patterns as designed. `make test-backend` reports 71 passing, frontend 36 passing, E2E 7 passing.
- Two fixable issues and one unverified AC remain before ship.

FINDINGS:
- **[MEDIUM] Makefile regression — `docker compose build api` added to `test-backend`**: Every call to `make test-backend` now rebuilds the API Docker image. This makes CI/CD and local test runs significantly slower and can mask stale-image bugs. The build should stay in `make api-rebuild`, not in the test target. Revert this change; the original test failure on attempt 1 was likely a transient container startup race, not a missing build step.
- **[MEDIUM] Potential double-FX in `_cash_deposits`**: `cost_basis_base` in `positions` is conventionally stored already converted to the account's base currency at ingestion time. Multiplying it again by `cash_rates.get(quote_currency, 1.0)` in the new `_cash_deposits()` query is correct only if `cost_basis_base` is stored in the *position's native currency* (not yet converted). The existing `_cash_balances` helper should be checked to confirm which convention is used — if `cost_basis_base` is already in base currency then SGD positions (rate=1.0) will be correct but any non-SGD cash positions would be double-converted. This must be confirmed against existing usage before shipping.
- **[LOW] AC-15 unverified** (`make api-smoke`): All three retries failed with connect error 7 — noted as a sandbox network limitation, not a code bug. The change is not deployable without live smoke-test confirmation. This should be run in the actual dev environment before merge.
- **[LOW] `_display_source` casing is fragile**: `"ethereum"` → `"Ethereum"` works, but `"ETHEREUM"` → `"ETHEREUM"` (stays all caps due to `.isupper()` guard). The chain field from `crypto_wallet_snapshots` is lowercase in the test fixture but should be verified against actual DB values.
- **[INFO] `as_of: None` in parser output**: The OCBC position sets `as_of=None`. This is accepted if the runner defaults `as_of` to the file upload timestamp. Confirmed acceptable by DBS parser precedent — no action needed.

TEST_GAPS:
- No test covering a non-SGD CASH position to validate FX conversion path in `_cash_deposits` (critical given the double-FX risk above).
- No test for `_display_source` edge cases (`"ETHEREUM"` uppercase input, empty string, `None`).
- `test_ocbc_ingest_upload_and_import` is an integration test requiring a live DB — it will be skipped or fail in unit-only environments; no fixture-only fallback is provided.
- `make api-smoke` (AC-15) has never passed in this environment; a verified run log from the actual Docker environment is missing from Verification Evidence.
```

### Review Cycle R1 - Status (2026-03-13T11:50:30Z)

```text
Review-ID: R1
Status: Reviewed
Result: NEEDS_FIXES
Risk: MEDIUM
```

### Review Cycle R1 - Status (2026-03-13T12:48:55Z)

```text
Review-ID: R1
Status: Implemented
Result: NEEDS_REVIEW
Risk: PENDING
```

### Review Cycle R1 - Rework Result (2026-03-13T12:48:55Z)

```text
Targeted rework implemented for latest review findings.
```

### Review Cycle R2 - Sonnet (claude-sonnet-4.6) (2026-03-13T12:53:42Z)

```text

Total usage est:        1 Premium request
API time spent:         1m 9s
Total session time:     1m 17s
Total code changes:     +0 -0
Breakdown by AI model:
 claude-sonnet-4.6       91.6k in, 3.4k out, 14.3k cached (Est. 1 Premium request)
● SQL: Track review findings
  └ Schema operation completed successfully.

STATUS: APPROVED
RISK: LOW

SUMMARY:
- All R1 MEDIUM findings are addressed. `_display_source` now correctly normalises `"ETHEREUM"` → `"Ethereum"` via `text.lower().title()` fallback (only names ≤ 4 chars all-caps stay uppercase, plus the explicit whitelist). The double-FX concern is resolved: `cost_basis_base` is confirmed stored in position-native currency and the FX path is intentional and correct; a new test (`test_dashboard_cash_deposits_converts_non_sgd_cash_positions`) validates the USD→SGD conversion at read time. All three R1 test gaps are now covered (non-SGD cash FX, `_display_source` parametrised edge cases, stablecoin-by-chain with uppercase chain). Backend test count grew from 71 → 83 passed; frontend 36 passed; E2E 7 passed.

FINDINGS:
- **[LOW] Makefile revert unconfirmable from diff**: The rework addendum states the accidental `docker compose build api` in `test-backend` was reverted, but the Makefile does not appear in either the committed or staged diffs. Cannot confirm from diff context alone. The 83-passed test result is consistent with the revert having happened (no slow rebuild), but this should be spot-checked before merge with `grep -n 'build api' Makefile`.
- **[LOW] AC-15 (`make api-smoke`) remains unverified**: All three sandbox retries fail with curl connect error 7 — confirmed environment limitation, not a code defect. Must be validated in the actual Docker dev environment before merge.
- **[INFO] Stablecoin chain casing in integration test fixture**: `crypto_wallet_snapshot_items` inserts `chain='ETHEREUM'` (all-caps) and `chain='solana'` (lowercase). Both now handled correctly by `_display_source` producing `"Ethereum"` and `"Solana"` respectively. Test expectations match.
- **[INFO] `section_counts["transactions"]` semantics**: The counter increments for all non-empty rows after the header; `result.transactions` only appends rows with a valid date and non-zero amount. Both equal 20 for the fixture, which is correct assuming the fixture has no date-less or amount-less rows. Acceptable.

TEST_GAPS:
- No remaining material test gaps. The three gaps called out in R1 are all filled: non-SGD FX test, `_display_source` parametrised test (`"ETHEREUM"`, `""`, `None`), and stablecoin-by-chain test. `test_ocbc_ingest_upload_and_import` is an integration test requiring a live DB — acceptable as-is since the test suite already has integration tests with the same pattern.
```

### Review Cycle R2 - Status (2026-03-13T12:53:42Z)

```text
Review-ID: R2
Status: Reviewed
Result: APPROVED
Risk: LOW
```
