# Issue 176: Canonical portfolio phase 1 - IBKR Flex cutover

## Objective
- Implement the first production slice of the canonical portfolio model using IBKR Flex as the first cutover source.
- Ingest daily IBKR Flex reports into canonical import lineage, source authority, instrument, snapshot, FX, report-metric, and reconciliation tables.
- Cut over IBKR so Flex becomes the authoritative source for holdings, cash, NAV, FX, and future IBKR activity from a configured cutover date.
- Do not change Sharekhan, DBS Vickers, or other existing upload behavior in this phase.

## Parent Architecture
- Umbrella architecture: [Issue 175](./issue-175-ibkr-flex-broker-neutral-portfolio-ingestion.md)
- Canonical model docs: [Canonical Portfolio Data Model](../docs/finance/canonical-portfolio-model.md)

## Scope

### In Scope
- Add additive schema for the phase-1 canonical tables:
  - `broker_connections`
  - `broker_accounts`
  - `portfolio_source_authority_windows`
  - `broker_import_runs`
  - `raw_broker_documents`
  - `broker_instruments`
  - `asset_identifiers`
  - `portfolio_position_snapshots`
  - `portfolio_cash_balance_snapshots`
  - `portfolio_nav_snapshots`
  - `portfolio_report_metrics`
  - `portfolio_fx_rates`
  - `portfolio_reconciliations`
  - `portfolio_data_quality_events`
  - `portfolio_data_completeness`
- Implement IBKR Flex client:
  - `SendRequest`
  - `GetStatement`
  - XML parsing with a real XML parser
  - bounded retry/backoff for still-generating responses
  - secret redaction
- Parse and normalize current daily Flex sections:
  - `EquitySummaryInBase`
  - `CashReport`
  - `StmtFunds`
  - `OpenPositions`
  - `Trades`
  - `CorporateActions`
  - `ConversionRates`
- Store raw XML immutably before normalization.
- Enforce source authority and cutover rules for IBKR.
- Store reconciliation results and data-quality outcomes.
- Add manual trigger and scheduler with database locking.
- Make Flex account dashboard total use canonical NAV, including dividend and interest accruals, once an authoritative Flex snapshot exists.

### Out Of Scope
- Adapting Sharekhan, DBS Vickers, DBS, UOB, OCBC, Citi, or legacy IBKR CSV upload parsers into canonical writes. That is phase 2.
- Migrating all dashboard/analytics reads to canonical tables. That is phase 3.
- Full historical return calculations, TWR, MWR, realized P&L, and closed-position analytics.
- Replacing existing `positions`, `transactions`, or `assets` tables.

## Architecture Decisions
- IBKR Flex is the first canonical cutover source, not a special-case long-term sidecar.
- Existing manual IBKR uploads remain reference/history before cutover and are rejected for authoritative facts on/after cutover.
- Canonical facts must use `Decimal` / `NUMERIC`, not floating point.
- `reportDate` is the accounting date. `whenGenerated` is report metadata.
- `BASE_SUMMARY` cash is never inserted as a spendable cash balance.
- `broker_instruments` represent broker tradable contracts; `assets` are nullable mapping targets.
- Missing FX for a held currency prevents fake base valuation.
- Scheduler overlap must be prevented with a database-backed lock or active-import constraint, not only APScheduler `max_instances`.

## Acceptance Criteria
- [ ] Phase-1 canonical migrations are additive and do not modify existing upload parser tables destructively.
- [ ] IBKR source authority windows enforce that Flex is authoritative on/after the configured cutover date.
- [ ] Manual IBKR uploads on/after cutover are rejected for authoritative holdings, cash, NAV, FX, and activity.
- [ ] Sharekhan and DBS Vickers upload tests pass unchanged.
- [ ] Flex credentials are read from configuration and are never logged, returned, persisted, or included in reports.
- [ ] Flex client uses application HTTP code and XML parser, not shell commands, curl, regex, or string extraction.
- [ ] Raw Flex XML is stored immutably with content hash, source type, report date, parser version, and import metadata before normalization.
- [ ] `OpenPositions` creates/updates `broker_instruments` and canonical position snapshots without auto-merging instruments by ticker plus currency.
- [ ] `CashReport` creates per-currency cash balance snapshots and stores report-period metrics in `portfolio_report_metrics`.
- [ ] `EquitySummaryInBase` creates NAV snapshots including dividend and interest accruals.
- [ ] `ConversionRates` creates broker FX rate snapshots.
- [ ] Same Flex XML imported twice creates exactly one authoritative snapshot set and one reconciliation result per report date.
- [ ] Non-zero IBKR stock NAV with empty `OpenPositions` fails safely and leaves the displayed portfolio unchanged.
- [ ] Missing FX rate for a held currency marks the import partial/failed and creates no fake base valuation.
- [ ] Dashboard total for the IBKR Flex account equals canonical NAV, including accruals.
- [ ] Scheduler and manual trigger overlap creates only one successful import run for a broker account/report date.
- [ ] Reconciliation results and data-quality events are queryable.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Add additive migrations for phase-1 canonical tables and indexes.
- [x] Add models/typed SQL helpers for canonical portfolio tables.
- [x] Implement source authority resolution and IBKR cutover enforcement.
- [x] Implement immutable raw Flex document storage.
- [x] Implement IBKR Flex client with retry/backoff and redacted logging.
- [x] Implement Flex XML parser and canonical normalizer.
- [x] Implement snapshot, metric, FX, and reconciliation upserts.
- [x] Implement scheduler/manual trigger with database lock.
- [x] Add Flex account canonical NAV dashboard path.
- [x] Add focused tests and existing upload non-regression tests.
- [x] Run deterministic safety gates.

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `make api-rebuild`: `passed`
- `make db-migrate`: `passed` (migration 055 applied; existing Postgres collation-version warning remains)
- `docker compose exec api pytest tests/test_ibkr_flex_phase1.py tests/test_ingest_sharekhan.py tests/test_ingest_dbs_vickers.py -q`: `passed` (9 passed)
- `make api-test`: `passed` (867 passed, 4 skipped)
- `make api-smoke`: `passed`
- `make lint`: `passed` (existing frontend React hook warning; backend ruff not installed, skipped by target)
- `make typecheck`: `passed` (backend mypy not installed, skipped by target)

## Execution Journal (Codex Mutable)
- Current Stage: `implemented`
- Workflow Status: `phase-1-complete`
- Provider/Model: `openai/gpt-5-codex`
- Last Updated: `2026-06-20T13:22:00Z`

## Automation Log (Mutable)
- 2026-06-20T09:03:51Z - Created phase-1 implementation issue from canonical portfolio architecture.
- 2026-06-20T13:16:00Z - Implemented phase-1 IBKR Flex canonical ingestion, cutover guard, dashboard NAV overlay, scheduler/manual trigger, migration 055, and regression tests.
- 2026-06-20T13:22:00Z - Added canonical trade and corporate-action persistence for daily Flex activity; reran focused broker tests, full API suite, lint, and typecheck.
