# Issue 143: Split dashboard.py into a valuation service (clock, fx, prices, state, facts, history)

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/143

## Objective
- Turn `api/app/routers/dashboard.py` (3,309 lines mixing clock, FX, price selection, loading, aggregation and HTTP) into a valuation service package with a thin router (#130 finding 10.1).
- One anchor rule in one timezone (#130 finding 1.10): Dashboard, History, its dirty marks and the Crypto page agree on when a month is completed.
- No output change except that deliberate fix, proven by the #142 goldens and invariants.

## Architecture Decisions
- Package `api/app/valuation/`: `clock`, `fx`, `prices`, `state`, `facts`, `holdings`, `exposure`, `history`, `pages` (bottom-up; each imports only the ones before it). The Data Hub card, which isn't valuation, goes to `app/services/data_hub.py`.
- The split is done in reviewable steps: a verbatim move by line range (only imports changed), then the thin router, then typing, then the clock fix, then Crypto/Dividends.
- Test patch points stay single: valuation modules call `fx.get_rates`, `clock._current_anchor_ts` and `prices._quote_age_days` through their module, so one `monkeypatch` reaches every caller. Tests now import and patch the new locations (assertions unchanged).
- Function names keep their leading underscore for now (the move stays reviewable); renaming to a public API is a follow-up.
- Completion rule: an anchor (date SNAPSHOT_DAY of the next month, carried as 00:00 UTC of that date) has passed once today in the app timezone is on or after its date. Anchor instants and data boundaries are unchanged, so only the 1st before 08:00 SGT moves.
- `fx.py` is not edited (#188 works there in parallel); `ingestion/runner.py`'s dead anchor copy is left for #190's area.

## Acceptance Criteria
- [x] Router under ~600 lines (198).
- [x] Crypto and Dividends use the same facts: Crypto uses `app.valuation.clock` (its copy of the anchor helpers is gone); the Dividends yield denominator is `app.valuation.prices._asset_market_values` (D-21 rule).
- [x] Goldens unchanged (`mid.json` byte-identical); `first.json` changes only for the 1.10 case, explained number by number in the PR.
- [x] The strict xfail for #143 passes; marker removed.
- [x] D-28 cache and D-29 dirty marks keep working (their tests pass; dirty marks use the same completion rule).

## How To Test
- `make verify` (lint, typecheck, backend and frontend tests).
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_valuation_golden.py tests/test_valuation_invariants.py tests/test_valuation_clock.py tests/test_valuation_cache.py`

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `lint`: pass — `make verify` (ruff: all checks passed; eslint; pinned refs, checkout guard, backup tests)
- `typecheck`: pass — mypy: no issues in 125 source files (the moved modules are not on the ignore list); tsc
- `tests`: pass — backend 769 passed, 1 skipped, 1 xfailed (the untracked FX-cache xfail, #188's area); frontend 315 passed
- `e2e`: skip — no UI change
- `api-smoke`: skip — no endpoint or field change
- `policy-checks`: pass — synthetic fixtures only

## Extra Files Changed (Codex Mutable)
- `api/app/core/clock.py` — reason: `app_now()`, the app-timezone "now" the valuation clock uses.
- `api/app/wealth_rollup_dirty.py` — reason: dirty marks use the same completion rule; imports History from its new home.
- `api/app/routers/spending.py`, `api/app/routers/crypto.py`, `api/app/routers/dividends.py` — reason: import from `app.valuation` instead of the router / their own copies.
- `api/tests/*` — reason: imports and patch targets moved with the code; new clock tests and a first-of-month invariant.

## Human Action Summary (Codex Mutable)
- Next expected action: review the PR (module map and golden explanation in its description).
- Open questions:
  - Quote ages (`prices._quote_age_days`) and FX dates (`app.fx`) still count days in UTC; moving them to the app day would change numbers every morning before 08:00 SGT, so it is left for a separate decision.
