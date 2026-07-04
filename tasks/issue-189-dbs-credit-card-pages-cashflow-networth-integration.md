# Issue 189: DBS credit card page, cash-flow, and net-worth integration

## Objective
- Make imported DBS credit-card data visible and correct across CapitalOS product surfaces after Issue 188 lands.
- Ensure DBS credit-card transactions show on the Credit Cards page and flow correctly into cash-flow analytics.
- Ensure DBS credit-card liabilities affect net worth without double-counting card payments or bank-account transfers.

## Current State
- Credit-card pages already read `accounts.account_type = 'CREDIT_CARD'` and `credit_card_accounts`.
- Cash-flow pages already include transaction types `EXPENSE`, `FEE`, `TAX`, `INTEREST`, `TRANSFER` and exclude explicit/internal transfers from operating flow.
- Net-worth pages primarily depend on canonical balances/positions and dashboard aggregation logic.
- DBS credit-card CSV ingestion is not yet implemented; this issue depends on Issue 188.

## Architecture Decisions
- Use one source of truth for card details: imported DBS credit-card transactions plus the `credit_card_accounts` metadata for card name, issuer, credit limit, statement day, and due day.
- Card purchases, fees, taxes, and interest are spending/outflows.
- Card payments are transfers and must not inflate expenses or income.
- Net-worth impact should be a liability value, not a negative cash position and not a duplicate expense.
- If the DBS CSV exposes credit limit and available limit, derive current outstanding balance carefully and document the semantics:
  - outstanding liability = credit limit - available limit only when both fields are present and clearly current as of the export date,
  - otherwise use transaction-derived monthly/current due behavior already used by the Credit Cards page.
- Do not use historical snapshots to display current card detail; snapshots are only for month-over-month trajectory.

## Implementation Plan
- Verify the DBS credit-card account/card record from Issue 188 appears in `/spending/credit-cards`.
- Update credit-card detail logic if needed so DBS rows display:
  - card name,
  - issuer,
  - credit limit,
  - current due/outstanding amount,
  - transactions,
  - top purchases,
  - recurring payments only when stable recurring logic applies.
- Update cash-flow detail/summary behavior if DBS card rows reveal classification gaps:
  - purchases/fees/taxes/interest count as expenses,
  - payments and internal transfers are excluded from operating cash flow,
  - refunds/credits do not show as recurring spending.
- Update net-worth/dashboard behavior if DBS card liabilities are currently omitted:
  - credit-card outstanding balance appears as a liability component,
  - liabilities reduce net worth,
  - the same payment is not counted once as reduced cash and again as a separate expense.
- Update frontend types/rendering if backend responses add optional DBS/card-liability fields.
- Add targeted tests that compare UI/API totals with database-derived canonical values, not just "value exists" checks.
- Keep DBS bank account and DBS Vickers behavior separate from DBS credit-card behavior.

## How To Test
- First complete Issue 188 and import `data/fixtures/transaction_history_04072026_105429.csv`.
- Run `make api-rebuild` and `make web-rebuild`.
- Run focused backend tests:
  - `docker compose run --rm api pytest tests/test_spending.py tests/test_dashboard.py -q`
  - add focused DBS credit-card integration tests if new test files are created.
- Run focused frontend tests for affected pages:
  - `npm --prefix web test -- CreditCards`
  - `npm --prefix web test -- CashFlow`
  - `npm --prefix web test -- Wealth`
- Use curl to verify API behavior:
  - `curl "http://localhost:8000/spending/credit-cards?month=2026-07&base_currency=SGD"`
  - `curl "http://localhost:8000/spending/credit-card-transactions?month=2026-07&base_currency=SGD"`
  - `curl "http://localhost:8000/spending/cash-flow-detail?month=2026-07&base_currency=SGD"`
  - `curl "http://localhost:8000/dashboard/summary?month=2026-07&base_currency=SGD"`
- Manually open the UI and confirm:
  - Credit Cards shows the DBS card,
  - card transactions include the imported DBS rows,
  - cash-flow expenses include card purchases/fees/taxes/interest,
  - card payments do not inflate expenses,
  - net worth includes the card liability exactly once.
- Run `make api-smoke`, `make typecheck`, and the relevant frontend test command.

## Acceptance Criteria
- [ ] DBS credit-card account appears on Credit Cards after Issue 188 import.
- [ ] DBS card transactions appear on the Credit Cards detail page with correct signs and categories.
- [ ] Cash-flow pages include DBS card expenses and exclude DBS card payments as operating expenses.
- [ ] Net worth includes DBS credit-card liability exactly once when a current/outstanding value is available.
- [ ] DBS bank, DBS Vickers, and DBS credit-card surfaces remain distinguishable.
- [ ] Backend/API tests assert totals equal database-derived expected values.
- [ ] Frontend tests cover visible DBS card data rather than only shallow rendering.

## Out Of Scope
- Implementing the DBS CSV parser itself; that belongs to Issue 188.
- Reworking the full liabilities model beyond the DBS credit-card path.
- Adding statement PDF parsing or automatic DBS credit-card fetching.
- Changing snapshot semantics for historical net-worth trends.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Verify Issue 188 DBS card data path.
- [ ] Update backend card/cash-flow/net-worth reads as needed.
- [ ] Update frontend card/cash-flow/net-worth rendering as needed.
- [ ] Add backend total/parity tests.
- [ ] Add frontend page tests.
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
- `web-rebuild`: `pending`
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
- Next expected action: run after Issue 188 is shipped and the fixture can be imported.
- Open questions:
  - Confirm whether card outstanding should come from credit-limit/available-limit metadata when present, or from transaction-derived current due only.

## Automation Log (Mutable)
- 2026-07-04T00:00:00+08:00 - Created DBS credit-card product integration planning issue dependent on Issue 188.

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `deterministic_gates`
**Workflow Status**: `waiting_for_human`

## Workflow Snapshot
- latest_outcome: Implemented DBS credit-card current outstanding integration across ingestion metadata, Credit Cards, cash-flow, and net-worth/dashboard paths with targeted backend and frontend coverage.
- next_action: All deterministic gates passed. Review the changes in the working tree, then run `make task-ship TASK=<task_file> THREAD_ID=<thread_id>` to commit, push, and open a PR.
- pipeline_version: `v3`
- provider_model: `codex/gpt-5.5`
- retry_gate_pending: `no`
- retry_detail: `test-backend` stopped after attempt 1/3: Code failure with no auto-fix available: tests/test_ingest_uob_cc.py:183: AssertionError

## Active Requirements
- Acceptance criterion: DBS credit-card account appears on Credit Cards after Issue 188 import.
- Acceptance criterion: DBS card transactions appear on the Credit Cards detail page with correct signs and categories.
- Acceptance criterion: Cash-flow pages include DBS card expenses and exclude DBS card payments as operating expenses.
- Acceptance criterion: Net worth includes DBS credit-card liability exactly once when a current/outstanding value is available.
- Acceptance criterion: DBS bank, DBS Vickers, and DBS credit-card surfaces remain distinguishable.
- Acceptance criterion: Backend/API tests assert totals equal database-derived expected values.
- Acceptance criterion: Frontend tests cover visible DBS card data rather than only shallow rendering.

## Prepare
Checked out `feature/issue-189-dbs-credit-card-pages-cashflow-networth-integration` from `main` and verified task file exists.

## Plan Summary
Persist optional DBS available-limit metadata, prefer credit_limit - available_limit for current card outstanding when imported as-of metadata exists, fall back to transaction-derived outstanding otherwise, add dashboard liability computation that avoids counting card balances as cash, and cover the affected API/UI surfaces with parity tests.

### Architecture Decisions
- Added optional available_limit and available_limit_as_of columns to credit_card_accounts instead of introducing a separate liabilities model.
- Persist DBS available-limit metadata only for dbs_credit_card_csv_v1 imports when credit_limit, available_limit, and transactions_as_at are all present.
- Credit-card current_due uses available-limit outstanding when current metadata exists; otherwise it uses transaction-derived outstanding including payments and credits.
- Dashboard net worth treats credit-card outstanding as liabilities and skips credit-card account balance rows from cash to avoid double-counting.
- Cash-flow operating logic remains separate from card liability logic: purchases, fees, taxes, and interest are expenses; payments remain transfers.

### Acceptance Criteria
- DBS credit-card account appears on Credit Cards after Issue 188 import.
- DBS card transactions appear on the Credit Cards detail page with correct signs and categories.
- Cash-flow pages include DBS card expenses and exclude DBS card payments as operating expenses.
- Net worth includes DBS credit-card liability exactly once when a current/outstanding value is available.
- DBS bank, DBS Vickers, and DBS credit-card surfaces remain distinguishable.
- Backend/API tests assert totals equal database-derived expected values.
- Frontend tests cover visible DBS card data rather than only shallow rendering.

### Planned Paths
- `api/app/ingestion`
- `api/app/models`
- `api/app/routers`
- `api/app/schemas`
- `api/tests`
- `migrations`
- `web/src`
- `tasks`

## Build Summary
Implemented DBS credit-card current outstanding integration across ingestion metadata, Credit Cards, cash-flow, and net-worth/dashboard paths with targeted backend and frontend coverage.

### Changed Files
- `tasks/issue-189-dbs-credit-card-pages-cashflow-networth-integration.md`

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
Implemented DBS credit-card current outstanding integration across ingestion metadata, Credit Cards, cash-flow, and net-worth/dashboard paths with targeted backend and frontend coverage.

- semantic_intent_achieved: `True`
- provider_model: `codex/gpt-5.5`

### Semantic Checks
- `pass` DBS credit-card account appears on Credit Cards after Issue 188 import.: api/tests/test_spending.py asserts /spending/credit-cards returns only DBS Credit Card with DBS/POSB MasterCard Platinum metadata.
- `pass` DBS card transactions appear on the Credit Cards detail page with correct signs and categories.: api/tests/test_spending.py asserts detail transactions include EXPENSE, FEE, TAX, INTEREST, TRANSFER with payment amount positive and top purchases limited to purchase rows.
- `pass` Cash-flow pages include DBS card expenses and exclude DBS card payments as operating expenses.: api/tests/test_spending.py derives expected expenses from SQL charge rows and asserts cash-flow expense transactions exclude TRANSFER rows.
- `pass` Net worth includes DBS credit-card liability exactly once when a current/outstanding value is available.: api/tests/test_dashboard.py asserts net-worth liabilities equal credit_limit - available_limit while a credit-card balance snapshot is skipped from cash.
- `pass` DBS bank, DBS Vickers, and DBS credit-card surfaces remain distinguishable.: api/tests/test_spending.py seeds DBS bank, DBS Vickers broker, and DBS credit-card accounts and asserts card endpoints only include the credit-card account.
- `pass` Backend/API tests assert totals equal database-derived expected values.: api/tests/test_spending.py and api/tests/test_dashboard.py compute expected expense/outstanding/liability values via SQL and compare API/helper totals to those values.
- `pass` Frontend tests cover visible DBS card data rather than only shallow rendering.: CreditCards, CashFlowDetail, and WealthOverview tests assert visible DBS card, DBS card expense, and liability text.

### Risk Flags
- Local Postgres collation-version warning observed during db-migrate; command passed.
- Backend ruff and mypy were skipped by existing Makefile targets because the tools are not installed in the API image.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Retry Log
- test-backend: attempt 1/3, class=code, exit=2, log=.task-flow/failures/20260704T091058Z_test-backend_attempt1.log, notes=Code failure with no auto-fix available: tests/test_ingest_uob_cc.py:183: AssertionError
<!-- MACHINE_RENDERED_END -->
