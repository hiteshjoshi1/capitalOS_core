# Issue 134: IBKR Flex import deletes position and cash history for every report date; rebuild what can be rebuilt

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/134

## Objective
- A multi-day IBKR Flex import (e.g. a 30- or 365-day backfill) must only replace the facts the
  report actually carries. Today it deletes positions, cash, metrics, reconciliations and
  completeness on every NAV date, but a multi-day report has positions and cash only for its
  period end, so earlier daily holdings are lost.
- Restore the holdings that earlier imports deleted, from the raw Flex XMLs those imports kept.

## Architecture Decisions
- Delete scope per table (`FactScopes` in `api/app/portfolio/ibkr_flex.py`):
  positions on dates with position rows, cash on dates with cash rows, NAV on NAV dates,
  report metrics on metric/cash dates, reconciliations only where NAV, positions and cash are
  all in the report, completeness on the NAV and holdings dates. The period end (`toDate`) counts
  as carried for positions and cash whenever the report has NAV for it, so re-importing a date
  after selling everything still clears the stale holding (unchanged single-day behaviour).
- NAV-only dates get completeness `nav_only` (`missing_reason = holdings_not_in_report`) unless
  the stored facts still hold cash and positions for that date (or the NAV's stock is zero),
  then `complete`. No reconciliation is written for a NAV-only date (it used to compare NAV to
  zero components and record a fabricated warning).
- Cash ledger (StatementOfFundsLine), trades and corporate actions keep their row-level
  replace logic; they never went through the date-wide delete.
- Rebuild tool `make ibkr-rebuild-snapshots [APPLY=1] [BROKER_ACCOUNT_ID=] [RAW_DIR=]`
  (`api/app/portfolio/ibkr_flex_rebuild.py`, CLI `app.scripts.rebuild_ibkr_flex_snapshots`):
  reads the retained XML of each completed import, newest first; the newest report speaking
  for a date decides it; restores positions/cash only where the DB has none for that date,
  linked to that report's import run and raw document; verifies the file's sha256 against
  `content_hash`; never creates or moves authority windows, never touches NAV, FX, metrics,
  reconciliations, ledger, trades. Restored authority status = the date's NAV row status, else
  the authority windows. Only extra write: `nav_only` completeness → `complete` once holdings
  are back. Dry run by default, idempotent, prints counts per date only.

## Acceptance Criteria
- [x] Multi-day report keeps earlier positions/cash; NAV for every day is replaced.
- [x] No fabricated reconciliation warnings or `complete` status for NAV-only dates.
- [x] Ledger and trades unaffected.
- [x] Rebuild tool: dry run by default, APPLY=1 writes, idempotent, per-date counts, original lineage, no authority-window/NAV/ledger/trade writes.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_ibkr_flex_history_scope.py tests/test_ibkr_flex_phase1.py -q`
- Isolated stack: `make up && make db-migrate`, import synthetic daily D1, D2 and a D1..D3 report,
  delete D1/D2 holdings, then `make ibkr-rebuild-snapshots` (dry run lists D1, D2),
  `make ibkr-rebuild-snapshots APPLY=1` (restores, completeness → complete), and again (0 dates).

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `tests`: pass — `tests/test_ibkr_flex_history_scope.py` (6) + `tests/test_ibkr_flex_phase1.py` (26)
- `make verify`: see PR description
- `e2e`: pass — isolated Postgres stack, rebuild dry run / apply / re-apply as described above

## Human Action Summary (Codex Mutable)
- Next expected action: on the test instance (restored real backup), copy the main checkout's
  `data/broker_raw/ibkr_flex/*.xml` where the test api container can read them (or pass
  `RAW_DIR=`), run `make ibkr-rebuild-snapshots`, review the per-date counts, then `APPLY=1`.
