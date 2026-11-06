# Issue 242: Canonical reads: one "newest per broker account" rule, Flex-routed coverage date, app-clock today for pricing

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/242

## Objective
- Resolve the three differences #231 kept between readers on purpose (`tasks/issue-231-canonical-read-layer.md`, "Kept differences" 1-3), so every reader follows one rule.
- Expected: no change on today's real data. That has to be shown on a copy of the real data (test instance), and the read-only impact script below counts what would change.

## Architecture Decisions
- **D-62** (docs/decisions.md), refining D-56:
  1. **One owner key**: positions, NAV and broker cash each count their broker account's newest fact on or before the anchor (`effective_facts.BROKER_ACCOUNT_OWNER`; `POSITIONS_OWNER` is gone). NAV and broker cash already worked this way, so only positions change (`effective_positions_sql`). Every positions reader follows: net worth, holdings, exposure, prices, dividends, account status (all through `canonical_position_rows_by_legacy_account`).
  2. **Coverage date through Flex**: `canonical_snapshot_coverage_as_of` uses the value readers' routing. Positions and broker cash of a legacy account that Flex owns at the anchor come only from its Flex broker account (`flex_routed_sql`), and its uploaded balances don't count (`not_flex_owned_sql`). NAV stays unrouted, as in the NAV reader.
  3. **Held positions for pricing** (`unpriced_held_positions`: Data Hub's unpriced list, the quote job's partial check) take "today" from the app clock (`app.core.clock.app_today`: the request user's timezone, else `TZ`). Uploads are dated by the same clock (D-34). Quote and FX dates stay on market/UTC time (D-44): the quote job's `trade_date` is unchanged.
- **Parity**: `tests/canonical_reads_reference.py` keeps the old rules as defaults, and the new rules are opt-in arguments (`ref_positions(owner_key="broker_account")`, `ref_coverage(flex_routed=True)`). The parity checks compare the live readers with the new-rule reference. Old vs new is pinned per input (below).
- **Trade-off** (in D-62): the new owner key only adds rows, never drops them. The old rule kept the rows dated on the legacy account's newest date; the new rule keeps each broker account's newest. So a stale broker account next to a newer one under the same legacy account stays carried forward and is counted along with it. Example: a Phase 6 legacy backfill (`backfill_<id>`) next to an upload (`upload_<id>`), with no Flex window between them. The impact script lists every legacy account with 2+ broker accounts holding authoritative positions, and the days on which the readers differ.

## Which inputs give different outputs now
| Change | Input that differs | Before | After |
| --- | --- | --- | --- |
| 1. Owner key | A legacy account with two broker accounts that both hold authoritative position snapshots and that Flex routing doesn't separate (e.g. no Flex window, or both outside it), on a day when their newest dates differ | Only the rows on the newest date across both (the other broker account's holdings drop out) | Each broker account's newest rows (the older one is carried forward) |
| 2. Coverage date | A Flex-owned legacy account (Flex window covers the day, Flex fact on or before it) with an authoritative non-card uploaded balance, or positions/cash on a non-Flex broker account, **dated after every other counting fact of the user** | That fact's date | The newest date among the routed facts |
| 3. Held positions | A position snapshot dated *today* in the app timezone while the UTC date is still yesterday (00:00-08:00 in Singapore); or, west of UTC, dated the UTC date while local is still the day before | Left out until 08:00 SGT (or shown early, west of UTC) | Counted from local midnight |

Everything else is unchanged: same rows, same order. Parity on the golden household plus #231's edges, both users, every day from 2025-12-01 to 2026-04-15: old rules == new rules (`test_the_242_changes_leave_the_household_alone`).

Edge tests (`api/tests/test_canonical_read_parity.py`):
- `add_242_edges` part 1: a second broker account (`LEGACY_BACKFILL`) on the Sharekhan account with one snapshot on 2026-02-20. Both position readers differ for user A on every day from 2026-02-20. Before that day nothing differs.
- `add_242_edges` part 2: on the IBKR account (Flex-owned from February), an uploaded cash balance on 2026-04-10 and broker cash on its non-Flex broker account on 2026-04-12. The coverage date with cash differs for user A from 2026-04-10. Without cash, or NAV only, nothing differs.
- `test_the_242_changes_differ_from_the_old_rules_exactly_where_intended` asserts that set of (reader, user, day) pairs and nothing else, for all three golden scenarios, on SQLite every day and on Postgres every other day.
- `test_held_positions_for_pricing_use_the_app_clock`: at 2026-04-01 23:00 UTC (07:00 on 2 April in Singapore), a snapshot dated 2 April is in the unpriced list. The UTC date (1 April) doesn't see it, and neither does a user in New York at that instant (still 1 April there).
- Each test was checked by reverting its change: reverting the owner key, the coverage routing or the clock each makes the matching tests fail.

## Impact script (read-only, counts and ids only)
Run it against a restored copy of the real data, before or after this change (it computes both rules itself):

```
docker exec <api container> python -m app.scripts.canonical_rules_impact
docker exec <api container> python -m app.scripts.canonical_rules_impact --from 2025-08-01 --to 2026-11-06 --step 1 [--user-id N]
```

On the test instance the API container is the one `make test-instance-status` / `make where` names. The script needs this PR's code in the container (the test instance mounts the batch's code). It runs in one `READ ONLY` transaction, rolled back at the end, and prints:
1. Legacy accounts with 2+ broker accounts holding authoritative positions (ids). Then the (user, day) pairs where the positions reader differs, with and without NAV accounts' own positions, the legacy and broker account ids involved, and how many snapshot rows are now shown. "No longer shown" is always 0.
2. The (user, day) pairs where the coverage date differs, and the Flex-owned legacy accounts behind them.
3. Per user and for all users, on how many days the held list differs from the day before. On each such day the old UTC rule showed the previous day's list for the first hours of the local day. It also prints whether the list differs right now.

The expectation on the real data is 0 pairs for 1 and 2. A non-zero line names the account ids to look at. Tested on the synthetic household (`api/tests/test_canonical_rules_impact.py`): it finds exactly the edges above, its routed coverage equals the live reader every day, and the report contains no amounts or names.

## Acceptance Criteria
- [x] One owner key for positions, NAV and broker cash, in `effective_facts.py` (every reader follows).
- [x] Coverage date routed through Flex.
- [x] Held positions for pricing use the app clock's today.
- [x] Parity: old rules pinned where unchanged; an edge test per intended change; the inputs that differ are listed above.
- [x] Golden files byte-identical.
- [x] D-62 recorded; #231's kept-differences note points to it.
- [ ] Hitesh / coordinator: before/after on the test instance with a copy of the real data (every page, History), plus the impact script's output: expect no change.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_canonical_read_parity.py tests/test_canonical_rules_impact.py tests/test_valuation_golden.py`
- `make db-schema-check` (runs the parity test, including the old-vs-new pins, on Postgres 16).
- `make verify`.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `pr`
- Workflow Status: `shipped`
- Provider/Model: `claude-code/claude-opus-5-5`
- Last Updated: `2026-11-06`

## Deterministic Gate Results (Codex Mutable)
- Parity file (SQLite, Docker): all green: parity vs the new-rule reference, old-vs-new pinned sets (3 scenarios each), household unchanged (3), clock test, #231 edge reach test; Postgres scenarios skipped there and run by `make db-schema-check`.
- Each change reverted on its own (owner key, coverage routing, clock): the matching tests fail (6, 6 and 1 failures), so they test the change.
- `make db-schema-check`: pass (58 migrations, idempotent, schema matches; 24 Postgres tests incl. the 3 parity scenarios with the old-vs-new pins).
- `make verify`: pass: ruff `All checks passed!`, mypy `no issues found in 140 source files`, backend 936 passed / 25 skipped (Postgres-only), frontend 57 files / 454 tests.
- Goldens: `git diff main -- api/tests/golden` empty (byte-identical, no regeneration).

## Extra Files Changed (Codex Mutable)
- `api/app/scripts/canonical_rules_impact.py`, `api/tests/test_canonical_rules_impact.py`: the read-only impact script asked for in the task, and its test.

## Human Action Summary (Codex Mutable)
- Next expected action: batch on the test instance; run the impact script there; compare every page and History before/after.
- Open questions:
  - If the impact script ever reports a legacy account under change 1, should a stale backfill broker account be retired (its window closed, so its facts become reference) rather than carried forward? The script names the ids. Recommendation: decide only if it happens; the expected count on today's data is zero.
