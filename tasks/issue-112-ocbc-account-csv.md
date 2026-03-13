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
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist

### Backend — OCBC Parser
- [ ] Create `api/app/ingestion/parsers/ocbc_account_csv_v1.py`
  - Import/adapt `_parse_amount`, `_parse_date` utilities (or import from a shared module)
  - Extract metadata: scan rows for `Account details for:`, `Available Balance`, `Ledger Balance`
  - Extract currency from column header `Withdrawals(SGD)` → parse parenthesized currency
  - Find transaction header row: match `transaction date` in lowercased first cell
  - Parse data rows: map `Withdrawals(SGD)` → negative amount (EXPENSE), `Deposits(SGD)` → positive amount (INCOME)
  - Transfer detection: check description for keywords (GIRO, IBG, TRANSFER, FAST PAYMENT, PAYNOW, BILL, TAX, IRAS, SRS, CPF, TOPUP)
  - Return `ParseResult(transactions=..., positions=[cash_position], section_counts={"transactions": N})`
- [ ] Register parser in `api/app/ingestion/runner.py` — add import + entry to `PARSER_REGISTRY`
- [ ] Add OCBC header inference in `api/app/ingestion/registry.py` — add `OCBC_ACCOUNT_CSV_HEADERS` tuple and `_has_ordered_header_subset` check in `_infer_parser_key`
- [ ] Create migration `migrations/026_register_ocbc_account_parser.sql` — compute signature, INSERT into `parser_registry`

### Backend — Cash Deposits Endpoint
- [ ] Add `_cash_deposits()` helper in `api/app/routers/dashboard.py`
  - Query `positions` JOIN `accounts` JOIN `platforms` WHERE `asset_class = 'CASH'`, grouped by platform code
  - Add crypto wallet snapshot totals as separate source entries (by chain: Ethereum, Solana)
  - Apply FX rates for base_currency conversion
  - Return `{ items: [...], total: float }`
- [ ] Add `GET /dashboard/cash-deposits` route in `api/app/routers/dashboard.py`
- [ ] Add Pydantic response schema `CashDepositsOut` in `api/app/schemas/dashboard.py`

### Frontend — Cash Deposits Card
- [ ] Add TypeScript type `CashDeposits` in `web/src/lib/api.ts`
- [ ] Add `api.cashDeposits(month, baseCurrency)` method in `web/src/lib/api.ts`
- [ ] Update `web/src/routes/CashOverview.tsx`:
  - Fetch `cashDeposits` alongside existing API calls
  - Create new `CashDepositsCard` section at the top (before existing cards)
  - Table: Source | Value | % of Total
  - Total row at bottom
  - Move existing "Cash Balances" and "Stablecoins" cards into a secondary grid below

### Tests
- [ ] Create `api/tests/test_ingest_ocbc.py`:
  - `test_ocbc_parser_extracts_metadata` — validates balance, currency, account name
  - `test_ocbc_parser_extracts_transactions` — validates count, types, amounts, dates
  - `test_ocbc_parser_multiline_description` — validates multi-line CSV field handling
  - `test_ocbc_parser_transfer_classification` — validates TRANSFER detection for GIRO, FUND TRANSFER, FAST PAYMENT
  - `test_ocbc_parser_cash_position` — validates CASH position output
  - `test_ocbc_parser_empty_file` — edge case: no transactions
- [ ] Add OCBC parser test to `api/tests/test_parsers.py` if pattern established
- [ ] Add signature test case to `api/tests/test_signature.py` for OCBC CSV

### Verification
- [ ] `make api-rebuild` — containers start cleanly
- [ ] `make api-smoke` — health + dashboard endpoints return valid JSON
- [ ] `make verify` — lint + typecheck + test-backend + test-frontend all pass
- [ ] Manual: `curl POST /ingest/upload` with OCBC fixture → status IMPORTED
- [ ] Manual: `curl GET /dashboard/summary?month=2026-03` → cash includes OCBC balance
- [ ] Manual: `curl GET /dashboard/cash-deposits?month=2026-03` → OCBC appears in items
- [ ] Manual: Open `http://localhost:5173/cash` → deposits breakdown card renders

## Implementation Reasoning Addendum (Codex Mutable)
_Codex appends execution reasoning entries here._

## Verification Evidence (Codex Mutable)
_Codex appends lint/typecheck/test evidence here._

## Review Findings (Sonnet Primary, Opus Escalation)
_Review output is appended here._

## Retry Log (Max 3)
_Failed command/rework retries are appended here._

## Automation Log (Mutable)
_Automation appends structured logs here._

## Workflow Commands

```bash
make task-plan TASK=tasks/issue-112-ocbc-account-csv.md
make task-build TASK=tasks/issue-112-ocbc-account-csv.md
make task-review TASK=tasks/issue-112-ocbc-account-csv.md
make task-rework TASK=tasks/issue-112-ocbc-account-csv.md
make task-ship TASK=tasks/issue-112-ocbc-account-csv.md
```
