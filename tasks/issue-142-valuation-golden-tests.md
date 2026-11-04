# Issue 142: Valuation golden and invariant test harness

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/142

## Objective
- A safety net before #143 moves the valuation code out of `api/app/routers/dashboard.py`: fixed
  inputs pin the exact numbers of the main endpoints (goldens), so a refactor can't change a figure
  unnoticed.
- Invariants that must hold between the numbers (breakdowns add up, one figure per page, user
  isolation, D-28/D-29/D-30), with the ones broken today by tracked bugs as strict xfails that flip
  when #144, #140, #180 (and #143's clock step) land.

## Architecture Decisions
- Tests only, no production code change, no migration. Two test-side seams, both in
  `api/tests/valuation_household.py`:
  - `freeze_clock`: replaces `datetime` in the modules on the valuation path with a class whose
    `now()` is frozen (constructors and `isinstance` are the real ones). No new dependency
    (freezegun not added).
  - `_postgres_date_types`: SQLite hands `MIN(as_of_date)` back as text where Postgres returns a
    date; the History rollup's crypto freshness does date arithmetic on it, so on SQLite
    `_crypto_snapshot_coverage_as_of` is wrapped to return a date. (Production on Postgres is
    unaffected; without the wrap the backfill raises `TypeError` on SQLite.)
- Synthetic household built through real write paths where they exist: IBKR Flex XML import
  (`run_ibkr_flex_import_from_xml`), the upload balance adapter (`run_upload_balance_canonical_adapter`),
  `seed_canonical_position_snapshot_for_test` for uploaded holdings; plain inserts for accounts,
  quotes, wallets, transactions. FX: EUR-based rows in `fx_rates`, different every month, never
  1.0; providers off (`remote_enabled` False) so only stored rates count.
- Two frozen instants: `mid` (2026-03-18 10:00 SGT: open month, past months to browse) and `first`
  (2026-04-01 06:00 SGT, still 31 March in UTC: the month-end anchor hasn't passed).
- Goldens: `api/tests/golden/valuation/<scenario>.json`, one key per endpoint path, sorted keys,
  floats rounded to 4 places, `computed_at` masked. A mismatch fails with a unified diff per
  changed endpoint. Regenerated only with `UPDATE_GOLDEN=1` (`make golden-update` in Docker).
- Strict xfails carry the issue number in the reason; the fixing PR removes the marker (and
  regenerates the goldens it deliberately changes).

## Acceptance Criteria
- [x] Harness runs in `make test-backend` (2 golden + 24 invariant tests, about 5 s of the suite).
- [x] Goldens are regenerated only deliberately (`UPDATE_GOLDEN=1` / `make golden-update`);
      regeneration is byte-identical on unchanged code.
- [x] A past month, the current month and the 1st of a month with the clock frozen; FX rates other than 1.
- [x] Invariants: allocation total = net worth + liabilities; Cash page = net-worth cash (+ stablecoins);
      stock exposure = stocks component; plus user isolation, missing FX never 1.0 (D-30), History
      after writes = recompute (D-29), cache on/off identical (D-28). Known violations are strict
      xfails with issue links.

## How To Test
- `make test-backend`: all pass, 9 xfailed (all nine are this harness's strict xfails).
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_valuation_golden.py tests/test_valuation_invariants.py -rxX`
  lists each xfail with its issue.
- `make golden-update` then `git diff api/tests/golden`: no diff on unchanged code.
- `pytest --runxfail tests/test_valuation_invariants.py` shows today's actual violations (numbers).

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes (tests only)
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Strict xfails (flip when fixed)
| Test | Tracked by | What fails today (household numbers) |
|---|---|---|
| `test_cash_page_equals_net_worth_cash_plus_stablecoins` | #144, #180 | Cash page 67,195.17 vs net-worth cash + stablecoins 63,000.00 |
| `test_cash_page_ibkr_cash_is_nav_cash` | #144 | IBKR cash 4,306.69 (SGD base converted again as USD) vs NAV cash 3,211.52 |
| `test_card_account_balance_never_counts_as_cash` | #180 | misfiled card balance (3,100) adds to Cash page, allocation, geography |
| `test_platform_allocation_total_is_assets` | #144 | 98,973.74 vs 95,873.74 |
| `test_summary_geography_adds_up_to_assets` | #144 | 77,785.72 vs 95,873.74 (no crypto) |
| `test_geography_exposure_total_is_assets` | #144 | 93,884.06 vs 90,755.03 (Feb) |
| `test_first_of_month_dashboard_and_history_agree` | #143 (finding 1.10) | summary boundary 2026-04-01 vs History's newest 2026-03-01 |
| `test_flex_backfill_does_not_resource_older_history` | #140 | December 44,032.11 becomes 53,000.00 after a Flex backfill from 1 Dec |
| `test_history_after_an_fx_correction_equals_a_fresh_process` | untracked (new) | a corrected past FX rate marks History dirty, but `fx._CACHE` (24 h TTL) keeps the old rate, so the recompute settles the mark with the old value |

## Execution Journal (Codex Mutable)
- Current Stage: `pr`
- Workflow Status: `running`
- Provider/Model: `anthropic/claude-opus-5.5`
- Last Updated: `2026-11-04`

## Deterministic Gate Results (Codex Mutable)
- `lint`: `pass` — `make verify`
- `typecheck`: `pass` — `make verify`
- `tests`: `pass` — `make verify` (backend 687 passed, 1 skipped, 9 xfailed; frontend pass)
- `e2e`: `skip` — tests-only change
- `api-smoke`: `skip` — no API change
- `policy-checks`: `pass` — synthetic data only, no decisions.md edit

## Extra Files Changed (Codex Mutable)
- `Makefile` — reason: `golden-update` target (regenerate goldens in Docker with the golden dir mounted).
