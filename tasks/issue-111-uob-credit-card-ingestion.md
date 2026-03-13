# Issue 111: UOB Credit Card Parser

## Objective

- Build a parser for UOB credit card statement XLS files (`UOB_CC_TXN_History_09032026222725.xls` in `data/fixtures/`) and integrate it into the existing ingest pipeline so users can upload UOB CC statements via the Ingest page and have transactions imported into the `transactions` table.
- The parser must follow the same patterns established by the Citibank credit card parser (Issue 105) and the credit card UI infrastructure (Issue 106): credit-card type/category classification, foreign currency extraction, and `ParseResult` return type.
- Once ingested, UOB credit card transactions must appear correctly in the Credit Cards detail page (`/credit-cards`), including top purchases and recurring payment detection — no UI code changes needed if the parser populates fields correctly.

---

## Architecture Decisions

### AD-1: XLS-Based Credit Card Parser (Not CSV)

UOB credit card statements are exported as `.xls` files (same format as UOB bank account statements). The parser is registered as `kind="excel"` in `PARSER_REGISTRY`, meaning it receives only `file_path` (no delimiter). The parser reuses UOB account parser utilities (`_pick_engine`, `_parse_date`, `_parse_amount`, `_clean_text`) but implements its own header detection, row collapsing, and credit-card-specific classification.

### AD-2: Distinct Parser Key `uob_credit_card_xls_v1`

A new parser key `uob_credit_card_xls_v1` is introduced, separate from the existing `uob_account_xls_v1`. This is necessary because UOB credit card XLS files have different column headers (e.g., no "Available Balance" column; may include card number, posting date, or transaction reference columns). The signature detection chain in `registry.py` must distinguish between UOB bank account and UOB credit card files based on header shape.

### AD-3: Signature-Based Auto-Detection via Header Inspection

The existing `_excel_signature()` in `signature.py` already computes a stable signature from Excel header fields. The UOB CC file will produce a different signature than the UOB account file because its headers differ. The `_infer_parser_key()` function in `registry.py` is extended with a new ordered-header check for UOB CC headers, ensuring auto-detection works even before manual signature registration. The UOB account header check remains first (more specific match takes priority).

### AD-4: Credit Card Transaction Classification (Matches Citi CC Pattern)

Transaction classification follows the same type/category vocabulary as the Citi CC parser:
- `EXPENSE` / `CreditCard::Purchase` — default for charges
- `TRANSFER` / `CreditCard::Payment` — payment/refund keywords
- `FEE` / `CreditCard::Fee` — late fees, annual fees
- `INTEREST` / `CreditCard::Interest` — finance charges
- `INCOME` / `CreditCard::Refund` — positive amounts (refunds/reversals)

This ensures consistency in the `/spending/credit-card-transactions` endpoint which aggregates across all credit card issuers.

### AD-5: Foreign Currency Extraction

UOB credit card statements may include foreign currency transaction details in the description (similar to Citi CC's `USD 21.80` pattern). The parser extracts foreign currency code and amount using the same regex pattern (`_FOREIGN_CURRENCY_RE`) and stores them in the `notes` field.

### AD-6: Row Collapsing for Multi-Line Descriptions

UOB XLS files use multi-row descriptions where continuation rows lack a transaction date. The same `_collapse_rows` pattern from the UOB account parser is applied: rows without dates are merged into the preceding transaction's description.

### AD-7: Frontend Ingest Button Addition (`UOB_CC`)

A new entry `UOB_CC: { label: "Approve as UOB CC", parserKey: "uob_credit_card_xls_v1" }` is added to `PLATFORM_PARSERS` in `Ingest.tsx`. The `resolvePlatformParser()` function is updated to detect UOB CC headers distinctly from UOB account headers. This allows manual approval for first-time uploads before signature auto-registration.

### AD-8: Migration for Signature Registration

A new migration `025_register_uob_cc_parser.sql` registers the computed signature for the UOB CC fixture file in the `parser_registry` table, enabling auto-detection on subsequent uploads.

### AD-9: No Database Schema Changes

UOB CC transactions use the existing `transactions` table with the same fields as Citi CC transactions. The `credit_card_accounts` table is used for card metadata (already exists from Issue 106). No new tables or columns needed.

---

## Risks

- **R-1: UOB CC XLS Header Ambiguity.** If UOB CC headers overlap substantially with UOB bank account headers, `_infer_parser_key` may misidentify the file. Mitigated by inspecting the actual fixture file headers and implementing precise ordered-header matching.
- **R-2: Date Format Variation.** UOB may use different date formats across exports (DD/MM/YYYY, DD MMM YYYY, Excel date serial). Mitigated by reusing the multi-format `_parse_date` from the UOB account parser.
- **R-3: Foreign Currency Edge Cases.** UOB may format foreign currency differently than Citi (e.g., inline vs. separate column). Parser must handle both patterns gracefully without breaking on unexpected formats.
- **R-4: Fixture File Size.** If the fixture file contains very few transactions, test assertions may be fragile. Ensure tests validate structural correctness, not just counts.

## Open Questions

- **OQ-1: Exact UOB CC XLS Column Headers.** The fixture file must be inspected at implementation time to determine exact column names. The parser header constants must match exactly. *(Resolved during implementation by reading the fixture.)*
- **OQ-2: Card Number Location.** Does UOB CC XLS include a card number column? If so, it should be extracted into `notes` for parity with Citi CC. *(Resolved during implementation.)*
- **OQ-3: Transaction Amount Sign Convention.** Does UOB use positive amounts for charges and negative for credits, or the reverse? The parser must normalize to the CapitalOS convention (negative = money out). *(Resolved during implementation.)*

## Acceptance Criteria

- [ ] New parser file `api/app/ingestion/parsers/uob_credit_card_xls_v1.py` exists and follows `ParseResult` contract
- [ ] Parser correctly parses all transaction rows from `UOB_CC_TXN_History_09032026222725.xls` fixture
- [ ] Transactions are classified with correct type/category (EXPENSE, TRANSFER, FEE, INTEREST, INCOME)
- [ ] Foreign currency info extracted and stored in `notes` field (if present in fixture)
- [ ] Parser registered in `PARSER_REGISTRY` in `runner.py` as `("excel", parse_uob_credit_card_xls)`
- [ ] `registry.py` `_infer_parser_key` updated to auto-detect UOB CC headers
- [ ] Migration `025_register_uob_cc_parser.sql` registers the fixture file's signature
- [ ] `Ingest.tsx` `PLATFORM_PARSERS` includes `UOB_CC` entry with correct parser key
- [ ] `resolvePlatformParser()` in `Ingest.tsx` distinguishes UOB CC from UOB bank account
- [ ] Backend test `api/tests/test_ingest_uob_cc.py` validates parser output (transaction count, type distribution, date parsing, currency)
- [ ] Backend test validates end-to-end upload + idempotent re-upload (same pattern as `test_ingest_citi_cc.py`)
- [ ] Frontend test in `web/src/__tests__/Ingest.test.tsx` includes test for UOB CC approve button
- [ ] `make api-rebuild` succeeds
- [ ] `make web-rebuild` succeeds
- [ ] `make api-smoke` passes
- [ ] `curl http://localhost:8000/health` returns 200
- [ ] Uploaded UOB CC transactions appear in `/credit-cards` detail page (top purchases, recurring payments populated)
- [ ] No existing parsers or tests broken

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist

### Backend — Parser
- [ ] Inspect `data/fixtures/UOB_CC_TXN_History_09032026222725.xls` to determine exact column headers and data layout
- [ ] Create `api/app/ingestion/parsers/uob_credit_card_xls_v1.py` with:
  - [ ] UOB CC header constants (from fixture inspection)
  - [ ] `_find_header_row()` for UOB CC specific headers
  - [ ] `_extract_metadata()` for account/currency/statement period
  - [ ] `_collapse_rows()` for multi-line description merging
  - [ ] `_classify()` with CreditCard:: category mapping (EXPENSE, TRANSFER, FEE, INTEREST, INCOME)
  - [ ] `_extract_foreign_currency()` regex extraction
  - [ ] `parse_uob_credit_card_xls(file_path: str) -> ParseResult` main function
- [ ] Import and register parser in `api/app/ingestion/runner.py` PARSER_REGISTRY as `"uob_credit_card_xls_v1": ("excel", parse_uob_credit_card_xls)`

### Backend — Signature & Registry
- [ ] Update `api/app/ingestion/registry.py`:
  - [ ] Import UOB CC header constants
  - [ ] Add `_has_ordered_header_subset` check for UOB CC headers in `_infer_parser_key`
  - [ ] Ensure UOB account check still works (order matters — more specific match first)
- [ ] Create `migrations/025_register_uob_cc_parser.sql` with computed signature hash for the fixture file

### Frontend — Ingest Page
- [ ] Add `UOB_CC: { label: "Approve as UOB CC", parserKey: "uob_credit_card_xls_v1" }` to `PLATFORM_PARSERS` in `web/src/routes/Ingest.tsx`
- [ ] Add UOB CC header constants (similar to `UOB_HEADERS`) in `Ingest.tsx`
- [ ] Update `resolvePlatformParser()` to detect UOB CC vs UOB bank based on header shape
- [ ] Ensure platform hint `UOB_CC` or `UOB CC` resolves correctly

### Tests — Backend
- [ ] Create `api/tests/test_ingest_uob_cc.py` with:
  - [ ] `test_parse_uob_credit_card_xls_fixture()` — validates transaction count, type distribution, date parsing, currency, category mapping
  - [ ] `test_uob_cc_ingest_upload_and_idempotent()` — end-to-end upload flow with duplicate detection
  - [ ] Foreign currency assertion (if applicable)
  - [ ] Notes field validation

### Tests — Frontend
- [ ] Add test in `web/src/__tests__/Ingest.test.tsx`:
  - [ ] `it("shows approve button for UOB CC mapping")` — tests `NEEDS_MAPPING` → approve → `IMPORTED` flow with `uob_credit_card_xls_v1` parser key

### Verification
- [ ] `make api-rebuild` — containers build without errors
- [ ] `make web-rebuild` — frontend compiles without TypeScript errors
- [ ] `make api-smoke` — all smoke tests pass
- [ ] Manual: upload UOB CC fixture via Ingest page, verify transactions appear in `/credit-cards`

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
make task-plan TASK=tasks/issue-111-uob-credit-card-ingestion.md
make task-build TASK=tasks/issue-111-uob-credit-card-ingestion.md
make task-review TASK=tasks/issue-111-uob-credit-card-ingestion.md
make task-rework TASK=tasks/issue-111-uob-credit-card-ingestion.md
make task-ship TASK=tasks/issue-111-uob-credit-card-ingestion.md
```
