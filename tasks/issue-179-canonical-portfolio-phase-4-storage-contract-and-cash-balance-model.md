# Issue 179: Canonical portfolio phase 4 - storage contract and cash balance model

## Objective
- Define and implement the canonical-only storage contract needed before retiring legacy `positions`.
- Remove the architectural ambiguity where `positions` stores both securities and cash balances.
- Add the minimal table/read-model design required for net worth, stock holdings, and cash views to read canonical facts without special legacy fallbacks.

## Parent Architecture
- Umbrella architecture: [Issue 175](./issue-175-ibkr-flex-broker-neutral-portfolio-ingestion.md)
- Phase 1 dependency: [Issue 176](./issue-176-canonical-portfolio-phase-1-ibkr-flex-cutover.md)
- Phase 2 dependency: [Issue 177](./issue-177-canonical-portfolio-phase-2-upload-parser-adapters.md)
- Phase 3 dependency: [Issue 178](./issue-178-canonical-portfolio-phase-3-dashboard-analytics-read-migration.md)
- Follow-up implementation: [Issue 180](./issue-180-canonical-portfolio-phase-5-complete-parser-adapters-and-stop-legacy-position-writes.md)

## Architecture Direction
- Canonical source of truth means one canonical portfolio layer, not one physical table.
- Security holdings belong in `portfolio_position_snapshots`.
- Broker/account NAV belongs in `portfolio_nav_snapshots`.
- Cash/account balances must not be encoded as security positions. Add a canonical cash/account-balance snapshot model rather than continuing to use `positions(asset_class='CASH')`.
- Legacy `positions` is a bridge only. It should not receive new authoritative facts once all position-producing parsers have canonical adapters.

## Proposed Table Design

Add a general account cash/balance snapshot table for non-security balances:

```text
account_balance_snapshots
- id
- account_id                         # user-visible CapitalOS account
- broker_account_id nullable          # populated when source also has broker identity
- import_job_id nullable              # upload lineage for bank/card/account parsers
- broker_import_run_id nullable       # canonical broker import lineage
- raw_document_id nullable
- as_of_date
- currency
- balance_type                        # cash | broker_cash | bank_cash | credit_balance | loan_balance | stablecoin_cash
- balance_local
- balance_base
- fx_rate_to_base
- authority_status                    # authoritative | reference | superseded
- source_kind                         # upload parser / flex / backfill / manual adjustment
- source_row_hash nullable
- metadata_json
- created_at
- updated_at
```

Natural-key rule:

```text
UNIQUE (account_id, as_of_date, currency, balance_type)
WHERE authority_status = 'authoritative'
```

Design notes:
- `portfolio_cash_balance_snapshots` may remain as broker-specific raw canonical evidence for IBKR/Flex detail, but net-worth/cash read services should consume a single canonical cash-balance abstraction that includes `account_balance_snapshots` and any broker cash detail intentionally promoted into that abstraction.
- Do not force bank accounts into `broker_accounts` just to reuse broker-specific tables. That makes the model harder to understand and extend.
- Do not add another legacy projection table unless it has a clear owner and can be deleted later.

## Scope

### In Scope
- Add migration(s) for the canonical account balance snapshot table and indexes.
- Add a small canonical balance read service that returns cash-like rows in one shape for dashboard/net-worth callers.
- Define source authority and idempotency rules for balance snapshots.
- Define how existing `portfolio_cash_balance_snapshots` feeds the canonical cash read abstraction.
- Update documentation comments and task docs so future adapters know where to write cash balances.

### Out Of Scope
- Retiring `positions`.
- Migrating historical data.
- Changing frontend behavior.
- Adding new broker importers.

## Architecture Decisions
- `positions` retirement requires a replacement for both securities and cash; securities already have canonical tables, cash does not.
- The canonical cash balance model references `accounts` directly because bank accounts, broker cash, and other cash-like balances are account-level facts.
- Broker-specific cash evidence can remain broker-specific, but dashboard reads should not need to know whether cash came from a bank parser, broker upload, Flex, or a future API connector.
- Keep money/quantity values `NUMERIC` in the database and `Decimal` in parser/write code.
- Additive schema first; destructive cleanup is a later issue.

## Acceptance Criteria
- [ ] A canonical account balance snapshot table exists with source lineage, authority status, currency, local/base values, and idempotent uniqueness.
- [ ] A canonical cash/balance read service returns one normalized shape for all account cash balances.
- [ ] Existing `portfolio_cash_balance_snapshots` can be surfaced through the normalized cash read abstraction without double-counting.
- [ ] No dashboard endpoint is migrated in this issue unless needed for a focused smoke test.
- [ ] OpenAPI remains compatible.
- [ ] Unit tests cover idempotency, FX/base values, source authority, and account scoping.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Add migration for `account_balance_snapshots`.
- [ ] Add model/schema or typed SQL helpers as used by the backend.
- [ ] Add canonical cash/balance read service.
- [ ] Add tests for account scoping, uniqueness, idempotency, and broker-cash promotion.
- [ ] Update canonical portfolio docs with the final cash table decision.
- [ ] Run deterministic safety gates.

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `pending`
- `typecheck`: `pending`
- `tests`: `pending`
- `api-smoke`: `pending`
- `e2e`: `pending`

## Execution Journal (Codex Mutable)
- Current Stage: `planned`
- Workflow Status: `ready-for-implementation`
- Provider/Model: `openai/gpt-5-codex`
- Last Updated: `2026-06-25T00:00:00Z`

## Automation Log (Mutable)
- 2026-06-25T00:00:00Z - Created as the first step toward canonical-only portfolio storage and legacy `positions` retirement.

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `completed`
**Workflow Status**: `passed`

## Workflow Snapshot
- latest_outcome: Implemented Issue 179: canonical account balance snapshot table, SQLAlchemy model, canonical cash read abstraction, and full unit test suite. All deterministic gates pass.
- next_action: None.
- pipeline_version: `v3`
- provider_model: `copilot/claude-sonnet-4.6`
- latest_failed_checks: `none`
- retry_gate_pending: `no`
- retry_detail: `api-smoke` stopped after attempt 1/3: Code failure with no auto-fix available: make[1]: *** [api-smoke] Error 1
- retry_detail: `contract-backend` stopped after attempt 1/3: Code failure with no auto-fix available: ImportError while loading conftest '/app/tests/conftest.py'.
- retry_detail: `test-backend` stopped after attempt 1/3: Code failure with no auto-fix available: ImportError while loading conftest '/app/tests/conftest.py'.
- blocked_reason: `none`
- stopped_due_to: `none`

## Active Requirements
- Acceptance criterion: A canonical account balance snapshot table exists with source lineage, authority status, currency, local/base values, and idempotent uniqueness.
- Acceptance criterion: A canonical cash/balance read service returns one normalized shape for all account cash balances.
- Acceptance criterion: Existing portfolio_cash_balance_snapshots can be surfaced through the normalized cash read abstraction without double-counting.
- Acceptance criterion: No dashboard endpoint is migrated in this issue unless needed for a focused smoke test.
- Acceptance criterion: OpenAPI remains compatible.
- Acceptance criterion: Unit tests cover idempotency, FX/base values, source authority, and account scoping.

## Prepare
Checked out `feature/issue-179-canonical-portfolio-phase-4-storage-contract-and-cash-balance-model` from `main` and ensured task file exists.

## Plan Summary
1) Added migration 056 creating account_balance_snapshots with natural-key uniqueness for authoritative rows. 2) Added AccountBalanceSnapshot SQLAlchemy model. 3) Extended canonical_reads.py with canonical_account_balance_rows() that merges account_balance_snapshots (preferred) and portfolio_cash_balance_snapshots (fallback for accounts without canonical rows) into one normalized shape. 4) Added 14 unit tests covering idempotency, FX/base values, source authority, account scoping, and broker cash promotion/anti-double-count. 5) Updated conftest.py to create/clear/drop the new table in test lifecycle.

### Architecture Decisions
- account_balance_snapshots references accounts(id) directly so bank accounts are not forced into broker_accounts just to reuse broker-specific tables.
- broker_account_id is nullable on account_balance_snapshots, allowing non-broker sources (bank parsers, manual adjustments) to write without a broker lineage.
- canonical_account_balance_rows() uses UNION ALL to merge account_balance_snapshots and portfolio_cash_balance_snapshots in a single SQL pass, with an EXISTS exclusion guard to prevent double-counting when both tables have rows for the same account.
- authority_status partial unique index ensures natural-key uniqueness only for 'authoritative' rows; 'reference' and 'superseded' rows can coexist.
- balance_type enum (cash | broker_cash | bank_cash | credit_balance | loan_balance | stablecoin_cash) allows future adapters to distinguish source without additional schema changes.
- source_kind column (upload_parser | flex | backfill | manual_adjustment) mirrors the provenance pattern already used in portfolio_source_authority_windows.

### Acceptance Criteria
- A canonical account balance snapshot table exists with source lineage, authority status, currency, local/base values, and idempotent uniqueness.
- A canonical cash/balance read service returns one normalized shape for all account cash balances.
- Existing portfolio_cash_balance_snapshots can be surfaced through the normalized cash read abstraction without double-counting.
- No dashboard endpoint is migrated in this issue unless needed for a focused smoke test.
- OpenAPI remains compatible.
- Unit tests cover idempotency, FX/base values, source authority, and account scoping.

### Planned Paths
- `migrations/056_canonical_account_balance_snapshots.sql`
- `api/app/models/canonical_balance.py`
- `api/app/portfolio/canonical_reads.py`
- `api/tests/test_canonical_account_balance_phase4.py`
- `api/tests/conftest.py`

## Build Summary
Implemented Issue 179: canonical account balance snapshot table, SQLAlchemy model, canonical cash read abstraction, and full unit test suite. All verification gates pass.

### Changed Files
- `api/app/models/__init__.py`
- `api/app/models/canonical_balance.py`
- `api/app/portfolio/canonical_reads.py`
- `api/tests/conftest.py`
- `api/tests/test_canonical_account_balance_phase4.py`
- `migrations/056_canonical_account_balance_snapshots.sql`
- `tasks/issue-179-canonical-portfolio-phase-4-storage-contract-and-cash-balance-model.md`

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
Implemented Issue 179: canonical account balance snapshot table, SQLAlchemy model, canonical cash read abstraction, and full unit test suite. All verification gates pass.

- semantic_intent_achieved: `True`
- provider_model: `copilot/claude-sonnet-4.6`

### Semantic Checks
- `pass` A canonical account balance snapshot table exists with source lineage, authority status, currency, local/base values, and idempotent uniqueness.: migrations/056_canonical_account_balance_snapshots.sql creates account_balance_snapshots with broker_import_run_id/import_job_id/raw_document_id lineage columns, authority_status, currency, balance_local/balance_base/fx_rate_to_base, and a partial unique index on (account_id, as_of_date, currency, balance_type) WHERE authority_status = 'authoritative'.
- `pass` A canonical cash/balance read service returns one normalized shape for all account cash balances.: canonical_account_balance_rows() in canonical_reads.py returns dicts with keys account_id, currency, balance_type, balance_local, balance_base, fx_rate, source, as_of_date for all accounts visible to the caller.
- `pass` Existing portfolio_cash_balance_snapshots can be surfaced through the normalized cash read abstraction without double-counting.: canonical_account_balance_rows() surfaces PCBS rows only for accounts NOT covered by account_balance_snapshots (via abs_covered_accounts exclusion). TestBrokerCashPromotion tests verify both the surfacing and the anti-double-count guard.
- `pass` No dashboard endpoint is migrated in this issue unless needed for a focused smoke test.: No router files were modified. The new function is a library-level addition only.
- `pass` OpenAPI remains compatible.: No router or schema files were changed. make contract-backend and make contract-frontend both pass.
- `pass` Unit tests cover idempotency, FX/base values, source authority, and account scoping.: test_canonical_account_balance_phase4.py: TestIdempotency (3 tests), TestFXValues (2 tests), TestSourceAuthority (2 tests), TestAccountScoping (2 tests), TestBrokerCashPromotion (4 tests). All 916 backend tests pass.

### Risk Flags
- portfolio_cash_balance_snapshots fallback in canonical_account_balance_rows() is a transitional bridge and must be retired in a later issue once all broker cash writers are migrated to account_balance_snapshots.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Retry Log
- contract-backend: attempt 1/3, class=code, exit=2, log=.task-flow/failures/20260625T100928Z_contract-backend_attempt1.log, notes=Code failure with no auto-fix available: ImportError while loading conftest '/app/tests/conftest.py'.
- test-backend: attempt 1/3, class=code, exit=2, log=.task-flow/failures/20260625T100930Z_test-backend_attempt1.log, notes=Code failure with no auto-fix available: ImportError while loading conftest '/app/tests/conftest.py'.
- api-smoke: attempt 1/3, class=code, exit=2, log=.task-flow/failures/20260625T100930Z_api-smoke_attempt1.log, notes=Code failure with no auto-fix available: make[1]: *** [api-smoke] Error 1

## Blockers
- None

## Permanently Failed / Gave Up
- None
<!-- MACHINE_RENDERED_END -->
