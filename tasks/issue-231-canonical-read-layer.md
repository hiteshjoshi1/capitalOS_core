# Issue 231: Canonical read layer: one authority rule and one latest-per-account rule for every reader (#130 10.2)

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/231

## Objective
- Every page values an account from the same rows: which canonical fact rows count at an anchor is defined once, not per reader (#130 technical review, 10.2, findings 1.3/1.4/1.5).
- A refactor with no behaviour change: same rows, same order where a reader orders, golden files byte-identical.

## Measurement (main 3e2e26b, before this change)
#140 (authority windows) had already made `authority_status` the only rule for whether a row counts (`authoritative_sql`), with windows used only to route a legacy account to its Flex broker account; it also did #130 1.3 (one window per broker account/source/scope, logged moves, overlap check). #141 did 1.4 (uploads dated by the statement's as-of date). #207 added `accounts.closed_on` (`account_open_sql`) and dated card statements with a 45-day limit (D-52). What was left: each reader still wrote the predicates and its own "latest" query by hand, 23 authority predicates and 10 `MAX(date)` latest queries in `canonical_reads.py` alone, plus five readers elsewhere.

| Reader (where) | Used by | Authority | Latest per | Carry-forward | Closed | Flex routing | NAV rule |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `canonical_position_rows_by_legacy_account` (canonical_reads) | net worth, holdings, exposure, prices, dividends, account status | status | legacy account | unlimited | yes | yes | NAV accounts left out unless `include_nav_accounts` |
| `canonical_account_balance_rows`, upload part (canonical_reads) | cash, account status | status | account (all balance types) | unlimited | yes | account left out when Flex owns it | n/a |
| `canonical_account_balance_rows`, broker cash part | cash (NAV cash split) | status | broker account | unlimited | yes | yes | only accounts without upload rows |
| `latest_authoritative_nav_by_legacy_account` (ibkr_flex) | net worth, cash, holdings, exposure, account status | status | broker account | unlimited | yes | none | n/a. Scope written as `user_id = :u OR user_id IS NULL` |
| `canonical_snapshot_coverage_as_of` (canonical_reads) | as-of / freshness | status | MAX over accounts' newest | unlimited | yes | **none** | positions: NAV form with own positions; uploads exclude `credit_balance` |
| `get_data_completeness_status` (canonical_reads) | pages' completeness indicators | n/a (no column) | broker account + scope | unlimited | yes | n/a | n/a |
| card statement rows (valuation/facts) | card liability | status | card (in Python) | 45 days | yes | n/a | n/a |
| `_card_statement_dates` (valuation/account_status) | carried-forward flags | status | card (in SQL) | 45 days | yes | n/a | n/a |
| `unpriced_held_positions` (market_data/service) | Data Hub, quote job | status (literal) | broker account, at UTC today | unlimited | yes (literal) | none | none |
| `canonical_cash_rows_by_legacy_account`, `has_canonical_position_snapshot_sql` | nothing (dead code) | | | | | | |
| `parity_report` (CLI, Phase 6 legacy-vs-canonical diagnostic) | nobody's page | literal | broker account / account | unlimited | **no** | none | none |

## Architecture Decisions
- **D-56: one shared SQL builder**, `app/portfolio/effective_facts.py`, not Postgres views or functions: a view can't take the anchor, and SQL functions would exist only on Postgres while the default backend suite runs on SQLite. It defines once:
  - `counting_sql`: dated on or before the anchor (and not before a carry-forward floor), `authoritative`, the reader's account, open on the anchor.
  - `latest_per_account_sql` / `effective_rows_sql`: the newest counting row per owner key. `effective_rows_sql` uses one window (`MAX(date) OVER (PARTITION BY owner)`) over the counting rows, so each predicate is evaluated once (a join-to-MAX version measured slower on Postgres).
  - `flex_authority_accounts_cte`, `flex_routed_sql`, `not_flex_owned_sql` (Flex routing); `has_nav_sql`, `valued_by_nav_sql`, `nav_rule_sql` (NAV coverage); `CARD_STATEMENT_MAX_AGE_DAYS`.
  - `effective_positions_sql`, `effective_nav_sql`, `effective_uploaded_balances_sql`, `effective_broker_cash_sql`, `effective_card_statements_sql`, `effective_completeness_sql`.
- Readers became thin selects over these: positions, balances, coverage, completeness, NAV (moved to `canonical_reads`, still importable from `ibkr_flex`), the new `canonical_card_statement_rows` (used by both the card liability and the account status, which had their own copies), and market data's `held_position_rows`.
- **Owner key stays per fact** (positions: legacy account; NAV, broker cash: broker account; balances, card statements: account; completeness: broker account + scope). Unifying it is a behaviour change, left for a decision (below).
- **Parity first**: `tests/canonical_reads_reference.py` is a verbatim copy of the old readers; `tests/test_canonical_read_parity.py` compares every live reader to it over the golden household plus edge cases, both users, every day (SQLite) / every other day (Postgres) from 2025-12-01 to 2026-04-15. Committed and green against the old readers before any reader was switched.

## Kept differences (not changed; candidates for a later decision)
1. **Owner key.** Positions take the newest date across all broker accounts of a legacy account; NAV and broker cash count each broker account's newest. Only differs for a legacy account with two broker accounts holding authoritative facts that Flex routing doesn't separate. On a restored copy of the real data there are none, for positions, NAV or cash.
2. **Coverage date without Flex routing.** `canonical_snapshot_coverage_as_of` counts every account's facts, including uploaded balances of an account Flex owns. It's the MAX over all accounts, so this matters only when such a fact is the newest of all; on the real-data copy there are none.
3. **Held positions for pricing** use the newest snapshot per broker account, no routing, no NAV rule (deliberate: everything held needs a price), and "today" is the UTC date (a clock question, not this issue's).
4. `parity_report` (a Phase 6 diagnostic CLI) keeps its own SQL, without the closed-account rule; it values no page.
5. Crypto wallets have their own "newest snapshot per wallet" queries (5 copies in valuation/routers); a separate fact family, not in 10.2.
6. Writers (`upload_canonical`, `legacy_backfill`, `card_balance_backfill`, `ibkr_flex_rebuild`) still match `authority_status = 'authoritative'` literally for exact-key lookups; they are write-side checks, not readers.

## Intended behaviour changes
- NAV reader scope: before, `acc.user_id = :u OR acc.user_id IS NULL`, whatever `AUTH_ALLOW_LEGACY_NULL_OWNERSHIP` says; after, `account_scope_sql` like every other reader (the same with the flag on; without it, a NULL-owner account's NAV no longer reaches every user). `accounts.user_id` is NOT NULL in Postgres, so no stored row can differ; the parity test shows no difference.
- Card statement rows come back ordered by account and currency (before: no ORDER BY). Same rows; only the order of a multi-currency statement's sum could change, below the goldens' rounding.
- Removed dead code: `canonical_cash_rows_by_legacy_account`, `has_canonical_position_snapshot_sql` and its two SQL constants (no callers).

## Acceptance Criteria
- [x] One authority rule and one latest-per-account rule in the code; readers call it (`effective_facts`; the remaining hand-written copies are listed above, none in a page reader).
- [x] Parity test green on SQLite and Postgres; valuation golden files unchanged (byte-identical, no regeneration).
- [x] Parity on a restored copy of the real data (throwaway Postgres, database only): every reader check, every user, every day from August 2025 to November 2026: no mismatch.
- [ ] Hitesh: on the test instance, every page and History identical before and after.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_canonical_read_parity.py tests/test_valuation_golden.py`
- `make db-schema-check` (runs the parity test on Postgres 16).
- Full: `docker compose run --rm --build --no-deps api-dev pytest`, `make lint`, `make typecheck`.

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
- Parity test against the old readers (commit 1, before any switch): SQLite 3 scenarios green; Postgres 3 scenarios green.
- After the switch (2026-11-06): backend suite in Docker 898 passed, 25 skipped (Postgres-only); `make db-schema-check` pass (58 migrations, idempotent, schema matches, 24 Postgres tests incl. the 3 parity scenarios); `make lint` and `make typecheck` pass. `git diff main -- api/tests/golden`: empty.
- Reader timings (Postgres, golden household, per call, old vs new): positions 11.2 vs 8.9 ms, positions with NAV accounts 9.0 vs 6.6, balances 4.2 vs 3.5, completeness 2.1 vs 1.3, NAV 1.7 vs 1.3, others within noise. On the real-data copy every reader was the same or faster. Endpoint timings on a demo stack were not measured.

## Extra Files Changed (Codex Mutable)
- `api/tests/valuation_household.py`, `api/tests/canonical_test_helpers.py` — reason: the household now also builds on Postgres (seed rows cleared, UUID wallet ids, `RETURNING id`, a source_type Postgres accepts, portable booleans/upserts). Unchanged on SQLite: goldens byte-identical.
- `api/app/market_data/service.py` — reason: its held-positions query was one of the readers.

## Human Action Summary (Codex Mutable)
- Next expected action: review the PR, then batch it on the test instance and compare pages and History.
- Open questions:
  - Kept differences 1-3 above: unify the owner key (one rule for positions, NAV and cash) and route the coverage date? Each is a small behaviour change on edge data (none on today's real data); recommendation: yes, as one follow-up with its own before/after, so this PR stays a pure refactor.
