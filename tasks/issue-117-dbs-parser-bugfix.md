# Issue 117: Fix Cash-Flow Misclassification (DBS Salary vs Internal Transfer) + UOB Data Regression

## Objective

Two scoped fixes:

**Requirement 1 — DBS parser salary misclassification:**
DBS salary/payroll credits (e.g. `PAY PARTIOR PTE. LTD. SALARY_*`) are classified as `TRANSFER` instead of `INCOME` because `_is_transfer()` in `dbs_transaction_history_csv_v1.py` uses broad keywords (`GIRO`, `IBG`) that also match payroll GIRO credits. This excludes real income from cash-flow totals (the spending router SQL filters `WHERE t.type IN ('INCOME', 'EXPENSE', 'FEE', 'TAX', 'INTEREST')` — TRANSFER is excluded). The dashboard `_cashflow()` function also only sums INCOME-typed rows for income totals.

**Requirement 2 — UOB data regression:**
UOB ingested data periodically disappears from the UI. This has occurred before. Root-cause must be identified and fixed so it does not recur.

No other changes are in scope.

## Architecture Decisions

### Decision 1: DBS parser — salary-aware classification before transfer keyword matching

**Current flow** (`dbs_transaction_history_csv_v1.py:130-145`):
1. Credit amount → `tx_type = "INCOME"`
2. `_is_transfer(stmt_code, description, supplementary)` → if any keyword matches, override to `"TRANSFER"`

**Problem:** Keywords `GIRO`, `IBG` match legitimate salary credits. The keyword list also includes `BILL`, `TAX`, `IRAS` which are real expenses, not transfers — these convert expenses to transfers incorrectly.

**Fix — add `_is_salary()` check and refine `_is_transfer()`:**

1. Add a `_is_salary(description, supplementary)` function that detects payroll/employer signals:
   - Keywords: `SALARY`, `SAL `, `PAYROLL`, `PAY ` followed by employer-like patterns
   - Pattern: credit + GIRO/IBG + salary keyword in description or supplementary → INCOME
2. Modify classification flow: if `_is_salary()` returns True, preserve `INCOME` type — do NOT override to `TRANSFER`.
3. Separate true-transfer keywords from payment-mechanism keywords:
   - True transfers (own-account movement): `TRF`, `TRANSFER`, `PAYNOW`, `TOPUP`, `TOP UP`
   - Government/regulatory (keep as non-transfer expense/income): `CPF`, `SRS`, `TAX`, `IRAS`
   - Payment mechanism (contextual): `GIRO`, `IBG`, `BILL` — only mark as TRANSFER if no salary signal and statement code is `TRF`
4. Self-transfer detection: add known counterparty patterns for own-account transfers (IBKR, Coinbase, UOB, OCBC, DBS Vickers) so that credits from these are classified as TRANSFER.

**Rationale:** UOB parser already does this correctly — it checks `"SALARY" in text` before transfer keywords (`uob_account_xls_v1.py:220-227`). DBS parser should follow the same pattern. OCBC parser has similar broad keywords and the same `_INCOME_KEYWORDS` guard — but OCBC is not in scope for this issue.

### Decision 2: Historical backfill via idempotent SQL migration

**Problem:** Existing transactions in the DB have incorrect `type = 'TRANSFER'` for salary rows. Re-ingesting won't fix them because the duplicate detection (`runner.py:260-283`) matches on `type` — a row stored as TRANSFER won't match the new parser output of INCOME, creating duplicates.

**Fix:**
- Write a new numbered migration (e.g. `028_fix_dbs_salary_type.sql`) that:
  1. UPDATEs `transactions.type` from `'TRANSFER'` to `'INCOME'` where:
     - `source = 'DBS'` (or account is DBS-linked)
     - `amount > 0` (credit)
     - `merchant_counterparty` or `notes` contains salary/payroll signals
     - Does NOT match known self-transfer counterparties
  2. Is idempotent: running multiple times produces the same result (UPDATE with WHERE guards).
- Also re-backfill `category` from `'Bank::TRF'` / `'Bank::GR'` to the correct value for re-classified rows.
- Run `apply_rules()` on affected transaction IDs to re-evaluate category overrides.

**Fingerprint impact:** The fingerprint stored in `notes` (`fp:...`) includes `type` in its hash. After the migration, the stored fingerprint will be stale. Future re-imports with the fixed parser will compute a different fingerprint (INCOME vs TRANSFER), and the duplicate-detection SQL (`runner.py:260-283`) also matches on `type`. Therefore:
- The migration must also update the `notes` field to reflect the new fingerprint, OR
- The duplicate detection should match on a type-agnostic set of fields for DBS transactions, OR
- Accept that re-importing the same file after the fix will skip correctly because the duplicate check matches on all fields including the NEW type.

**Chosen approach:** The migration UPDATEs the `type` field. After the parser fix, re-importing the same CSV will produce `type='INCOME'` for salary rows, which now matches the DB (post-migration), so duplicate detection works correctly. No fingerprint change needed.

### Decision 3: UOB data regression — root-cause investigation and fix

**Hypotheses to investigate (ordered by likelihood):**

1. **Position snapshot staleness:** If UOB cash positions have a different `as_of` date than expected, the dashboard `_networth_components()` query (`WHERE as_of <= :anchor_ts`) may not find them. The `_cash_deposits()` and `_cash_balances()` queries use the same pattern. If the anchor timestamp is before the UOB position `as_of`, UOB cash disappears.

2. **Account `platform_id` NULL after migration 024:** Migration `024_remove_card_issuer_platforms.sql` updated `UOB_CARDS` → `UOB` but may have left some accounts with `platform_id = NULL`. Dashboard queries use `LEFT JOIN platforms pl ON pl.id = acc.platform_id` so NULL platform_id still works, but the display source would fall back to `acc.platform` which may be stale.

3. **Import job failure swallowed:** If the UOB parser fails (exception in `runner.py:398-401`), the job status is `FAILED` but the error is stored only in `import_jobs.error_message` — not surfaced in UI. The user may think data was imported when it wasn't.

4. **Duplicate detection creating duplicates instead of skipping:** If UOB transactions are re-imported and any field differs slightly (e.g., description whitespace from parser changes), duplicates are inserted. The position query uses `MAX(as_of)` per account, so only the latest snapshot is used — but if transactions duplicate, cash-flow totals double-count.

**Fix approach:** Investigate each hypothesis via diagnostic SQL in verification. Fix the confirmed root cause. Add a regression test.

### Decision 4: No changes to spending/dashboard query layer

The spending router already correctly excludes TRANSFER-typed transactions from cash-flow. The dashboard `_cashflow()` function also only counts INCOME and EXPENSE types. The fix is purely at the parser layer (correct classification at source) and a one-time migration (correct historical data). No reporting-layer workarounds needed.

## Risks

1. **Backfill scope uncertainty:** Without seeing the actual DBS CSV data, the salary detection patterns must be general enough to catch real payroll but not false-positive on non-salary GIRO credits (e.g., government refunds, insurance payouts). Mitigation: use both credit direction AND salary keyword signals.

2. **Breaking existing tests:** `test_dbs_parser_marks_transfers` (line 20-33 of `test_parsers.py`) tests that a `TRF` statement code row is classified as TRANSFER. The existing test fixture uses `TRF FT251009IB00249524` in description with statement code `ADV` — this should still be TRANSFER. The test at line 9-17 has `GR` statement code + `Salary` description + `IBG` supplementary → currently classified as INCOME (the test expects INCOME). This test already passes correctly because `GR` is not in the transfer statement codes and `Salary` + `IBG` triggers `_is_transfer()` BUT the credit amount sets initial type to INCOME which then gets overridden to TRANSFER... Wait, let me re-verify:
   - Line 10: `GR,Salary,IBG,Payments` → credit of 500
   - `_is_transfer("GR", "Salary", "Payments")` → checks `"IBG"` NOT in `"Salary Payments"` — actually the supplementary is `"Payments"`, not `"IBG"`. The header mapping: `Supplementary Code` = `IBG`, `Supplementary Code Description` = `Payments`. So `supp_desc = "Payments"`, and `_is_transfer("GR", "Salary", "Payments")` → text = `"SALARY PAYMENTS"` → `"GIRO"` not in it, `"IBG"` not in it → returns False. So test expects INCOME and it passes.
   - This means the existing test does NOT cover the actual bug scenario (where IBG appears in description/supplementary). New test cases needed.

3. **UOB regression root cause may be multi-factorial.** The investigation may reveal issues beyond what's initially hypothesized. Mitigation: diagnostic queries first, then targeted fix.

4. **Duplicate detection after type change:** If a user re-imports a DBS CSV after the parser fix but before running the backfill migration, the same transaction will be inserted twice (once as TRANSFER from old import, once as INCOME from new parser). Mitigation: migration must run before or atomically with the parser fix deployment. Document this in deployment notes.

## Open Questions

1. **Q:** What specific DBS CSV rows triggered this bug? Are there real fixture files available with salary GIRO credits? → Needed to write precise regression tests. If not available, use synthetic test data matching the described pattern (`PAY PARTIOR PTE. LTD. SALARY_*`).

2. **Q:** For UOB regression — is the issue reproducible now, or was it a one-time occurrence? What month/data range is affected? → Needed to write diagnostic queries.

3. **Q:** Should `BILL`, `TAX`, `IRAS`, `CPF`, `SRS` remain as TRANSFER in the DBS parser, or should they be reclassified? Currently these are real expenses/contributions being excluded from cash-flow. → The task description says "Keep true own-account movement as TRANSFER" — these government payments are arguably not transfers. Recommend reclassifying: `TAX`/`IRAS` → EXPENSE, `CPF`/`SRS` → EXPENSE (mandatory contributions), `BILL` → EXPENSE. But this expands scope. Defer to human approval.

4. **Q:** Should the OCBC parser receive the same salary-awareness fix? It has the same broad keyword pattern. → Not in scope per task description, but worth noting for future work.

## Acceptance Criteria

- [ ] AC1: DBS salary/payroll credits (credit amount + salary keyword in description/supplementary) are classified as `INCOME`, not `TRANSFER`
- [ ] AC2: DBS own-account transfers (statement code `TRF`, or description containing transfer to known counterparties like IBKR/UOB/OCBC) remain classified as `TRANSFER`
- [ ] AC3: Existing unit tests pass (`test_dbs_parser_extracts_cash_and_transactions`, `test_dbs_parser_marks_transfers`, `test_dbs_parser_prefers_transaction_date`)
- [ ] AC4: New regression tests cover: (a) salary via GIRO/IBG → INCOME, (b) non-salary GIRO transfer → TRANSFER, (c) self-transfer to IBKR → TRANSFER
- [ ] AC5: Backfill migration is idempotent — running it twice produces identical DB state
- [ ] AC6: After backfill, `/spending/cash-flow-detail?month=YYYY-MM` shows salary rows under income, not excluded
- [ ] AC7: After backfill, `/dashboard/summary?month=YYYY-MM` cash_flow.income includes reclassified salary amounts
- [ ] AC8: UOB regression root cause identified, fixed, and regression test added
- [ ] AC9: UOB data appears correctly in dashboard net_worth and cash_flow after fix
- [ ] AC10: `make api-rebuild` succeeds, `make api-smoke` passes
- [ ] AC11: No unrelated files modified

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist

### Phase 1: DBS Parser Fix
- [ ] 1.1 Add `_is_salary(description: str, supplementary: str) -> bool` function to `dbs_transaction_history_csv_v1.py`
- [ ] 1.2 Add `_SALARY_KEYWORDS` list: `SALARY`, `SAL `, `PAYROLL`
- [ ] 1.3 Add `_SELF_TRANSFER_COUNTERPARTIES` list: `IBKR`, `INTERACTIVE BROKERS`, `COINBASE`, `UOB`, `OCBC`, `DBS VICKERS`, `POSB`
- [ ] 1.4 Refactor `_is_transfer()` to accept amount direction and check salary exemption: if credit + salary signal → return False (not a transfer)
- [ ] 1.5 Add `_is_self_transfer(description: str, supplementary: str) -> bool` for cross-account transfer detection
- [ ] 1.6 Update classification flow in `parse_dbs_transaction_history_csv()` lines 130-145: check `_is_salary()` before `_is_transfer()`
- [ ] 1.7 Verify existing tests still pass: `test_dbs_parser_extracts_cash_and_transactions`, `test_dbs_parser_marks_transfers`

### Phase 2: New Regression Tests
- [ ] 2.1 Add test: DBS salary via GIRO → type=INCOME (e.g. description=`PAY PARTIOR PTE. LTD.`, supplementary contains `SALARY`, stmt_code=`GR`, credit amount)
- [ ] 2.2 Add test: DBS salary via IBG → type=INCOME
- [ ] 2.3 Add test: DBS non-salary GIRO debit → type=TRANSFER (e.g. GIRO bill payment)
- [ ] 2.4 Add test: DBS self-transfer to IBKR → type=TRANSFER
- [ ] 2.5 Add test: DBS PayNow transfer → type=TRANSFER (ensure PayNow is still correctly classified)
- [ ] 2.6 Add test: DBS statement code TRF → type=TRANSFER (existing test, verify it still passes)

### Phase 3: Historical Backfill Migration
- [ ] 3.1 Create `028_fix_dbs_salary_type.sql` migration
- [ ] 3.2 SQL: UPDATE transactions SET type='INCOME' WHERE source='DBS' AND amount > 0 AND type='TRANSFER' AND (salary keyword conditions)
- [ ] 3.3 Ensure idempotency with WHERE guards
- [ ] 3.4 Test migration locally: verify before/after row counts

### Phase 4: UOB Data Regression
- [ ] 4.1 Investigate: Run diagnostic SQL to check UOB account linkage, positions, transactions
- [ ] 4.2 Investigate: Check `import_jobs` for UOB failures or NEEDS_MAPPING status
- [ ] 4.3 Investigate: Check position `as_of` dates vs dashboard anchor timestamps
- [ ] 4.4 Investigate: Check if `platform_id` is NULL for UOB accounts after migration 024
- [ ] 4.5 Implement fix based on root cause
- [ ] 4.6 Add regression test for UOB data persistence

### Phase 5: Verification
- [ ] 5.1 `make api-rebuild` — containers start without errors
- [ ] 5.2 `make api-smoke` — all smoke tests pass
- [ ] 5.3 `curl http://localhost:8000/health` — returns OK
- [ ] 5.4 `curl http://localhost:8000/spending/cash-flow-detail?month=2026-02&base_currency=SGD` — salary rows in income section
- [ ] 5.5 `curl http://localhost:8000/dashboard/summary?month=2026-02` — cash_flow.income reflects salary
- [ ] 5.6 Verify UOB data present in dashboard net_worth and cash_flow
- [ ] 5.7 Run full test suite: `pytest api/tests/`

## Implementation Reasoning Addendum (Codex Mutable)
_Codex appends execution reasoning entries here._

## Verification Evidence (Codex Mutable)
_Codex appends lint/typecheck/test evidence here._

## Review Findings (Sonnet Primary, Opus Escalation)
_Review output is appended here._

## Human Rework Input (Mutable)
_Before running `task-rework`, add/update:_
- `### Review Cycle R<n> - Human Input` with a `text` block containing:
  `HUMAN_QUESTIONS: ...`
  `UNRESOLVED_COMMENTS: ...`
  `RESPONSE_REQUIREMENTS: ...`

## Retry Log (Max 3)
_Failed command/rework retries are appended here._

## Automation Log (Mutable)
_Automation appends structured logs here._

## Workflow Commands

```bash
make task-plan TASK=tasks/issue-117-dbs-parser-bugfix.md
make task-build TASK=tasks/issue-117-dbs-parser-bugfix.md
make task-review TASK=tasks/issue-117-dbs-parser-bugfix.md
make task-rework TASK=tasks/issue-117-dbs-parser-bugfix.md
make task-ship TASK=tasks/issue-117-dbs-parser-bugfix.md
```
