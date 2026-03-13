# Issue 110: UOB Account XLS Parser

## Objective
Build a parser for UOB bank account transaction history exported as `.xls` (binary Excel 97-2003 format via xlrd). The fixture file `data/fixtures/UOB_ACC_TXN_History_09032026225218.xls` contains real transaction data from a UOB "One Account" in SGD. The parser must follow the existing `ExcelParserProtocol`, integrate with the ingestion pipeline, and produce transactions + a cash position (available balance) via `ParseResult`. Additionally, remove the unused `UOB_CARDS` and `DBS_CARDS` platforms, consolidating credit card accounts under the parent bank platform.

### Sub-Objective: Remove UOB_CARDS / DBS_CARDS Platforms
**Analysis**: `UOB_CARDS` (platform_type=CARD_ISSUER) and `DBS_CARDS` (platform_type=CARD_ISSUER) are defined in `migrations/004_seed_reference_data.sql` lines 10–11. They are referenced **only** in:
- `migrations/seed_dummy.sql` lines 21, 28 (DBS_CARDS)
- `api/tests/conftest.py` line 438 (DBS_CARDS)

**No production code** (routers, models, services, frontend) references these platform codes. The spending router queries by `account_type = 'CREDIT_CARD'`, not by platform code. Credit card accounts should use the parent bank platform (`UOB` or `DBS`) with `account_type = CREDIT_CARD`. These redundant platform entries must be removed.

---

## Architecture Decisions

### Decision 1: ExcelParserProtocol (function-based, not class-based)
Follow the existing protocol-based parser design. The UOB parser is a standalone function `parse_uob_account_xls(file_path: str) -> ParseResult` matching `ExcelParserProtocol`. No base class inheritance—any function matching the signature works. This makes it **impossible for a new parser to break existing parsers** because:
- Each parser is a self-contained module with zero shared mutable state
- Parsers are registered in `PARSER_REGISTRY` dict by key; adding a new entry cannot affect existing entries
- The `ParseResult` dataclass is immutable output; parsers don't modify runner internals
- Format signatures are SHA256 hashes; a new file format cannot collide with existing signatures

### Decision 2: Transaction + Cash Position Output
The UOB XLS contains bank transactions (not holdings). Output pattern matches `dbs_transaction_history_csv_v1`:
- **Transactions**: Each row → `{ts, type, amount, currency, category, merchant_counterparty, notes}`
- **Positions**: One cash position from the last available balance → `{symbol: "SGD", asset_class: "CASH", quantity: <balance>}`
- Transaction classification: `INCOME` (deposits), `EXPENSE` (withdrawals), `TRANSFER` (GIRO/PayNow/internal transfers)

### Decision 3: Extend Signature Header Detection
The current `_find_header_row_excel()` in `signature.py` only recognizes stock-holdings tokens (`qty`, `symbol`, `market`, etc.). UOB transaction headers (`Transaction Date`, `Withdrawal`, `Deposit`) won't match. Add bank-transaction tokens (`transaction`, `withdrawal`, `deposit`) to the detection set so the signature system captures UOB column headers, producing a stable, specific signature hash.

### Decision 4: XLS Binary Format via xlrd + pandas
The UOB fixture is a real OLE2 binary `.xls` file (not HTML disguised as `.xls`). Use `pd.read_excel(engine='xlrd')` consistent with the existing `_pick_engine()` pattern in both `signature.py` and other XLS parsers.

### Decision 5: UOB_CARDS / DBS_CARDS Removal via New Migration
Add a migration (`024_remove_card_issuer_platforms.sql`) that deletes these platform rows. Update seed data and test fixtures to use `DBS` platform for credit card accounts. Do NOT modify the original `004_seed_reference_data.sql` migration (immutable migration history); instead, the new migration undoes the rows.

### Decision 6: UOB XLS Structure (from fixture analysis)
```
Header rows:
  - Row 0-3: Bank name, account holder, account number, currency, statement period
Column headers (row ~4):
  - Transaction Date | Transaction Description | Withdrawal | Deposit | Available Balance
Data rows:
  - Date format: "DD Mon YYYY" (e.g., "04 Mar 2026")
  - Amounts: numeric with comma thousands separator (e.g., 1,373.00)
  - Description: may span multiple sub-rows (GIRO codes, references, payee names)
  - Currency: always SGD (from header metadata)
```

---

## Risks

| Risk | Mitigation |
|------|-----------|
| Multi-line transaction descriptions in XLS | Parser must handle merged/grouped description cells; use pandas `fillna(method='ffill')` on date column to associate sub-rows with parent transaction |
| Signature collision with other XLS formats | Signature includes full header list + type profile; UOB headers are distinct from DBS Vickers/Sharekhan |
| xlrd not installed in container | Already a dependency (used by DBS Vickers and Sharekhan parsers); verify in requirements.txt |
| Removing UOB_CARDS/DBS_CARDS breaks existing accounts | No accounts in production reference these platforms; only seed/dummy data uses DBS_CARDS |
| Date parsing edge cases | Support multiple date formats like DBS parser; fallback to value date if transaction date missing |

---

## Open Questions

1. **Multi-row descriptions**: Does each transaction span exactly one data row, or does the description overflow into subsequent rows with empty date/amount cells? → Parser must handle both (forward-fill date column approach).
2. **Statement period metadata**: Should the parser extract the statement period (`01 Mar 2026 To 09 Mar 2026`) for the cash position `as_of` date? → Yes, use end date of statement period as `as_of` for the balance position.
3. **Future UOB credit card XLS**: Will UOB credit card statements follow the same format? → Likely not; defer to a separate parser when needed. The platform will be `UOB` with `account_type=CREDIT_CARD`.

---

## Acceptance Criteria

- [ ] `parse_uob_account_xls(file_path)` returns a valid `ParseResult` with transactions and cash position from the fixture file
- [ ] Parser correctly classifies transactions as INCOME (deposits), EXPENSE (withdrawals), or TRANSFER (GIRO/PayNow/internal)
- [ ] Parser extracts currency (SGD) and available balance from header/metadata rows
- [ ] Parser handles multi-line transaction descriptions (grouped by transaction date)
- [ ] Signature detection produces a stable, unique hash for UOB XLS files (distinct from all other registered signatures)
- [ ] New parser registered in `PARSER_REGISTRY` as `("excel", parse_uob_account_xls)`
- [ ] Migration `023_register_uob_account_parser.sql` registers the computed format_signature → `uob_account_xls_v1`
- [ ] End-to-end ingestion via `POST /ingest/upload?account_id=X` works with UOB XLS and reaches IMPORTED status
- [ ] Idempotent re-upload produces zero new inserts and correct `duplicates_skipped` count
- [ ] All existing parser tests pass without modification (regression-safe)
- [ ] `UOB_CARDS` and `DBS_CARDS` platform rows removed via migration `024_remove_card_issuer_platforms.sql`
- [ ] `seed_dummy.sql` updated: DBS credit card account uses platform `DBS` (not `DBS_CARDS`)
- [ ] Test fixture `conftest.py` updated: seed_spending_data uses platform `DBS` (not `DBS_CARDS`)
- [ ] `make test-backend` passes (all existing + new tests)
- [ ] `make api-rebuild` succeeds, `curl /health` returns 200

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist

### Backend: New Parser
- [ ] Create `api/app/ingestion/parsers/uob_account_xls_v1.py`
  - Function: `parse_uob_account_xls(file_path: str) -> ParseResult`
  - Follows `ExcelParserProtocol`
  - Uses pandas + xlrd engine
  - Extracts: account holder, currency, statement period from header rows
  - Finds header row with columns: Transaction Date, Transaction Description, Withdrawal, Deposit, Available Balance
  - Parses transactions with date format `DD Mon YYYY`
  - Classifies: INCOME (deposit), EXPENSE (withdrawal), TRANSFER (GIRO/PayNow/internal)
  - Extracts cash position from last available balance
  - Returns `ParseResult(transactions=[...], positions=[cash_pos], section_counts={...}, parser_meta={...})`

### Backend: Registry Integration
- [ ] Update `api/app/ingestion/runner.py`:
  - Add import: `from app.ingestion.parsers.uob_account_xls_v1 import parse_uob_account_xls`
  - Add to `PARSER_REGISTRY`: `"uob_account_xls_v1": ("excel", parse_uob_account_xls)`
- [ ] Update `api/app/ingestion/signature.py`:
  - Add tokens `"transaction"`, `"withdrawal"`, `"deposit"` to `_find_header_row_excel()` token set
  - This enables header detection for bank transaction XLS files (UOB and potentially future bank parsers)

### Database: Migrations
- [ ] Create `migrations/023_register_uob_account_parser.sql`:
  - Compute format_signature from the UOB fixture file
  - `INSERT INTO parser_registry (format_signature, parser_key, version) VALUES ('<sha256>', 'uob_account_xls_v1', 1) ON CONFLICT (format_signature) DO NOTHING;`
- [ ] Create `migrations/024_remove_card_issuer_platforms.sql`:
  - `DELETE FROM platforms WHERE code IN ('UOB_CARDS', 'DBS_CARDS');`
  - Update any accounts referencing these platforms: `UPDATE accounts SET platform = REPLACE(platform, '_CARDS', ''), platform_id = (SELECT id FROM platforms WHERE code = REPLACE(accounts.platform, '_CARDS', '')) WHERE platform IN ('UOB_CARDS', 'DBS_CARDS');`
- [ ] Update `migrations/seed_dummy.sql`:
  - Line 21: Remove `'DBS_CARDS'` from the CTE WHERE clause
  - Line 28: Change `'DBS_CARDS'` → `'DBS'` for the dummy credit card account

### Tests
- [ ] Create `api/tests/test_uob_account_parser.py` (unit tests):
  - `test_uob_parser_extracts_transactions_and_balance`: Parse fixture → verify transaction count, types, amounts, currency
  - `test_uob_parser_classifies_transfers`: Verify GIRO/PayNow transactions → type=TRANSFER
  - `test_uob_parser_extracts_cash_position`: Verify cash position from available balance
  - `test_uob_parser_date_parsing`: Verify "DD Mon YYYY" date format handling
  - `test_uob_parser_empty_file`: Empty/invalid XLS → empty ParseResult (no crash)
  - `test_uob_parser_handles_multiline_descriptions`: Forward-fill date for grouped rows
- [ ] Create `api/tests/test_ingest_uob_account.py` (integration tests):
  - `test_uob_ingest_upload_and_import`: Upload UOB XLS → IMPORTED status, transactions inserted
  - `test_uob_ingest_idempotent`: Re-upload same file → duplicates_skipped = prior inserts
  - `test_uob_signature_stable`: Signature is deterministic across runs
- [ ] Update `api/tests/conftest.py`:
  - Line 438: Change `'DBS_CARDS'` → `'DBS'` in seed_spending_data

### Regression Safety
- [ ] Run full test suite: `make test-backend` — all existing tests pass
- [ ] Verify no existing parser is affected: test_parsers.py, test_ingest.py, test_ingest_citi_cc.py, test_ingest_dbs_vickers.py, test_ingest_sharekhan.py, test_signature.py all green
- [ ] Verify signature stability: existing format signatures unchanged (IBKR, DBS, Sharekhan, Citi CC)

### Verification
- [ ] `make api-rebuild` — container builds successfully
- [ ] `curl http://localhost:8000/health` — returns 200
- [ ] `make api-smoke` — smoke tests pass
- [ ] Manual curl test: upload UOB XLS via `/ingest/upload?account_id=<uob_account_id>`

---

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
make task-plan TASK=tasks/issue-110-uob-account-xls-parser.md
make task-build TASK=tasks/issue-110-uob-account-xls-parser.md
make task-review TASK=tasks/issue-110-uob-account-xls-parser.md
make task-rework TASK=tasks/issue-110-uob-account-xls-parser.md
make task-ship TASK=tasks/issue-110-uob-account-xls-parser.md
```
