# Issue 188: A corrected past FX rate never reaches History: the in-process FX cache keeps the old rate

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/188

## Objective
- A new or corrected FX rate for a past date shows up in History on the next read, without a restart or a manual cache clear.

## Architecture Decisions
- `fx._store_rows` drops the in-process per-date rate cache entries from the earliest changed date on (`fx.forget_rates_from`), for every base and currency, in the same path that marks History dirty (D-29). "From that date on, everything" is the exact set a stored row can change: a row for date D is what later dates resolve to (latest on or before, up to the stale window), and pairs are derived through shared bases.
- It drops once inside the write transaction (before the dirty mark) and again after commit, so a read that raced the commit cannot keep the old rate cached.
- Provider-call cache entries are kept (they record whether a provider was asked, not values).
- The valuation cache (D-28) needs nothing: every write already bumps it. The FX cache is separate.
- The change stays inside `api/app/fx.py` (dashboard is being refactored in parallel, #143).

## Acceptance Criteria
- [x] The #142 strict xfail `test_history_after_an_fx_correction_equals_a_fresh_process` passes; marker removed.
- [x] Test: a corrected past rate replaces the cached one on the next read (`test_a_corrected_past_rate_replaces_the_cached_one`), earlier dates keep their cache entries, an unchanged re-store drops nothing.
- [x] Goldens unchanged.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_fx.py tests/test_valuation_invariants.py tests/test_valuation_golden.py -q`
- `make verify`

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results
- `make verify`: pass. Backend 763 passed, 1 skipped, 1 xfailed (the unrelated #143 first-of-month xfail); frontend 315 passed.
- Without the fix the invariant test fails (checked by stashing the fix).

## Extra Files Changed
- none

## Human Action Summary
- Follow-up noticed, not fixed here: IBKR statement rates (`portfolio_fx_rates`, written by `app/portfolio/ibkr_flex.py`) are read by `fx` too; that write path does not call `fx.forget_rates_from`, so a corrected IBKR rate can sit behind the same cache. It can call the new helper once #143's refactor lands.
