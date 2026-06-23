# Issue 177: Canonical portfolio phase 2 - upload parser adapters

## Objective
- Adapt existing broker upload parsers into the canonical portfolio model without changing their accepted file formats or parsed semantics.
- Keep Sharekhan and DBS Vickers uploads authoritative for their platforms while writing canonical snapshots through a common normalization layer.
- Preserve existing dashboard output until canonical equivalence tests pass.

## Parent Architecture
- Umbrella architecture: [Issue 175](./issue-175-ibkr-flex-broker-neutral-portfolio-ingestion.md)
- Phase 1 dependency: [Issue 176](./issue-176-canonical-portfolio-phase-1-ibkr-flex-cutover.md)
- Canonical model docs: [Canonical Portfolio Data Model](../docs/finance/canonical-portfolio-model.md)

## Mandatory Pre-Work Context
- Before attempting this issue, read Issue 175 end to end. It defines the target canonical portfolio architecture and why this is a phased migration rather than an IBKR-only feature.
- Before implementing any adapter code, read the completed Issue 176 implementation and treat it as the first canonical write-path reference, not as throwaway Flex-specific code.
- Specifically inspect:
  - `migrations/055_canonical_portfolio_phase1.sql` for the canonical tables, uniqueness rules, lineage tables, source authority windows, and import lock table.
  - `api/app/portfolio/ibkr_flex.py` for source authority setup, raw document storage, idempotent fact replacement, reconciliation, completeness, data-quality events, and broker-instrument identity handling.
  - `api/app/routers/portfolio.py` for canonical import trigger and read-only import diagnostics.
  - `api/app/portfolio/scheduler.py` for disabled-by-default scheduled canonical imports and DB-backed overlap protection.
  - `api/app/routers/ingest.py` for the IBKR post-cutover manual-upload guard.
  - `api/app/routers/dashboard.py` for the temporary phase-1 canonical NAV overlay that avoids double counting cutover IBKR accounts.
  - `api/tests/test_ibkr_flex_phase1.py` for expected idempotency, failure-safety, missing-FX, dashboard NAV, and non-regression behavior.
- Do not introduce a second canonical write style for upload parsers. Phase 2 should reuse or generalize the Issue 176 patterns where they fit: source authority, raw lineage, broker instruments, idempotent writes, completeness metadata, and data-quality events.
- If the Issue 176 implementation conflicts with Issue 175's architecture, update the task plan with the discrepancy and stop before making code changes.

## Scope

### In Scope
- Add a canonical adapter layer for existing `ParseResult` outputs.
- Convert upload parser positions into canonical `broker_instruments`, `portfolio_position_snapshots`, and where applicable `portfolio_cash_balance_snapshots`.
- Convert upload parser trades/cash transactions into canonical ledgers where source detail is sufficient.
- Preserve lower-detail upload data with explicit `portfolio_data_completeness` records rather than inventing missing history.
- Configure source authority windows:
  - Sharekhan upload remains authoritative for Sharekhan holdings.
  - DBS Vickers upload remains authoritative for DBS Vickers holdings.
  - Legacy IBKR CSV is pre-cutover reference/history only after phase 1 cutover.
- Add before/after equivalence tests for positions and dashboard output.

### Out Of Scope
- New broker APIs or scraping.
- Full dashboard read migration. That is phase 3.
- Retiring legacy `positions` or `transactions`.
- Historical performance metrics that require complete trade/cash/corporate-action history.

## Architecture Decisions
- Existing parser interfaces remain stable; adaptation happens after parsing.
- Source authority determines whether uploaded rows become authoritative canonical facts or reference-only evidence.
- Uploads with incomplete detail are valid canonical inputs, but completeness metadata must say what is missing.
- Canonical adapter output must be deterministic and idempotent.
- Legacy writes may continue during the bridge, but canonical writes become the target investment-platform truth.

## Acceptance Criteria
- [ ] Existing upload endpoint behavior remains OpenAPI-compatible.
- [ ] Existing parser tests for Sharekhan, DBS Vickers, IBKR CSV, DBS, UOB, OCBC, and Citi pass.
- [ ] Sharekhan upload before/after canonical adapter migration produces identical legacy `positions` rows and dashboard output.
- [ ] DBS Vickers upload before/after canonical adapter migration produces identical legacy `positions` rows and dashboard output.
- [ ] Sharekhan canonical writes are isolated to Sharekhan source authority windows.
- [ ] DBS Vickers canonical writes are isolated to DBS Vickers source authority windows.
- [ ] IBKR manual CSV upload after Flex cutover cannot create authoritative canonical IBKR facts.
- [ ] Uploads that lack cash/NAV/trade detail create explicit completeness records.
- [ ] Adapter writes are idempotent for repeated identical uploads.
- [ ] No Flex code path writes to Sharekhan or DBS Vickers canonical facts.
- [ ] Existing upload reports continue to show useful parser counts and warnings.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Inspect all existing parser outputs and map them to canonical facts.
- [ ] Add adapter services for upload positions, cash balances, and transactions.
- [ ] Add source authority setup for Sharekhan, DBS Vickers, and legacy IBKR upload windows.
- [ ] Add completeness records for missing source dimensions.
- [ ] Add idempotent canonical upserts for upload-derived facts.
- [ ] Add before/after equivalence tests for Sharekhan and DBS Vickers.
- [ ] Add non-regression tests for all existing upload parsers.
- [ ] Run deterministic safety gates.

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `pending`
- `typecheck`: `pending`
- `tests`: `pending`
- `api-smoke`: `pending`

## Execution Journal (Codex Mutable)
- Current Stage: `planned`
- Workflow Status: `ready-for-implementation-after-phase-1`
- Provider/Model: `openai/gpt-5-codex`
- Last Updated: `2026-06-20T13:30:00Z`

## Automation Log (Mutable)
- 2026-06-20T09:03:51Z - Created phase-2 upload adapter issue from canonical portfolio architecture.
- 2026-06-20T13:30:00Z - Added mandatory pre-work context requiring Issue 175 and completed Issue 176 implementation review before phase-2 work.

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `done`
**Workflow Status**: `shipped`

## Workflow Snapshot
- latest_outcome: Pushed branch `feature/issue-177-canonical-portfolio-phase-2-upload-parser-adapters`.
- next_action: No action required.
- pipeline_version: `v3`
- provider_model: `copilot/claude-sonnet-4.6`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: Existing upload endpoint behavior remains OpenAPI-compatible
- Acceptance criterion: Existing parser tests for Sharekhan, DBS Vickers, IBKR CSV, DBS, UOB, OCBC, and Citi pass
- Acceptance criterion: Sharekhan upload before/after canonical adapter migration produces identical legacy positions rows and dashboard output
- Acceptance criterion: DBS Vickers upload before/after canonical adapter migration produces identical legacy positions rows and dashboard output
- Acceptance criterion: Sharekhan canonical writes are isolated to Sharekhan source authority windows
- Acceptance criterion: DBS Vickers canonical writes are isolated to DBS Vickers source authority windows
- Acceptance criterion: IBKR manual CSV upload after Flex cutover cannot create authoritative canonical IBKR facts
- Acceptance criterion: Uploads that lack cash/NAV/trade detail create explicit completeness records
- Acceptance criterion: Adapter writes are idempotent for repeated identical uploads
- Acceptance criterion: No Flex code path writes to Sharekhan or DBS Vickers canonical facts
- Acceptance criterion: Existing upload reports continue to show useful parser counts and warnings

## Prepare
Checked out `feature/issue-177-canonical-portfolio-phase-2-upload-parser-adapters` from `main` and ensured task file exists.

## Plan Summary
1) Reviewed Issue 176 canonical write patterns in ibkr_flex.py and migrations/055. 2) Created upload_canonical.py with run_upload_canonical_adapter() implementing source authority, idempotent upserts, completeness records, and IBKR-CSV reference-only guard. 3) Modified runner.py to call the adapter post-legacy-write as a non-blocking step. 4) Created test_upload_canonical_phase2.py with 18 tests covering all acceptance criteria. 5) Rebuilt API container and verified 897 tests pass.

### Architecture Decisions
- Canonical adapter runs after legacy write path so legacy behavior is never disrupted
- IBKR CSV uploads always produce reference authority_status; no authority window is created for reference-only platforms
- Canonical failures are non-blocking: runner logs canonical_warning in report rather than raising
- Source authority windows scoped per broker connection (sharekhan_upload, dbs_vickers_upload) matching Phase 1 pattern
- Completeness records always written for upload parsers marking missing cash/NAV/trade dimensions
- Idempotent writes use delete-then-insert on (broker_account_id, report_date) matching ibkr_flex.py pattern
- No new canonical write style introduced; all patterns reuse or generalise Issue 176 ibkr_flex.py patterns

### Acceptance Criteria
- Existing upload endpoint behavior remains OpenAPI-compatible
- Existing parser tests for Sharekhan, DBS Vickers, IBKR CSV, DBS, UOB, OCBC, and Citi pass
- Sharekhan upload before/after canonical adapter migration produces identical legacy positions rows and dashboard output
- DBS Vickers upload before/after canonical adapter migration produces identical legacy positions rows and dashboard output
- Sharekhan canonical writes are isolated to Sharekhan source authority windows
- DBS Vickers canonical writes are isolated to DBS Vickers source authority windows
- IBKR manual CSV upload after Flex cutover cannot create authoritative canonical IBKR facts
- Uploads that lack cash/NAV/trade detail create explicit completeness records
- Adapter writes are idempotent for repeated identical uploads
- No Flex code path writes to Sharekhan or DBS Vickers canonical facts
- Existing upload reports continue to show useful parser counts and warnings

### Planned Paths
- `api/app/portfolio/upload_canonical.py`
- `api/app/ingestion/runner.py`
- `api/tests/test_upload_canonical_phase2.py`
- `migrations/`

## Build Summary
Phase 2 canonical portfolio upload adapter implementation: added canonical adapter layer for Sharekhan and DBS Vickers upload parsers, converting ParseResult outputs into canonical broker_instruments, portfolio_position_snapshots, and completeness records while preserving all legacy write paths and dashboard output.

### Changed Files
- `api/app/ingestion/runner.py`
- `api/app/portfolio/upload_canonical.py`
- `api/tests/test_upload_canonical_phase2.py`
- `tasks/issue-177-canonical-portfolio-phase-2-upload-parser-adapters.md`

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
Phase 2 canonical portfolio upload adapter implementation: added canonical adapter layer for Sharekhan and DBS Vickers upload parsers, converting ParseResult outputs into canonical broker_instruments, portfolio_position_snapshots, and completeness records while preserving all legacy write paths and dashboard output.

- semantic_intent_achieved: `True`
- provider_model: `copilot/claude-sonnet-4.6`

### Semantic Checks
- `pass` Existing upload endpoint behavior remains OpenAPI-compatible: canonical_result and canonical_warning are additive optional fields in runner report dict; no existing fields removed; contract-backend 3 passed
- `pass` Existing parser tests for Sharekhan, DBS Vickers, IBKR CSV, DBS, UOB, OCBC, and Citi pass: make test-backend: 897 passed including all pre-existing parser tests
- `pass` Sharekhan upload before/after canonical adapter migration produces identical legacy positions rows and dashboard output: test_upload_canonical_phase2.py non-regression tests pass; legacy write path in runner.py unchanged
- `pass` DBS Vickers upload before/after canonical adapter migration produces identical legacy positions rows and dashboard output: test_upload_canonical_phase2.py non-regression tests pass; legacy write path unchanged
- `pass` Sharekhan canonical writes are isolated to Sharekhan source authority windows: test_sharekhan_canonical_isolation passes; broker_connection keyed on sharekhan_upload platform
- `pass` DBS Vickers canonical writes are isolated to DBS Vickers source authority windows: test_dbs_vickers_canonical_isolation passes; broker_connection keyed on dbs_vickers_upload platform
- `pass` IBKR manual CSV upload after Flex cutover cannot create authoritative canonical IBKR facts: test_ibkr_csv_reference_only passes; IBKR CSV always produces reference authority_status, no authority window created
- `pass` Uploads that lack cash/NAV/trade detail create explicit completeness records: test_completeness_record_created passes; completeness written with missing_dimensions for all upload parsers
- `pass` Adapter writes are idempotent for repeated identical uploads: test_idempotent_upload passes; 3 identical uploads produce 1 position snapshot row
- `pass` No Flex code path writes to Sharekhan or DBS Vickers canonical facts: ibkr_flex.py untouched; upload_canonical.py has separate entry point; no cross-broker write possible by construction
- `pass` Existing upload reports continue to show useful parser counts and warnings: runner.py _report() extended with canonical_result/canonical_warning; existing counts/warnings fields preserved

### Risk Flags
- Completeness records will always be incomplete for upload parsers until richer upload formats are available; downstream consumers must handle incomplete canonical positions gracefully
- IBKR reference-only guard is name-based; any future IBKR platform name variant not in _REFERENCE_ONLY_PLATFORMS would bypass the guard and require a code update

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Ship Result
Pushed branch `feature/issue-177-canonical-portfolio-phase-2-upload-parser-adapters`.
<!-- MACHINE_RENDERED_END -->
