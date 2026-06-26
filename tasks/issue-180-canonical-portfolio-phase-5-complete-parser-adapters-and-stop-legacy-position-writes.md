# Issue 180: Canonical portfolio phase 5 - complete parser adapters and stop legacy position writes

## Objective
- Ensure every parser that currently produces `ParseResult.positions` writes to canonical tables.
- Make canonical persistence the blocking authoritative path for all position-producing imports.
- Stop writing new authoritative rows to legacy `positions` once canonical coverage is complete.

## Parent Architecture
- Umbrella architecture: [Issue 175](./issue-175-ibkr-flex-broker-neutral-portfolio-ingestion.md)
- Storage/table dependency: [Issue 179](./issue-179-canonical-portfolio-phase-4-storage-contract-and-cash-balance-model.md)
- Follow-up migration: [Issue 181](./issue-181-canonical-portfolio-phase-6-legacy-position-backfill-and-parity-audit.md)

## Problem
The upload runner currently writes legacy `positions` first, then runs the canonical adapter as a non-blocking secondary step. That was correct during the bridge, but it is the wrong long-term architecture:

- The old table remains authoritative by accident.
- Canonical failures can be hidden behind successful legacy imports.
- New parsers can keep extending the wrong storage path.
- Dashboard code must keep double-count guards instead of reading one canonical model.

## Parser Coverage Target

Inventory every parser that returns non-empty `positions` and route it explicitly:

| Parser/source | Canonical target |
|---|---|
| `sharekhan_holdings_xls_v1` | `portfolio_position_snapshots` |
| `dbs_vickers_holdings_xls_v1` | `portfolio_position_snapshots` |
| `ibkr_activity_csv_v1` | reference-only `portfolio_position_snapshots` or canonical ledgers before Flex cutover; never authoritative after Flex cutover |
| `uob_account_xls_v1` | `account_balance_snapshots` for bank cash |
| `ocbc_account_csv_v1` | `account_balance_snapshots` for bank cash |
| `dbs_transaction_history_csv_v1` | `account_balance_snapshots` where parser emits balances; transactions remain in spending/cash-flow model |
| Any future parser with `positions` output | must fail closed until a canonical adapter is registered |

## Scope

### In Scope
- Add an explicit parser-to-canonical adapter registry.
- Convert all remaining `ParseResult.positions` outputs into canonical position snapshots or account balance snapshots.
- Change ingestion order so canonical writes happen before import success for canonical-covered parsers.
- Make canonical adapter failure blocking for any parser that emits positions.
- Stop inserting/updating legacy `positions` for covered parsers.
- Keep additive upload report fields so users can see canonical counts and warnings.

### Out Of Scope
- Historical backfill from existing legacy `positions`; handled by Issue 181.
- Dashboard read cutover; handled by Issue 182.
- Dropping the legacy table; handled by Issue 183.

## Architecture Decisions
- No parser may write authoritative investment or cash-balance facts only to legacy `positions`.
- Parser adapters are narrow and deterministic: parser output in, canonical facts out.
- Canonical write failure should fail the import for position-producing parsers. Silent fallback to legacy storage is not acceptable after this phase.
- Existing `transactions` remains the spending/cash-flow event model. Do not force consumer spending rows into portfolio tables.
- If a parser lacks enough detail, write the available canonical facts and explicit completeness records rather than inventing missing dimensions.

## Acceptance Criteria
- [ ] All parsers that can emit `positions` have an explicit canonical adapter mapping.
- [ ] Uploads from Sharekhan, DBS Vickers, UOB account, OCBC account, DBS transaction history, and pre-cutover/reference IBKR CSV produce canonical facts.
- [ ] The upload runner no longer inserts or updates legacy `positions` for canonical-covered parser outputs.
- [ ] Canonical adapter errors are blocking for position-producing parsers and visible in the upload report.
- [ ] Upload reports remain OpenAPI-compatible; removed semantics are represented by additive fields, not field deletion.
- [ ] Tests fail if a new parser emits positions without an adapter.
- [ ] Existing non-position transaction/card parsers remain unchanged.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Inventory parser outputs and add coverage tests for every `positions` producer.
- [ ] Add explicit adapter registry.
- [ ] Implement canonical balance adapters for bank/account cash parsers.
- [ ] Update runner write order and failure semantics.
- [ ] Update upload report counts to distinguish parsed positions from canonical facts written.
- [ ] Remove or rewrite tests that require legacy `positions` writes.
- [ ] Run deterministic safety gates.

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `pass`
- `typecheck`: `pass`
- `tests`: `pass`
- `api-smoke`: `pass`
- `e2e`: `pass`

## Execution Journal (Codex Mutable)
- Current Stage: `completed`
- Workflow Status: `passed`
- Provider/Model: `openai/gpt-5-codex`
- Last Updated: `2026-06-26T00:00:00Z`

## Automation Log (Mutable)
- 2026-06-25T00:00:00Z - Created to complete canonical parser coverage and stop new legacy `positions` writes.

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `done`
**Workflow Status**: `shipped`

## Workflow Snapshot
- latest_outcome: Pushed branch `feature/issue-180-canonical-portfolio-phase-5-complete-parser-adapters-and-stop-legacy-position-writes`.
- next_action: No action required.
- pipeline_version: `v3`
- provider_model: `copilot/claude-sonnet-4.6`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: All parsers that can emit positions have an explicit canonical adapter mapping.
- Acceptance criterion: Uploads from Sharekhan, DBS Vickers, UOB account, OCBC account, DBS transaction history, and pre-cutover/reference IBKR CSV produce canonical facts.
- Acceptance criterion: The upload runner no longer inserts or updates legacy positions for canonical-covered parser outputs.
- Acceptance criterion: Canonical adapter errors are blocking for position-producing parsers and visible in the upload report.
- Acceptance criterion: Upload reports remain OpenAPI-compatible; removed semantics are represented by additive fields.
- Acceptance criterion: Tests fail if a new parser emits positions without an adapter.
- Acceptance criterion: Existing non-position transaction/card parsers remain unchanged.

## Prepare
Checked out `feature/issue-180-canonical-portfolio-phase-5-complete-parser-adapters-and-stop-legacy-position-writes` from `main` and ensured task file exists.

## Plan Summary
1. Verify existing implementation of PARSER_CANONICAL_REGISTRY, runner logic, and canonical adapters. 2. Run make db-migrate to create account_balance_snapshots table in PostgreSQL. 3. Run full verification suite (test-backend, lint, typecheck, contract-backend, contract-frontend, test-frontend, api-smoke, orch-test, e2e).

### Architecture Decisions
- PARSER_CANONICAL_REGISTRY maps every parser_key to 'portfolio_positions', 'account_balance', or 'none'; unregistered parsers that emit positions fail closed.
- Canonical writes are the blocking authoritative path for position-producing parsers; legacy positions table is skipped for all canonical-covered parsers.
- Bank/cash parsers (UOB, OCBC, DBS) route to account_balance_snapshots via run_upload_balance_canonical_adapter.
- Portfolio parsers (Sharekhan, DBS Vickers, pre-cutover IBKR CSV) route to portfolio_position_snapshots via run_upload_canonical_adapter.
- Upload reports include additive fields (canonical_positions_written, canonical_balances_written) without removing existing fields, preserving OpenAPI compatibility.
- SQLite (tests) uses DELETE+INSERT for idempotency; PostgreSQL uses ON CONFLICT DO UPDATE on partial index.

### Acceptance Criteria
- All parsers that can emit positions have an explicit canonical adapter mapping.
- Uploads from Sharekhan, DBS Vickers, UOB account, OCBC account, DBS transaction history, and pre-cutover/reference IBKR CSV produce canonical facts.
- The upload runner no longer inserts or updates legacy positions for canonical-covered parser outputs.
- Canonical adapter errors are blocking for position-producing parsers and visible in the upload report.
- Upload reports remain OpenAPI-compatible; removed semantics are represented by additive fields.
- Tests fail if a new parser emits positions without an adapter.
- Existing non-position transaction/card parsers remain unchanged.

### Planned Paths
- `api/app/portfolio/upload_canonical.py`
- `api/app/ingestion/runner.py`
- `api/tests/test_canonical_adapter_registry_phase5.py`
- `migrations/056_canonical_account_balance_snapshots.sql`

## Build Summary
Issue 180 Phase 5 implementation is complete. All parser-to-canonical adapter mappings exist in PARSER_CANONICAL_REGISTRY, the upload runner routes position-producing parsers through canonical adapters (blocking), legacy positions writes are suppressed for canonical-covered parsers, the balance adapter (run_upload_balance_canonical_adapter) handles UOB/OCBC/DBS bank parsers, and the missing account_balance_snapshots table was created in the running PostgreSQL instance via make db-migrate. All 939 backend tests, 191 frontend tests, 191 orch tests, and 17 e2e tests pass.

### Changed Files
- `tasks/issue-180-canonical-portfolio-phase-5-complete-parser-adapters-and-stop-legacy-position-writes.md`

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
Issue 180 Phase 5 implementation is complete. All parser-to-canonical adapter mappings exist in PARSER_CANONICAL_REGISTRY, the upload runner routes position-producing parsers through canonical adapters (blocking), legacy positions writes are suppressed for canonical-covered parsers, the balance adapter (run_upload_balance_canonical_adapter) handles UOB/OCBC/DBS bank parsers, and the missing account_balance_snapshots table was created in the running PostgreSQL instance via make db-migrate. All 939 backend tests, 191 frontend tests, 191 orch tests, and 17 e2e tests pass.

- semantic_intent_achieved: `True`
- provider_model: `copilot/claude-sonnet-4.6`

### Semantic Checks
- `pass` All parsers that can emit positions have an explicit canonical adapter mapping.: PARSER_CANONICAL_REGISTRY covers all 8 parsers: sharekhan→portfolio_positions, dbs_vickers→portfolio_positions, ibkr_activity→portfolio_positions, uob_account→account_balance, ocbc_account→account_balance, dbs_transaction→account_balance, uob_cc→none, citi_cc→none. test_all_parsers_have_canonical_registry_entry passes.
- `pass` Uploads from Sharekhan, DBS Vickers, UOB account, OCBC account, DBS transaction history, and pre-cutover/reference IBKR CSV produce canonical facts.: test_ocbc_upload_writes_canonical_balance_not_legacy_positions, test_dbs_transaction_upload_writes_canonical_balance, test_balance_adapter_writes_account_balance_snapshot all pass. Sharekhan/DBS Vickers routed through run_upload_canonical_adapter.
- `pass` The upload runner no longer inserts or updates legacy positions for canonical-covered parser outputs.: runner.py: legacy positions block guarded by `if canonical_target not in ('portfolio_positions', 'account_balance')`. Tests assert positions_inserted==0 for OCBC and DBS.
- `pass` Canonical adapter errors are blocking for position-producing parsers and visible in the upload report.: test_canonical_adapter_failure_fails_import passes. Exception propagates to job.status=FAILED with error in report.
- `pass` Upload reports remain OpenAPI-compatible; removed semantics are represented by additive fields, not field deletion.: _report() retains all original fields and adds canonical_positions_written and canonical_balances_written. contract-backend tests pass.
- `pass` Tests fail if a new parser emits positions without an adapter.: test_unregistered_parser_with_positions_fails_import passes. test_all_parsers_have_canonical_registry_entry enforces registry completeness.
- `pass` Existing non-position transaction/card parsers remain unchanged.: test_citi_credit_card_upload_not_affected passes. uob_cc and citi_cc remain mapped to 'none', no position writes.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Ship Result
Pushed branch `feature/issue-180-canonical-portfolio-phase-5-complete-parser-adapters-and-stop-legacy-position-writes`.
<!-- MACHINE_RENDERED_END -->
