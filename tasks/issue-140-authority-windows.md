# Issue 140: Authority windows: one per account/source/scope, no overlaps, one mechanism

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/140 (from #130, finding 1.3)

## Objective
- A backfill (or any import) can no longer silently change which source counts for past dates.
- One authority window per (broker account, source, scope); moving one is explicit and logged.
- One way for readers to decide that a canonical fact counts, instead of ~22 hand-copied predicates.

## Architecture Decisions
- **One mechanism: status.** Readers count position / cash / NAV rows by `authority_status = 'authoritative'`
  alone (`app.portfolio.authority.authoritative_sql`). Windows are the write gate: an importer stamps each fact
  from its window (`AuthorityWindow.status_for`). Windows still route a legacy account to its Flex broker
  account at a date (`window_covers_sql`, used by `flex_authority_accounts`, `is_ibkr_flex_cutover_active`,
  the legacy-backfill skip), but never promote a row. Rejected: keeping "status OR window" behind one helper
  (two mechanisms, and the window lookup on every read).
- **Imports never move a window.** `ensure_window` creates it when missing, else returns it unchanged. Facts
  outside it are stored as `reference` and the import records an `authority_window_unchanged` warning.
- **Explicit move:** `authority.move_window` / `make authority-window-move ... [APPLY=1]` (dry run by default):
  updates the one row in place, logs to `portfolio_source_authority_window_changes`, restamps that source's
  facts on the broker account (rows of its own import runs only, authoritative <-> reference), and marks
  History dirty from min(old start, new start) (D-29).
- **No overlaps:** unique index on (broker_account_id, source_kind, fact_scope) (SQLite and Postgres), plus a
  code check that two sources on the same broker account don't hold overlapping authoritative windows for
  overlapping scopes (`all` overlaps every scope). Rejected: a Postgres `EXCLUDE USING gist` constraint (needs
  the btree_gist extension and isn't testable on SQLite; the unique index already rules out same-scope overlaps).
- **Superseded windows close:** a new Flex window closes other sources' open windows on the same legacy
  account and platform (the IBKR CSV upload window) the day before it starts, logged.
- **Migration 075 collapse rule** (deterministic): per triple, keeper = first by (authoritative first, earliest
  `effective_from`, lowest id). If authoritative, its `effective_to` = NULL if any authoritative window of the
  triple was open, else the latest `effective_to`. Others are logged (`collapsed`) and deleted. Before that,
  rows counted only through a Flex window are promoted to `authoritative` (and History marked dirty from the
  earliest). It stops, changing nothing, if a triple's authoritative windows have a gap or a promotion would
  break an authoritative unique index.

## Acceptance Criteria
- [x] Backfilling an older period doesn't change which source counts without an explicit action
  (`test_backfill_with_an_earlier_start_does_not_move_the_window`, `..._explicit_cutover_earlier...`).
- [x] One window per (broker account, source, scope) (`test_daily_imports_keep_one_window...`, unique index test).
- [x] Moving `effective_from` is explicit and logged; superseded windows closed (`test_explicit_move...`,
  `test_a_new_flex_window_closes_the_upload_window_it_supersedes`).
- [x] No overlapping windows (`test_one_window_per_scope_is_a_unique_index`,
  `test_another_source_cannot_hold_an_overlapping_window_on_the_same_account`).
- [x] One reader mechanism, documented in `docs/finance/canonical-portfolio-model.md`
  (`test_no_reader_copies_the_window_predicate`).
- [x] Migration keeps the same rows authoritative on synthetic pre-#140 data (growing + overlapping windows,
  rows counted only via a window) on SQLite (`test_migration_075_*`) and on Postgres (isolated stack, check
  query before/after identical).

## How To Test
- `make verify`.
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_authority_windows.py -q`.
- On a copy of the data: run `scripts/authority-windows-075-check.sql` before and after `make db-migrate`;
  AFTER's old_rule and status columns must both equal BEFORE's old_rule columns, window ranges unchanged.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `lint`: pass (`make verify`)
- `typecheck`: pass (`make verify`)
- `tests`: pass: backend 682 passed, 1 skipped; frontend 304 passed (45 files)
- `e2e`: skip (no UI change)
- `api-smoke`: pass: on the isolated Postgres stack, a Flex import, a backfill with an earlier start (window
  unchanged, Jan NAV not counted), a dry-run and applied move (Jan NAV counted, change logged), and the
  canonical readers.
- `policy-checks`: pass (migration 075 applied with `make db-migrate`; guards raise on a gap and on a key
  collision, inside a rolled-back transaction)

## Extra Files Changed (Codex Mutable)
- `docker-compose.yml`: reason: `api-dev` mounts `./migrations` read-only so tests run the migration's real SQL.
- `Makefile`: reason: `authority-windows` / `authority-window-move` targets (the explicit action).
- `scripts/authority-windows-075-check.sql`: reason: the before/after check for the owner's test copy.
- `api/app/routers/portfolio.py`: reason: the `cutover_date` query description now says it only seeds a new window.
