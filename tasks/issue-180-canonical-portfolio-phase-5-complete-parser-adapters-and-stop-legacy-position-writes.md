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
- `lint`: `pending`
- `typecheck`: `pending`
- `tests`: `pending`
- `api-smoke`: `pending`
- `e2e`: `pending`

## Execution Journal (Codex Mutable)
- Current Stage: `planned`
- Workflow Status: `blocked-on-issue-179`
- Provider/Model: `openai/gpt-5-codex`
- Last Updated: `2026-06-25T00:00:00Z`

## Automation Log (Mutable)
- 2026-06-25T00:00:00Z - Created to complete canonical parser coverage and stop new legacy `positions` writes.
