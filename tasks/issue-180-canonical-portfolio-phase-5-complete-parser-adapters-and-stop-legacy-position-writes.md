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
**Current Stage**: `completed`
**Workflow Status**: `passed`

## Workflow Snapshot
- latest_outcome: Implemented canonical portfolio phase 5: added PARSER_CANONICAL_REGISTRY, balance adapter for bank parsers, canonical-first blocking write order in runner, legacy positions suppressed for covered parsers, and comprehensive Phase 5 tests.
- next_action: None - workflow is green.
- pipeline_version: `v3`
- provider_model: `copilot/claude-sonnet-4.6`
- latest_failed_checks: `none`
- retry_gate_pending: `no`
- retry_detail: `none`
- blocked_reason: `none`
- stopped_due_to: `none`

## Active Requirements
- Acceptance criterion: All parsers that can emit positions have an explicit canonical adapter mapping – YES (PARSER_CANONICAL_REGISTRY covers all 8 known parsers)
- Acceptance criterion: Sharekhan, DBS Vickers produce canonical facts in portfolio_position_snapshots – YES
- Acceptance criterion: UOB account, OCBC account, DBS transaction history produce canonical facts in account_balance_snapshots – YES
- Acceptance criterion: Pre-cutover/reference IBKR CSV produces canonical facts – YES
- Acceptance criterion: Upload runner no longer inserts/updates legacy positions for canonical-covered parsers – YES
- Acceptance criterion: Canonical adapter errors are blocking – YES (exception propagates, job marked FAILED)
- Acceptance criterion: Upload reports remain OpenAPI-compatible with additive fields – YES
- Acceptance criterion: Tests fail if new parser emits positions without an adapter – YES (test_unregistered_parser_with_positions_fails_import)
- Acceptance criterion: Existing non-position parsers remain unchanged – YES (credit card parsers verified)

## Prepare
Checked out `feature/issue-180-canonical-portfolio-phase-5-complete-parser-adapters-and-stop-legacy-position-writes` from `main` and ensured task file exists.

## Plan Summary
1) Added PARSER_CANONICAL_REGISTRY dict and parser_canonical_target() function in upload_canonical.py. 2) Implemented run_upload_balance_canonical_adapter() for UOB/OCBC/DBS bank cash positions writing to account_balance_snapshots. 3) Refactored runner.py: canonical writes are now blocking before IMPORTED status; legacy positions skipped for canonical-covered parsers; unregistered parsers with positions fail closed. 4) Updated test_upload_canonical_phase2.py to reflect canonical-first semantics. 5) Created test_canonical_adapter_registry_phase5.py with full coverage.

### Architecture Decisions
- PARSER_CANONICAL_REGISTRY maps every parser_key to its canonical target: 'portfolio_positions', 'account_balance', or 'none'.
- Canonical write is now blocking for position-producing parsers: failure = import failure, no silent legacy fallback.
- Legacy positions table is no longer written for canonical-covered parsers (sharekhan, dbs_vickers, ibkr_activity_csv, uob_account, ocbc_account, dbs_transaction_history).
- Bank/cash parsers route to account_balance_snapshots via run_upload_balance_canonical_adapter; investment parsers route to portfolio_position_snapshots via existing run_upload_canonical_adapter.
- is_canonical_upload_platform() preserved for backward compatibility; new parser_canonical_target() is the authoritative lookup.
- Upload report counts gain canonical_positions_written and canonical_balances_written as additive fields; positions_inserted remains at 0 for covered parsers.
- Unregistered parsers that emit positions fail with status=FAILED and canonical_adapter_missing error code.

### Acceptance Criteria
- All parsers that can emit positions have an explicit canonical adapter mapping – YES (PARSER_CANONICAL_REGISTRY covers all 8 known parsers)
- Sharekhan, DBS Vickers produce canonical facts in portfolio_position_snapshots – YES
- UOB account, OCBC account, DBS transaction history produce canonical facts in account_balance_snapshots – YES
- Pre-cutover/reference IBKR CSV produces canonical facts – YES
- Upload runner no longer inserts/updates legacy positions for canonical-covered parsers – YES
- Canonical adapter errors are blocking – YES (exception propagates, job marked FAILED)
- Upload reports remain OpenAPI-compatible with additive fields – YES
- Tests fail if new parser emits positions without an adapter – YES (test_unregistered_parser_with_positions_fails_import)
- Existing non-position parsers remain unchanged – YES (credit card parsers verified)

### Planned Paths
- `api/app/portfolio/upload_canonical.py`
- `api/app/ingestion/runner.py`
- `api/tests/test_upload_canonical_phase2.py`
- `api/tests/test_canonical_adapter_registry_phase5.py`

## Build Summary
Implemented canonical portfolio phase 5: added PARSER_CANONICAL_REGISTRY, balance adapter for bank parsers, canonical-first blocking write order in runner, legacy positions suppressed for covered parsers, and comprehensive Phase 5 tests.

### Changed Files
- `api/app/ingestion/runner.py`
- `api/app/portfolio/upload_canonical.py`
- `api/tests/test_canonical_adapter_registry_phase5.py`
- `api/tests/test_upload_canonical_phase2.py`
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
Implemented canonical portfolio phase 5: added PARSER_CANONICAL_REGISTRY, balance adapter for bank parsers, canonical-first blocking write order in runner, legacy positions suppressed for covered parsers, and comprehensive Phase 5 tests.

- semantic_intent_achieved: `True`
- provider_model: `copilot/claude-sonnet-4.6`

### Semantic Checks
- `pass` All parsers that can emit positions have an explicit canonical adapter mapping: PARSER_CANONICAL_REGISTRY covers all 8 parsers; test_all_parsers_have_canonical_registry_entry verifies PARSER_REGISTRY ⊆ PARSER_CANONICAL_REGISTRY
- `pass` Uploads from Sharekhan, DBS Vickers produce canonical portfolio_position_snapshots: Existing phase2 tests verify canonical write; test_sharekhan_upload_does_not_write_legacy_positions confirms legacy is 0
- `pass` Uploads from UOB account, OCBC account, DBS transaction history produce account_balance_snapshots: test_ocbc_upload_writes_canonical_balance_not_legacy_positions, test_dbs_transaction_upload_writes_canonical_balance, test_balance_adapter_writes_account_balance_snapshot all pass
- `pass` The upload runner no longer inserts or updates legacy positions for canonical-covered parser outputs: test_sharekhan_upload_does_not_write_legacy_positions and test_dbs_vickers_upload_do_not_write_legacy_positions confirm positions_inserted=0 and legacy positions table has 0 rows
- `pass` Canonical adapter errors are blocking for position-producing parsers and visible in the upload report: test_canonical_adapter_failure_fails_import verifies status=FAILED when adapter raises
- `pass` Upload reports remain OpenAPI-compatible; removed semantics represented by additive fields: positions_inserted remains at 0, new canonical_positions_written and canonical_balances_written added as additive fields
- `pass` Tests fail if a new parser emits positions without an adapter: test_unregistered_parser_with_positions_fails_import patches a fake parser and verifies FAILED status with canonical_adapter_missing error
- `pass` Existing non-position transaction/card parsers remain unchanged: test_citi_credit_card_upload_not_affected verifies credit card import still succeeds; 929 pre-existing tests all pass

### Risk Flags
- Dashboard/portfolio read paths that currently query legacy positions for SHAREKHAN/DBS_VICKERS data will see no new rows after this phase. The read-side cutover is Issue 182 scope and is explicitly out of scope here.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Retry Log
- test-backend: attempt 1/3, class=code, exit=2, log=.task-flow/failures/20260626T011726Z_test-backend_attempt1.log, notes=Code failure with no auto-fix available: """An upload from an unregistered parser that emits positions must fail with FAILED status."""

## Blockers
- Deterministic gates failed: test-backend

## Permanently Failed / Gave Up
- Stop reason: Deterministic gates failed: test-backend
- Attempted mitigations:
- mitigation: Code failure with no auto-fix available: """An upload from an unregistered parser that emits positions must fail with FAILED status."""
- Suggested human action: Fix the cited blocker and rerun the workflow on the same thread.
<!-- MACHINE_RENDERED_END -->
