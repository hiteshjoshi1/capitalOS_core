# Issue 153: Guard AUTH_BYPASS_USER_ID; scope shared endpoints to the caller; validate parser registration

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/153

## Objective
- The login bypass can't be switched on by accident: it needs an explicit test flag, otherwise the API refuses to start.
- `/market-data/status` (and the refresh-now diagnostics), the Data Hub market counts and `/platforms/options` only show the caller's own data.
- Parser registration accepts only known parser keys, is admin-only, and an admin can correct an existing mapping.

## Architecture Decisions
- Bypass needs `AUTH_BYPASS_ALLOW=test` next to `AUTH_BYPASS_USER_ID`. Without it (or with a non-integer id) `check_auth_bypass_config()` raises `AuthBypassConfigError` when `app.main` is imported (and again in the lifespan, after logging is configured), so uvicorn won't start. When active it logs `AUTH BYPASS ACTIVE` at WARNING. At request time a bypass without the flag is ignored (normal login applies).
- "Held" = an asset in a `positions` row, a canonical `portfolio_position_snapshots` row (via `broker_instruments.asset_id`) or a `transactions` row of one of the caller's accounts (`account_scope_sql`). Held-ever, not held-now: diagnostics for a stock you just sold are still yours.
- Market-data status: admins see every symbol; others see their held symbols, summary recounted. Run-level fields (`latest_run`, `/market-data/runs`) are unchanged (counts only, no tickers).
- Data Hub market counts are always the caller's own, admin included: the card is a per-user summary.
- `/platforms/options` countries: platforms + the caller's own accounts, same as `/accounts/options`.
- Registration: 403 for non-admins, 400 for a key not in `PARSER_REGISTRY`, `register_signature(..., replace=True)` corrects an existing mapping. The library function still accepts any key (tests seed unknown keys on purpose); the check is at the API boundary.

## Acceptance Criteria
- [x] Bypass refuses to start without the test flag; warns when active (tests).
- [x] User B does not see user A's tickers in `/market-data/status`, refresh-now diagnostics or Data Hub counts; admin sees all on status (tests).
- [x] `/platforms/options` countries only from the caller's accounts (test).
- [x] Unknown parser key 400, non-admin 403, admin can correct a mapping (tests).

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_issue_153_auth_bypass_and_scoping.py -q` → 15 passed.
- `make verify` → passes.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `lint`: `pass` — `make verify`
- `typecheck`: `pass` — `make verify`
- `tests`: `pass` — backend 595 passed, frontend 296 passed (`make verify`)
- `e2e`: `skip` — no UI change
- `api-smoke`: `skip`
- `policy-checks`: `pass`

## Extra Files Changed (Codex Mutable)
- `api/tests/conftest.py` — reason: sets `AUTH_BYPASS_ALLOW=test` so the suite's bypass keeps working.

## Human Action Summary (Codex Mutable)
- Next expected action: confirm the real `.env` / compose environment has no `AUTH_BYPASS_USER_ID` (the API would now refuse to start), and that the owner's user is an admin (registering a file format is now admin-only; #152 adds the grant-admin target).
