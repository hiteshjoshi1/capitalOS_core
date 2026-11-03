# Issue 169: IBKR rebuild tool marks History for refresh from the earliest restored date

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/169

## Objective
- After `make ibkr-rebuild-snapshots --apply` restores past position/cash snapshots, the History months that read those dates are recomputed on the next read, without pressing Refresh.

## Architecture Decisions
- `rebuild_account` tracks the earliest restored date per legacy account (the document's run legacy account, else the broker account's) and, on apply only, calls `mark_rollups_dirty(db, earliest, account_id=<legacy>, reason="ibkr_rebuild")` before the per-account commit, so the mark and the restored rows commit or roll back together.
- Dry run (rolled back, and no call) and a run that restores nothing mark nothing.
- `ibkr_flex.py` is not touched.

## Acceptance Criteria
- [x] An applied rebuild marks History dirty from the earliest restored date; a dry run and a no-op second run mark nothing (test).

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_ibkr_flex_history_scope.py -q`
- `make verify`

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `tests`: pass — test_ibkr_flex_history_scope.py + test_wealth_rollup_invalidation.py.
- `make verify`: see PR.
