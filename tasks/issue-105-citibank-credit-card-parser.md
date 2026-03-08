# Issue 105: Citibank Credit Card Parser

## Objective

Build a parser for Citibank credit card statement CSVs (`citi_credit_card_sample.csv` in `data/fixtures/`) and integrate it into the existing ingest pipeline so that users can upload Citibank CC statements via the Ingest page and have transactions imported into the `transactions` table. The parser must handle multi-month data in a single file without assuming a fixed number of months.

As part of this change, refactor the ingest pipeline to address accumulated structural debt: replace the growing if/elif parser dispatch chain with a registry pattern, standardize parser return types into a `ParseResult` dataclass, formalize signature detection ordering, and make frontend approval buttons data-driven. All existing parsers must continue to work identically after refactoring — zero regressions.

UI changes for Expenses display are **out of scope** for this issue.

---

## Architecture Decisions

### AD-1: Headerless CSV Detection via Structural Heuristic

The Citibank CC CSV has **no header row** — data starts on line 1. The current `_find_flat_header()` in `signature.py` falls back to treating the first data row as header fields, producing a signature that changes with every file (volatile first-row data). This is unsuitable.

**Solution:** Add a `_detect_citi_cc(lines, delimiter, platform_hint)` function in `signature.py` that identifies the Citibank CC format by structural heuristics:
- Exactly 5 columns
- Column 1 matches `DD/MM/YYYY` date pattern
- Column 3 is a signed numeric value (amount)
- Column 4 is empty
- Column 5 matches a card-number-like pattern (quoted digits)

When detected, produce a **stable signature** using `file_kind=citi_credit_card_csv`, `delimiter`, `platform_hint`, and `column_count=5` — not the volatile first-row data.

### AD-2: Formalize Signature Detection Order (Chain-of-Detectors)

**Problem:** `compute_format_signature()` currently checks IBKR first via `_detect_ibkr()`, then falls flat CSV. Adding Citi CC introduces another check. The grow-by-insertion pattern doesn't scale.

**Solution:** Refactor `compute_format_signature()` to iterate an ordered list of detector functions:
```python
CSV_DETECTORS = [
    _detect_ibkr,
    _detect_citi_cc,
    # future detectors added here
]
```
Each detector returns `Optional[Tuple[str, dict]]` — signature + debug dict on match, `None` on miss. If no detector matches, fall back to flat CSV signature (existing behaviour preserved). This follows the chain-of-responsibility pattern and satisfies the Open/Closed Principle.

### AD-3: Standardized Parser Return Type (`ParseResult` Dataclass)

**Problem:** CSV parsers return 3-tuples `(transactions, positions, section_counts)` while Excel parsers return 4-tuples `(transactions, positions, section_counts, parser_meta)`. This inconsistency forces the runner to handle both shapes.

**Solution:** Create `api/app/ingestion/parsers/base.py` with:
```python
@dataclass
class ParseResult:
    transactions: list[dict]
    positions: list[dict]
    section_counts: dict[str, int]
    parser_meta: dict[str, Any] = field(default_factory=dict)
```
Update **all existing parsers** (IBKR, DBS, Sharekhan, DBS Vickers) and the new Citi CC parser to return `ParseResult`. Update `runner.py` to consume `ParseResult` uniformly. The runner's `parser_meta` handling simplifies to `result.parser_meta` for all parsers.

### AD-4: Parser Registry Pattern (Replace if/elif Chain)

**Problem:** `runner.py` lines 196–211 use a growing if/elif chain for parser dispatch. Adding Citi CC extends it to 5 branches.

**Solution:** Create a parser registry dict in `runner.py` (or in `parsers/__init__.py`):
```python
PARSER_REGISTRY: dict[str, tuple[str, Callable]] = {
    "ibkr_activity_csv_v1":             ("csv",   parse_ibkr_activity_csv),
    "dbs_transaction_history_csv_v1":   ("csv",   parse_dbs_transaction_history_csv),
    "sharekhan_holdings_xls_v1":        ("excel", parse_sharekhan_holdings_xls),
    "dbs_vickers_holdings_xls_v1":      ("excel", parse_dbs_vickers_holdings_xls),
    "citi_credit_card_csv_v1":          ("csv",   parse_citi_credit_card_csv),
}
```
Dispatch logic becomes:
```python
entry = PARSER_REGISTRY.get(parser_key)
if not entry:
    # FAILED — unsupported parser_key
kind, parser_fn = entry
if kind == "csv":
    result = parser_fn(file_path, delimiter)
elif kind == "excel":
    result = parser_fn(file_path)
```
Adding a new parser = one line in the registry dict. No `elif` needed.

### AD-5: Data-Driven Frontend Approval Buttons

**Problem:** `Ingest.tsx` has separate `if (reportData.platform === "IBKR")` blocks for each platform. Adding Citi requires another block.

**Solution:** Replace with a platform→parser config map:
```tsx
const PLATFORM_PARSERS: Record<string, { key: string; label: string }> = {
  IBKR:        { key: "ibkr_activity_csv_v1",             label: "Approve as IBKR" },
  DBS:         { key: "dbs_transaction_history_csv_v1",   label: "Approve as DBS" },
  SHAREKHAN:   { key: "sharekhan_holdings_xls_v1",        label: "Approve as Sharekhan" },
  DBS_VICKERS: { key: "dbs_vickers_holdings_xls_v1",      label: "Approve as DBS Vickers" },
  CITI:        { key: "citi_credit_card_csv_v1",           label: "Approve as Citi CC" },
};
```
Render a single conditional block that looks up the platform in the map. Adding a new platform = one line in the config.

### AD-6: Citi CC Parser Contract

The parser follows the new `ParseResult` contract:
```python
def parse_citi_credit_card_csv(file_path: str, delimiter: str) -> ParseResult
```
Returns `ParseResult(transactions=[...], positions=[], section_counts={"transactions": N}, parser_meta={})`. Credit card CSVs have no positions (no balance snapshot).

### AD-7: Transaction Type Mapping

| CSV Pattern | `type` | Sign | Category |
|---|---|---|---|
| Negative amount (default) | `EXPENSE` | Negative (as-is) | `CreditCard::Purchase` |
| `PAYMENT - THANK YOU` | `TRANSFER` | Positive (as-is) | `CreditCard::Payment` |
| `LATE CHARGE FEE` / `LATE CHARGE FEE REVERSAL` | `FEE` | Signed (as-is) | `CreditCard::Fee` |
| `BILLED FINANCE CHARGES` | `INTEREST` | Negative (as-is) | `CreditCard::Interest` |
| `RTL INT CRED ADJ` | `INTEREST` | Positive (as-is) | `CreditCard::Interest` |
| Other positive amounts (refunds) | `INCOME` | Positive (as-is) | `CreditCard::Refund` |

All amounts are preserved as-is from the CSV (negative = money out, positive = money in), consistent with the existing signed-amount convention in the `transactions` table.

### AD-8: Foreign Currency Extraction

Some descriptions embed foreign currency info (e.g., `"OPENAI *CHATGPT SUBSCR   OPENAI.COM   US USD 21.80 USD 21.80"`). The parser will:
- Extract original foreign currency and amount from the description when the pattern `<CURRENCY_CODE> <AMOUNT>` is detected at the end
- Store the foreign currency info in `notes` for auditability
- Use `SGD` as the transaction `currency` since the amount column is always in SGD (the billed amount)

### AD-9: Date Parsing & Card Number Handling

- Dates are in `DD/MM/YYYY` format → parsed into UTC datetime objects (consistent with DBS parser)
- Card number (column 5, e.g., `'4147464004225540'`) → stripped of surrounding quotes, included in `notes`
- Full description kept as `merchant_counterparty` (trimmed whitespace, no location stripping — preserves auditability)

---

## Risks

1. **Regression from refactoring** (MEDIUM): Changing parser return types and dispatch logic across all parsers risks breaking existing flows. Mitigation: run full existing test suite after each refactoring step; add explicit regression tests per parser type.
2. **Signature stability** (LOW): If Citibank changes their CSV column count or format, the heuristic detection will fail. Mitigation: `NEEDS_MAPPING` fallback allows manual re-registration.
3. **Date ambiguity** (LOW): DD/MM/YYYY is unambiguous for this dataset (Singapore locale), but if● Response was interrupted due to a server error. Retrying...

Now I have full context. Let me compose the comprehensive task file.

# Issue 105: Citibank Credit Card Parser

## Objective

Build a parser for Citibank credit card statement CSVs (`data/fixtures/citi_credit_card_sample.csv`) and integrate it into the existing ingest pipeline so that users can upload Citibank CC statements via the Ingest page and have transactions imported into the `transactions` table. The parser must handle multi-month data in a single file without assuming a fixed number of months. UI changes for the Expenses Credit Card dashboard section are **out of scope** for this issue.

Additionally, this issue incorporates five architectural improvements to the ingest pipeline that directly support clean integration of the new parser and improve maintainability for future parsers:
1. Replace the if/elif parser dispatch chain with a registry dict
2. Standardize all parsers on a common `ParseResult` dataclass
3. Define a `ParserProtocol` for type safety
4. Formalize signature detection as an ordered chain of detectors
5. Replace hardcoded frontend platform approval buttons with a data-driven config

All existing parsers (IBKR, DBS, Sharekhan, DBS Vickers) must continue to work identically after these changes — zero regressions.

---

## Architecture Decisions

### Decision 1: Headerless CSV Detection via Structural Heuristic

The Citibank CC CSV has **no header row** — data starts on line 1. The current `_find_flat_header()` in `signature.py` falls back to treating the first data row as header fields, producing a signature that changes with every file (because the first row's data values differ). This is unsuitable.

**Solution:** Add a `_detect_citi_cc(lines, delimiter)` function in `signature.py` that identifies the Citibank CC format by structural heuristics before falling back to `_find_flat_header()`:
- Exactly 5 columns
- Column 1 matches `DD/MM/YYYY` date pattern
- Column 3 is a signed numeric value (amount)
- Column 4 is empty
- Column 5 matches a card-number-like pattern (quoted digits with surrounding single quotes)

When detected, produce a **stable signature** using `file_kind=citi_credit_card_csv`, `delimiter`, `platform_hint`, and `column_count=5` — not the volatile first-row data.

### Decision 2: Conform to Standardized ParseResult Contract

All parsers (existing and new) will return a `ParseResult` dataclass instead of bare tuples:

```python
@dataclass
class ParseResult:
    transactions: List[Dict]
    positions: List[Dict]
    section_counts: Dict[str, int]
    parser_meta: Dict[str, Any] = field(default_factory=dict)
```

The Citi CC parser returns `ParseResult(transactions=..., positions=[], section_counts={"transactions": N})`. Existing parsers (IBKR, DBS returning 3-tuples; Sharekhan, DBS Vickers returning 4-tuples) are updated to return `ParseResult`. This eliminates the inconsistent 3-tuple vs 4-tuple return types.

### Decision 3: Parser Registry Dict (Replace if/elif Chain)

Replace the growing if/elif chain in `runner.py` (lines 196–211) with a `PARSER_REGISTRY` dict:

```python
PARSER_REGISTRY: Dict[str, Callable[..., ParseResult]] = {
    "ibkr_activity_csv_v1": parse_ibkr_activity_csv,
    "dbs_transaction_history_csv_v1": parse_dbs_transaction_history_csv,
    "sharekhan_holdings_xls_v1": parse_sharekhan_holdings_xls,
    "dbs_vickers_holdings_xls_v1": parse_dbs_vickers_holdings_xls,
    "citi_credit_card_csv_v1": parse_citi_credit_card_csv,
}
```

Dispatch becomes `parser_fn = PARSER_REGISTRY.get(parser_key)` → call with appropriate args. CSV parsers receive `(file_path, delimiter)`, XLS parsers receive `(file_path,)`. The registry entry determines which argument pattern to use (CSV parsers require delimiter; XLS parsers do not).

### Decision 4: Parser Protocol for Type Safety

Define a `ParserProtocol` in `api/app/ingestion/parsers/__init__.py`:

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class CsvParserProtocol(Protocol):
    def __call__(self, file_path: str, delimiter: str) -> ParseResult: ...

@runtime_checkable
class ExcelParserProtocol(Protocol):
    def __call__(self, file_path: str) -> ParseResult: ...
```

This is purely for documentation and IDE support — no ABC inheritance required.

### Decision 5: Formalized Signature Detection Chain

Replace the ad-hoc detection ordering in `compute_format_signature()` with an ordered list of detector functions:

```python
_CSV_DETECTORS: List[Callable] = [
    _detect_ibkr,
    _detect_citi_cc,
    # future detectors here
]
```

Each detector returns `Optional[Tuple[str, dict]]` — the signature and debug info if detected, `None` otherwise. `compute_format_signature()` iterates detectors, returning the first match, with `_flat_csv_signature()` as the fallback.

### Decision 6: Data-Driven Frontend Approval Buttons

Replace the hardcoded per-platform `if (reportData.platform === "IBKR")` blocks in `Ingest.tsx` with a config-driven approach:

```typescript
const PLATFORM_PARSERS: Record<string, { label: string; parserKey: string }> = {
  IBKR: { label: "Approve as IBKR", parserKey: "ibkr_activity_csv_v1" },
  DBS: { label: "Approve as DBS", parserKey: "dbs_transaction_history_csv_v1" },
  SHAREKHAN: { label: "Approve as Sharekhan", parserKey: "sharekhan_holdings_xls_v1" },
  DBS_VICKERS: { label: "Approve as DBS Vickers", parserKey: "dbs_vickers_holdings_xls_v1" },
  CITI: { label: "Approve as Citi CC", parserKey: "citi_credit_card_csv_v1" },
};
```

The JSX renders by looking up `reportData.platform` in the map — one block instead of five.

### Decision 7: Transaction Type Mapping

| CSV Pattern | `type` | Sign | Category |
|---|---|---|---|
| Negative amount (default) | `EXPENSE` | Negative (as-is) | `CreditCard::Purchase` |
| `PAYMENT - THANK YOU` | `TRANSFER` | Positive (as-is) | `CreditCard::Payment` |
| `LATE CHARGE FEE` / `LATE CHARGE FEE REVERSAL` | `FEE` | Signed (as-is) | `CreditCard::Fee` |
| `BILLED FINANCE CHARGES` | `INTEREST` | Negative (as-is) | `CreditCard::Interest` |
| `RTL INT CRED ADJ` | `INTEREST` | Positive (as-is) | `CreditCard::Interest` |
| Other positive amounts (refunds, e.g., FIREFLIES.AI refund) | `INCOME` | Positive (as-is) | `CreditCard::Refund` |

All amounts are preserved as-is from the CSV (negative = money out, positive = money in), consistent with the existing signed-amount convention in the `transactions` table.

Expected fixture breakdown (51 data rows):
- 42 EXPENSE (negative amounts, standard purchases)
- 2 TRANSFER (PAYMENT - THANK YOU)
- 2 FEE (LATE CHARGE FEE + LATE CHARGE FEE REVERSAL)
- 4 INTEREST (2 × BILLED FINANCE CHARGES + 2 × RTL INT CRED ADJ)
- 1 INCOME/Refund (FIREFLIES.AI positive amount, not matching any keyword pattern)

### Decision 8: Foreign Currency Extraction

Some descriptions embed foreign currency info (e.g., `"OPENAI *CHATGPT SUBSCR   OPENAI.COM   US USD 21.80 USD 21.80"`). The parser will:
- Extract original foreign currency and amount from the description when the pattern `<CURRENCY_CODE> <AMOUNT>` is detected at the end
- Store the foreign currency info in `notes` for auditability
- Use `SGD` as the transaction `currency` since the amount column is always in SGD (the billed amount)

### Decision 9: Card Number Handling

Column 5 contains the card number (e.g., `'4147464004225540'`). The parser will:
- Strip surrounding quotes (both double and single)
- Store it in `notes` alongside any foreign currency info for traceability
- **Not** use it as a key for account lookup (the user selects the account at upload time)

### Decision 10: Date Parsing

Dates are in `DD/MM/YYYY` format. The parser will parse into UTC datetime objects consistent with the DBS parser approach.

### Decision 11: Merchant Name Extraction

The description field contains the merchant name, often padded with spaces and suffixed with location info. The parser will:
- Trim leading/trailing whitespace
- Keep the full description as `merchant_counterparty` (no location stripping — preserves auditability)

---

## Risks

1. **Regression from architecture refactor**: Changing all parser return types and the dispatch mechanism touches every parser path. Mitigation: comprehensive regression test suite; run ALL existing ingestion tests before and after changes.
2. **Signature stability**: If Citibank changes their CSV column count or format, the heuristic detection will fail. Mitigation: the NEEDS_MAPPING fallback allows manual re-registration.
3. **Date ambiguity**: DD/MM/YYYY is unambiguous for this dataset (Singapore locale), but if Citibank ever changes to MM/DD/YYYY, parsing would silently produce wrong dates. Mitigation: validate that parsed dates are within a reasonable range (not in the future, not before 2020).
4. **No BOM handling**: The sample file has a UTF-8 BOM (`﻿`). Must use `utf-8-sig` encoding (consistent with existing `compute_format_signature` which already uses `utf-8-sig`).
5. **Frontend approval button refactor**: Changing the JSX structure could break existing platform approval flows. Mitigation: verify IBKR, DBS, Sharekhan, and DBS Vickers buttons still render correctly in frontend tests.
6. **Duplicate detection**: Re-uploading the same file should skip all rows. The existing fingerprint logic (`_fingerprint()` in runner.py) covers this.

---

## Open Questions

1. **Should the parser attempt to deduplicate across overlapping multi-month uploads?** Current dedup logic (account_id + ts + type + amount + currency + merchant + category) handles this naturally. No additional logic needed.
2. **Should foreign currency transactions be stored with the original currency or SGD?** Decision: SGD (the billed amount), with original currency info in `notes`. This matches how the credit card statement works — the cardholder owes SGD.

---

## Acceptance Criteria

- [ ] New parser file `api/app/ingestion/parsers/citi_credit_card_csv_v1.py` exists and correctly parses the fixture CSV
- [ ] All 51 data lines of `citi_credit_card_sample.csv` are parsed into transactions with correct dates, amounts, types, and categories
- [ ] Headerless Citibank CC CSV format is detected by `signature.py` with a stable signature (same signature regardless of which Citibank CSV is uploaded)
- [ ] Migration `021_register_citi_cc_parser.sql` registers the computed signature to parser_key `citi_credit_card_csv_v1`
- [ ] `runner.py` uses `PARSER_REGISTRY` dict for dispatch (no if/elif chain)
- [ ] All parsers return `ParseResult` dataclass (no bare tuples)
- [ ] `ParserProtocol` types defined in `parsers/__init__.py`
- [ ] Signature detection uses ordered `_CSV_DETECTORS` chain
- [ ] Frontend uses `PLATFORM_PARSERS` config map for approval buttons (no hardcoded per-platform blocks)
- [ ] Transactions use signed amounts: negative for expenses/fees/interest, positive for payments/refunds
- [ ] `PAYMENT - THANK YOU` rows are typed as `TRANSFER`
- [ ] `LATE CHARGE FEE` and reversals are typed as `FEE`
- [ ] `BILLED FINANCE CHARGES` and `RTL INT CRED ADJ` are typed as `INTEREST`
- [ ] Currency is `SGD` for all transactions; foreign currency info stored in `notes`
- [ ] Re-uploading the same file produces 0 inserts / all duplicates
- [ ] Frontend Ingest page shows "Approve as Citi CC" button when platform is `CITI` and status is `NEEDS_MAPPING`
- [ ] `make api-rebuild` succeeds with no import errors
- [ ] `make web-rebuild` succeeds with no TypeScript errors
- [ ] ALL existing parser tests pass — zero regressions (IBKR, DBS, Sharekhan, DBS Vickers)
- [ ] ALL existing frontend tests pass — zero regressions
- [ ] E2E tests pass if configured

---

## Human Approval Gate

- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist

### Phase 1: Architecture Refactor (Before Citi CC Parser)

#### 1A: ParseResult Dataclass (`api/app/ingestion/parsers/__init__.py`)
- [ ] Define `ParseResult` dataclass with fields: `transactions`, `positions`, `section_counts`, `parser_meta`
- [ ] Define `CsvParserProtocol` and `ExcelParserProtocol` using `typing.Protocol`
- [ ] Export all from `__init__.py`

#### 1B: Update Existing Parsers to Return ParseResult
- [ ] Update `ibkr_activity_csv_v1.py`: return `ParseResult(transactions, positions, section_counts)` instead of 3-tuple
- [ ] Update `dbs_transaction_history_csv_v1.py`: return `ParseResult(transactions, positions, section_counts)` instead of 3-tuple
- [ ] Update `sharekhan_holdings_xls_v1.py`: return `ParseResult(transactions, positions, section_counts, parser_meta)` instead of 4-tuple
- [ ] Update `dbs_vickers_holdings_xls_v1.py`: return `ParseResult(transactions, positions, section_counts, parser_meta)` instead of 4-tuple

#### 1C: Parser Registry in Runner (`api/app/ingestion/runner.py`)
- [ ] Define `PARSER_REGISTRY` dict mapping `parser_key` → parser callable
- [ ] Define `CSV_PARSERS` set listing parser keys that require delimiter arg
- [ ] Replace if/elif dispatch with registry lookup and call
- [ ] Update runner to read `result.transactions`, `result.positions`, etc. from `ParseResult`

#### 1D: Formalized Signature Detection Chain (`api/app/ingestion/signature.py`)
- [ ] Refactor `_detect_ibkr()` to return `Optional[Tuple[str, dict]]` (signature + debug) instead of `bool`
- [ ] Create `_CSV_DETECTORS` ordered list
- [ ] Refactor `compute_format_signature()` to iterate `_CSV_DETECTORS`, fall back to flat CSV
- [ ] Extract flat CSV signature into `_flat_csv_signature()` helper

#### 1E: Regression Verification (Architecture)
- [ ] Run ALL existing ingestion tests: `test_ingest.py`, `test_ingest_router.py`, `test_ingestion_utils.py`, `test_ingest_sharekhan.py`, `test_ingest_dbs_vickers.py`
- [ ] Verify 0 test failures — all existing parsers work identically
- [ ] `make api-rebuild` succeeds with no import errors
- [ ] `curl http://localhost:8000/health` returns OK

### Phase 2: Citi CC Parser Implementation

#### 2A: Parser (`api/app/ingestion/parsers/citi_credit_card_csv_v1.py`)
- [ ] Create `parse_citi_credit_card_csv(file_path: str, delimiter: str) -> ParseResult`
- [ ] Parse DD/MM/YYYY dates into UTC datetime objects
- [ ] Map transaction types: EXPENSE, TRANSFER, FEE, INTEREST, INCOME based on description patterns
- [ ] Set `currency` to `SGD`, extract foreign currency details into `notes`
- [ ] Strip card number quotes, include in `notes`
- [ ] Set `merchant_counterparty` from description column (trimmed)
- [ ] Set `category` per mapping table (CreditCard::Purchase, CreditCard::Payment, etc.)
- [ ] Return `ParseResult(transactions=..., positions=[], section_counts={"transactions": N})`
- [ ] Handle BOM via `utf-8-sig` encoding

#### 2B: Signature Detection (`api/app/ingestion/signature.py`)
- [ ] Add `_detect_citi_cc(lines, delimiter)` heuristic function
- [ ] Check: 5 columns, col1=DD/MM/YYYY, col3=numeric, col4=empty, col5=card-number pattern
- [ ] Generate stable signature: `file_kind=citi_credit_card_csv`, `delimiter`, `platform_hint`, `column_count=5`
- [ ] Add `_detect_citi_cc` to `_CSV_DETECTORS` list (after IBKR, before flat CSV fallback)

#### 2C: Runner Registration (`api/app/ingestion/runner.py`)
- [ ] Add `from app.ingestion.parsers.citi_credit_card_csv_v1 import parse_citi_credit_card_csv`
- [ ] Add `"citi_credit_card_csv_v1": parse_citi_credit_card_csv` to `PARSER_REGISTRY`
- [ ] Add `"citi_credit_card_csv_v1"` to `CSV_PARSERS` set

#### 2D: Database Migration (`migrations/021_register_citi_cc_parser.sql`)
- [ ] Compute the exact SHA-256 signature that `_detect_citi_cc` will produce
- [ ] Insert into `parser_registry` with `parser_key='citi_credit_card_csv_v1'`, `version=1`

### Phase 3: Frontend Changes

#### 3A: Data-Driven Approval Buttons (`web/src/routes/Ingest.tsx`)
- [ ] Define `PLATFORM_PARSERS` config map: `Record<string, { label: string; parserKey: string }>`
- [ ] Include all 5 platforms: IBKR, DBS, SHAREKHAN, DBS_VICKERS, CITI
- [ ] Replace hardcoded per-platform if-blocks with single map-lookup rendering
- [ ] Verify button text: "Approve as Citi CC" for CITI platform

### Phase 4: Testing

#### 4A: New Parser Tests (`api/tests/test_ingest_citi_cc.py`)
- [ ] Parse fixture file and verify transaction count = 51
- [ ] Verify date parsing correctness (DD/MM/YYYY → datetime)
- [ ] Verify type mapping counts: 42 EXPENSE, 2 TRANSFER, 2 FEE, 4 INTEREST, 1 INCOME
- [ ] Verify amount signs (negative for expenses, positive for payments/refunds)
- [ ] Verify currency = SGD for all transactions
- [ ] Verify foreign currency info appears in `notes` for applicable rows
- [ ] Verify `PAYMENT - THANK YOU` → TRANSFER
- [ ] Verify `LATE CHARGE FEE` → FEE, `LATE CHARGE FEE REVERSAL` → FEE
- [ ] Verify `BILLED FINANCE CHARGES` → INTEREST, `RTL INT CRED ADJ` → INTEREST
- [ ] Verify `ParseResult` return type

#### 4B: Architecture Regression Tests
- [ ] Run `test_ingest.py` — verify all existing tests pass
- [ ] Run `test_ingest_router.py` — verify API endpoint tests pass
- [ ] Run `test_ingestion_utils.py` — verify signature/utility tests pass
- [ ] Run `test_ingest_sharekhan.py` — verify Sharekhan parser tests pass
- [ ] Run `test_ingest_dbs_vickers.py` — verify DBS Vickers parser tests pass

#### 4C: Frontend Regression Tests
- [ ] Run existing frontend test suite — verify all tests pass
- [ ] Verify approval buttons render for all platforms (IBKR, DBS, SHAREKHAN, DBS_VICKERS, CITI)

### Phase 5: Verification

- [ ] `make api-rebuild` — containers start, no import errors
- [ ] `make web-rebuild` — TypeScript compiles
- [ ] `curl http://localhost:8000/health` returns `{"status":"ok"}`
- [ ] Upload `citi_credit_card_sample.csv` via Ingest page → status IMPORTED
- [ ] Re-upload same file → 0 inserted, all duplicates
- [ ] Verify existing parser flows still work (IBKR/DBS signatures still detected)

---

## Implementation Reasoning Addendum (Codex Mutable)
_Codex appends execution reasoning entries here._

## Verification Evidence (Codex Mutable)
_Codex appends lint/typecheck/test evidence here._

## Review Findings (Sonnet Primary, Opus Escalation)
_Sonnet performs primary review. If Sonnet flags MEDIUM or HIGH risk, or if architectural refactor correctness is uncertain, escalate to Opus for secondary review._

## Retry Log (Max 3)
_Failed command/rework retries are appended here._

## Automation Log (Mutable)
_Automation appends structured logs here._

## Workflow Commands

```bash
make task-plan TASK=tasks/issue-105-citibank-credit-card-parser.md
make task-build TASK=tasks/issue-105-citibank-credit-card-parser.md
make task-review TASK=tasks/issue-105-citibank-credit-card-parser.md
make task-rework TASK=tasks/issue-105-citibank-credit-card-parser.md
make task-ship TASK=tasks/issue-105-citibank-credit-card-parser.md
```
