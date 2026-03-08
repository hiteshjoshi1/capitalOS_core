# Issue 105: Citibank Credit Card Parser

## Objective

Build a parser for Citibank credit card CSV statements (`citi_credit_card_sample.csv`) and integrate it into the existing ingest pipeline. The parser must handle multi-month data in a single file, normalize transactions into the standard `transactions` table format, and be invocable from the existing Ingest page via CSV upload. UI changes for the Expenses Credit Card dashboard section are **out of scope** for this issue.

---

## Architecture Decisions

### Decision 1: Headerless CSV Detection via Structural Fingerprint

The Citibank CSV has **no header row** — data starts on line 1. The current `_find_flat_header()` in `signature.Now I have complete understanding of the codebase. Let me compose the task file.Now I have a complete picture of the architecture. Let me compose the final task file.

# Issue 105: Citibank Credit Card Parser

## Objective
Build a parser for Citibank credit card statement CSVs (`citi_credit_card_sample.csv` in `data/fixtures/`) and integrate it into the existing ingest pipeline so that users can upload Citibank CC statements via the Ingest page and have transactions imported into the `transactions` table. The parser must handle multi-month data in a single file without assuming a fixed number of months. UI changes for Expenses display are **out of scope** for this issue.

---

## Architecture Decisions

### Decision 1: Headerless CSV Detection via Structural Heuristic

The Citibank CC CSV has **no header row** — data starts on line 1. The current `_find_flat_header()` in `signature.py` falls back to treating the first data row as header fields, producing a signature that changes with every file (because the first row's data values differ). This is unsuitable.

**Solution:** Add a `_detect_citi_cc()` function in `signature.py` that identifies the Citibank CC format by structural heuristics before falling back to `_find_flat_header()`:
- Exactly 5 columns
- Column 1 matches `DD/MM/YYYY` date pattern
- Column 3 is a signed numeric value (amount)
- Column 4 is empty
- Column 5 matches a card-number-like pattern (quoted digits)

When detected, produce a **stable signature** using `file_kind=citi_credit_card_csv`, `platform_hint`, and `column_count=5` — not the volatile first-row data.

### Decision 2: Conform to Existing Parser Contract

The parser will follow the 3-tuple return contract used by IBKR and DBS parsers:
```python
def parse_citi_credit_card_csv(file_path: str, delimiter: str) -> Tuple[List[Dict], List[Dict], Dict[str, int]]
```
Returns `(transactions, positions=[], section_counts)`. Credit card CSVs have no positions (no balance snapshot in the file).

### Decision 3: Transaction Type Mapping

| CSV Pattern | `type` | Sign | Category |
|---|---|---|---|
| Negative amount (default) | `EXPENSE` | Negative (as-is) | `CreditCard::Purchase` |
| `PAYMENT - THANK YOU` | `TRANSFER` | Positive (as-is) | `CreditCard::Payment` |
| `LATE CHARGE FEE` / `LATE CHARGE FEE REVERSAL` | `FEE` | Signed (as-is) | `CreditCard::Fee` |
| `BILLED FINANCE CHARGES` | `INTEREST` | Negative (as-is) | `CreditCard::Interest` |
| `RTL INT CRED ADJ` | `INTEREST` | Positive (as-is) | `CreditCard::Interest` |
| Other positive amounts (refunds) | `INCOME` | Positive (as-is) | `CreditCard::Refund` |

All amounts are preserved as-is from the CSV (negative = money out, positive = money in), consistent with the existing signed-amount convention in the `transactions` table.

### Decision 4: Foreign Currency Extraction

Some descriptions embed foreign currency info (e.g., `"OPENAI *CHATGPT SUBSCR   OPENAI.COM   US USD 21.80 USD 21.80"`). The parser will:
- Extract original foreign currency and amount from the description when the pattern `<CURRENCY_CODE> <AMOUNT>` is detected at the end
- Store the foreign currency info in `notes` for auditability
- Use `SGD` as the transaction `currency` since the amount column is always in SGD (the billed amount)

### Decision 5: Card Number Handling

Column 5 contains the card number (e.g., `'4147464004225540'`). The parser will:
- Strip surrounding quotes
- Store it in `notes` alongside any foreign currency info for traceability
- **Not** use it as a key for account lookup (the user selects the account at upload time)

### Decision 6: Date Parsing

Dates are in `DD/MM/YYYY` format. The parser will parse into UTC datetime objects consistent with the DBS parser approach.

### Decision 7: Merchant Name Extraction

The description field contains the merchant name, often padded with spaces and suffixed with location info (e.g., `"SHENG SIONG SUPERMARKET -SINGAPORE    SG"`). The parser will:
- Trim leading/trailing whitespace
- Keep the full description as `merchant_counterparty` (no location stripping — preserves auditability)

---

## Risks

1. **Signature stability**: If Citibank changes their CSV column count or format, the heuristic detection will fail. Mitigation: the NEEDS_MAPPING fallback allows manual re-registration.
2. **Date ambiguity**: DD/MM/YYYY is unambiguous for this dataset (Singapore locale), but if Citibank ever changes to MM/DD/YYYY, parsing would silently produce wrong dates. Mitigation: validate that parsed dates are within a reasonable range (not in the future, not before 2020).
3. **No BOM handling**: The sample file has a UTF-8 BOM (`﻿`). Must use `utf-8-sig` encoding (consistent with existing parsers).
4. **Duplicate detection**: Re-uploading the same file should skip all rows. The existing fingerprint logic covers this.

---

## Open Questions

1. **Should the parser attempt to deduplicate across overlapping multi-month uploads?** Current dedup logic (account_id + ts + type + amount + currency + merchant + category) should handle this naturally. No additional logic needed.
2. **Should foreign currency transactions be stored with the original currency or SGD?** Decision: SGD (the billed amount), with original currency info in `notes`. This matches how the credit card statement works — the cardholder owes SGD.

---

## Architectural Observations (Not In Scope — For Human Review)

The following are not bugs but areas where the codebase could benefit from refactoring in a future issue. **The build stage will NOT implement these.**

### 1. Parser Dispatch is a Growing if/elif Chain
`runner.py` lines 196–211 use `if parser_key == "ibkr_activity_csv_v1": ... elif ...`. Adding Citi CC extends this to 5 branches. A registry-pattern dict (`PARSERS = {"ibkr_activity_csv_v1": parse_ibkr_activity_csv, ...}`) would be cleaner and follow the Open/Closed Principle.

### 2. Inconsistent Parser Return Types
IBKR and DBS parsers return `Tuple[List, List, Dict]` (3-tuple). Sharekhan and DBS Vickers return `Tuple[List, List, Dict, Dict]` (4-tuple with `parser_meta`). The Citi CC parser will use the 3-tuple form. A future refactor should standardize all parsers to a common interface (e.g., a `ParseResult` dataclass).

### 3. No Abstract Parser Interface
There is no base class or protocol defining what a parser must implement. Each parser is a standalone function with a similar but not identical signature. A `Protocol` or ABC would improve discoverability and type safety.

### 4. Signature Detection Order Could Be Formalized
`compute_format_signature()` checks IBKR first, then falls back to flat CSV. Adding Citi CC detection introduces another check. A chain-of-responsibility or ordered-list-of-detectors pattern would scale better.

### 5. Frontend Approval Buttons are Hardcoded per Platform
`Ingest.tsx` has separate `if (reportData.platform === "IBKR")` blocks for each platform. A data-driven approach mapping platform → parser_key would reduce repetition.

---

## Acceptance Criteria

- [ ] New parser file `api/app/ingestion/parsers/citi_credit_card_csv_v1.py` exists and correctly parses the fixture CSV
- [ ] All 52 lines of `citi_credit_card_sample.csv` are parsed into transactions with correct dates, amounts, types, and categories
- [ ] Headerless Citibank CC CSV format is detected by `signature.py` with a stable signature (same signature regardless of which Citibank CSV is uploaded)
- [ ] Migration `021_register_citi_cc_parser.sql` registers the computed signature to parser_key `citi_credit_card_csv_v1`
- [ ] `runner.py` dispatches to `parse_citi_credit_card_csv` when `parser_key == "citi_credit_card_csv_v1"`
- [ ] Transactions use signed amounts: negative for expenses/fees/interest, positive for payments/refunds
- [ ] `PAYMENT - THANK YOU` rows are typed as `TRANSFER`
- [ ] `LATE CHARGE FEE` and reversals are typed as `FEE`
- [ ] `BILLED FINANCE CHARGES` and `RTL INT CRED ADJ` are typed as `INTEREST`
- [ ] Currency is `SGD` for all transactions; foreign currency info stored in `notes`
- [ ] Re-uploading the same file produces 0 inserts / all duplicates
- [ ] Frontend Ingest page shows "Approve as Citi CC" button when platform is `CITI` and status is `NEEDS_MAPPING`
- [ ] `make api-rebuild` succeeds with no import errors
- [ ] `make web-rebuild` succeeds with no TypeScript errors
- [ ] Existing parser tests still pass (no regressions)

---

## Human Approval Gate

- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist

### Backend — Parser (`api/app/ingestion/parsers/citi_credit_card_csv_v1.py`)
- [ ] Create `parse_citi_credit_card_csv(file_path: str, delimiter: str) -> Tuple[List[Dict], List[Dict], Dict[str, int]]`
- [ ] Parse DD/MM/YYYY dates into UTC datetime objects
- [ ] Map transaction types: EXPENSE, TRANSFER, FEE, INTEREST, INCOME based on description patterns
- [ ] Set `currency` to `SGD`, extract foreign currency details into `notes`
- [ ] Strip card number quotes, include in `notes`
- [ ] Set `merchant_counterparty` from description column
- [ ] Set `category` per mapping table (CreditCard::Purchase, CreditCard::Payment, etc.)
- [ ] Return `positions=[]` (no balance data in CC statements)
- [ ] Handle BOM via `utf-8-sig` encoding

### Backend — Signature Detection (`api/app/ingestion/signature.py`)
- [ ] Add `_detect_citi_cc(lines, delimiter)` heuristic function
- [ ] Check: 5 columns, col1=DD/MM/YYYY, col3=numeric, col4=empty, col5=card-number pattern
- [ ] Generate stable signature: `file_kind=citi_credit_card_csv`, `delimiter`, `platform_hint`, `column_count=5`
- [ ] Insert detection check in `compute_format_signature()` after IBKR check but before flat CSV fallback

### Backend — Runner Integration (`api/app/ingestion/runner.py`)
- [ ] Add `from app.ingestion.parsers.citi_credit_card_csv_v1 import parse_citi_credit_card_csv`
- [ ] Add `elif parser_key == "citi_credit_card_csv_v1":` dispatch block
- [ ] Pass `delimiter` to parser (consistent with IBKR/DBS pattern)

### Database — Migration (`migrations/021_register_citi_cc_parser.sql`)
- [ ] Compute the exact SHA-256 signature that `_detect_citi_cc` will produce
- [ ] Insert into `parser_registry` with `parser_key='citi_credit_card_csv_v1'`, `version=1`

### Frontend — Ingest Page (`web/src/routes/Ingest.tsx`)
- [ ] Add `CITI` platform approval button block (matching pattern of existing IBKR/DBS/Sharekhan/DBS_VICKERS blocks)
- [ ] Button text: "Approve as Citi CC"
- [ ] Parser key: `citi_credit_card_csv_v1`

### Testing
- [ ] Add `api/tests/test_ingest_citi_cc.py` with:
  - Parse fixture file and verify transaction count
  - Verify date parsing correctness
  - Verify type mapping (EXPENSE, TRANSFER, FEE, INTEREST)
  - Verify amount signs
  - Verify currency = SGD
  - Verify duplicate detection on re-parse
- [ ] Run existing test suite — no regressions

### Verification
- [ ] `make api-rebuild` — containers start, no import errors
- [ ] `make web-rebuild` — TypeScript compiles
- [ ] `curl http://localhost:8000/health` returns `{"status":"ok"}`
- [ ] Upload `citi_credit_card_sample.csv` via Ingest page → status IMPORTED
- [ ] Re-upload same file → 0 inserted, all duplicates

---

## Workflow Commands

```bash
# 1. Create feature branch
git checkout -b feature/issue-105-citi-cc-parser

# 2. Implement changes (see checklist above)

# 3. Rebuild and verify backend
TASK=tasks/issue-105-citibank-credit-card-parser.md make api-rebuild
curl http://localhost:8000/health

# 4. Rebuild and verify frontend
TASK=tasks/issue-105-citibank-credit-card-parser.md make web-rebuild

# 5. Run tests
TASK=tasks/issue-105-citibank-credit-card-parser.md make api-smoke

# 6. Manual smoke test
# Upload citi_credit_card_sample.csv via http://localhost:5173/ingest
# Verify: 52 transactions parsed, correct types, SGD currency

# 7. Commit
git add -A
git commit -m "feat(ingest): add Citibank credit card CSV parser (issue-105)

- New parser: citi_credit_card_csv_v1
- Headerless CSV detection heuristic in signature.py
- Migration 021 registers parser signature
- Frontend approval button for CITI platform
- Transaction type mapping: Purchase/Payment/Fee/Interest

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

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
