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
