# Issue 117: dbs-parser-bigfix

## Objective
# Issue 117: Fix Cash-Flow Misclassification (DBS Salary vs Internal Transfer)

- Cash-flow totals are currently unreliable because DBS salary-like rows are being parsed as `TRANSFER`.

Problem statement:
- Current DBS parser likely marks many GIRO/IBG rows as `TRANSFER` using broad keyword logic.
- Real payroll credits (for example `PAY PARTIOR PTE. LTD. SALARY_*`) are being excluded from income totals.
- Category overrides cannot fully solve this because cash-flow grouping is based on transaction `type`.

Scope:
1. Fix parser logic at source
- Update DBS classifier so payroll/employer credits are `INCOME`.
- Keep true own-account movement as `TRANSFER`.
- Add strong regression tests for both paths.

2. Correct historical data deterministically
- Reprocess historical rows with a one-time deterministic migration/backfill.
- Idempotent: running it multiple times must not create drift.

3. Internal transfer correctness across ingested accounts
- If money moves from one ingested account to another ingested account, classify as `TRANSFER` (not income/expense).
- Examples to handle: DBS -> IBKR, Coinbase, UOB, OCBC (and reverse credit legs where applicable).

Non-negotiable constraints:
- `transactions.type` must be correct after this fix (no permanent “workaround-only” reporting layer).
- Rule logic must generalize to future statements (no fixture-specific hardcoding).
- Good: detect payroll-like inflow using broader signals such as:
credit transaction,salary/payroll keywords,employer-like counterparty patterns,and exclude known self-transfer patterns.
- No personal data committed.

Required output from implementation:
- Exact local verification commands + curl checks showing before/after for Feb/March cash-flow totals.
- Evidence that salary rows are counted as income and internal transfers are excluded from cash-flow.

Requirement 2
- regression issue: UOB data that was ingested is missing from UI which is messing up the net worth and cash
- this has happened before and has happened again. Find out why and fix it.
- both the issues are within scope 

Apart from these 2,  no unrelated changes should be in the scope

## Architecture Decisions
- Decision 1:
- Decision 2:

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement backend changes (if required)
- [ ] Implement frontend changes (if required)
- [ ] Add/update tests
- [ ] Run verification commands

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
