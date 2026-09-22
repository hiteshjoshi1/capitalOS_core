# Issue 205: Per-deployment token key, optional signup switch, and per-user category rules

## Objective
- Stop signing login tokens with a value that is public in the source tree.
- Let an operator close the open signup endpoint.
- Stop category rules from being one global, world-editable table: users must not be able to read, change or deactivate each other's rules.

## Architecture Decisions
- `_jwt_secret()` no longer has a hardcoded fallback. Order: `AUTH_ACCESS_TOKEN_SECRET`, else a random key generated once and stored in `$DATA_DIR/.auth_secret` (mode 0600, created with `O_EXCL` so concurrent workers agree). If neither is possible it raises instead of issuing tokens. Zero-config local use keeps working; every deployment gets its own key.
- `AUTH_ALLOW_SIGNUP` (default `1`, so existing behaviour is unchanged): `0`/`false`/`no`/`off` makes `POST /auth/signup` return 403.
- Category rules get a nullable `user_id` (migration 069). `NULL` = shared system rule (the migration-seeded defaults): visible to and applied for everyone, changeable only by an admin (403 otherwise). A rule with `user_id = N` is visible, editable and applied only for user N's transactions. New rules created via the API are owned by the caller; another user's rule looks like a missing one (404); ownership cannot be changed through the API. Existing rows stay `NULL`, so nothing changes for current data.
- The categorization engine joins the transaction's account and only applies a rule when `r.user_id IS NULL OR r.user_id = account.user_id`.
- `category_overrides` needs no owner column: overrides are keyed by transaction and the endpoints already validate transaction ownership.
- No response shapes changed; the web app has no rule-editing UI, so no frontend change.

## Acceptance Criteria
- [x] A token signed with the old public default secret is rejected.
- [x] With no secret configured a per-deployment key is generated, is stable across restarts, is not the old default, and is mode 0600; if it cannot be stored the API fails closed.
- [x] `AUTH_ALLOW_SIGNUP=0` returns 403 and creates no user; unset/`1` keeps signup open.
- [x] Users see only shared rules plus their own; cannot update/delete each other's rules; non-admins cannot change shared rules; admins cannot touch another user's rules.
- [x] A user's rule categorizes only that user's transactions; shared rules still apply to everyone.
- [x] Migration 069 applies cleanly to an existing database and leaves all existing rules shared.

## How To Test
- `docker compose run --rm --no-deps api pytest tests/test_auth_secret_and_signup.py tests/test_category_rule_ownership.py` (or `make test-backend` for everything).
- `make db-migrate`, then `select count(*) filter (where user_id is null) from category_rules` equals the total.
- With a running API and `AUTH_ALLOW_SIGNUP=0`: `curl -X POST http://localhost:8000/auth/signup -H 'Content-Type: application/json' -d '{"username":"x","password":"y"}'` returns 403 (adjust the port if your API isn't on 8000).

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `manual`
- Workflow Status: `shipped`
- Provider/Model: `claude-code/claude-sonnet-5` (interactive session, not the orchestration graph)
- Last Updated: `2026-09-22`

## Deterministic Gate Results (Codex Mutable)
- `lint`: `pass` — `ruff check app tests`
- `typecheck`: `pass` — `mypy app` (95 files)
- `tests`: `pass` — backend suite exit 0 (439 passed, 8 skipped); new: `test_auth_secret_and_signup.py`, `test_category_rule_ownership.py`
- `e2e`: `skip` — not run
- `api-smoke`: `pass` — live checks: forged default-secret token 401, signup 403, non-admin PUT on a shared rule 403, rule rows unchanged
- `policy-checks`: `pass` — numbered migration 069 added (additive), no response fields removed
