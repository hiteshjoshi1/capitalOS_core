# Issue 125: User Identity And Username/Password Auth (Phase 1)

## Objective
- Implement user identity and username/password auth so CapitalOS data is user-scoped.
- Preserve existing financial data by adding ownership without orphaning records.
- Prepare schema for future Google auth linking without implementing full Google flow now.

## Architecture Decisions
- Decision 1: Use `accounts.user_id` as the canonical ownership anchor for finance data; scope `transactions`, `positions`, and `import_jobs` via account joins.
- Decision 2: Use signed JWT (`JWS`) short-lived access token + HttpOnly/Secure/SameSite refresh cookie with server-side refresh-session tracking.
- Decision 3: Seed a dedicated demo user for demo dataset only; do not use demo as owner of existing legacy data.
- Decision 4: One-time legacy ownership migration reassigns only `user_id IS NULL` rows to the signed-up personal user.
- Decision 5: Keep Google auth as phase-2-ready schema (`oauth_identities`) but out of implementation scope for this issue.

## Acceptance Criteria
- [x] New identity/auth tables exist: `users`, `user_credentials`, `auth_sessions`, `oauth_identities`.
- [x] `accounts.user_id` is added and indexed; all finance endpoints enforce user scoping.
- [x] Username/password endpoints implemented:
- [x] `POST /auth/signup`
- [x] `POST /auth/login`
- [x] `POST /auth/logout`
- [x] `GET /auth/me`
- [x] Refresh-session lifecycle is persisted and revocable via `auth_sessions`.
- [x] Demo user seed exists and remains isolated from personal data migration.
- [x] One-time legacy ownership migration script exists and updates only `user_id IS NULL` ownership rows for:
- [x] `accounts`
- [x] `crypto_wallets`
- [x] `crypto_user_networth`
- [ ] Post-migration constraint step exists to enforce mandatory ownership for new account-linked data (`accounts.user_id NOT NULL`).
- [ ] Frontend login/signup pages and route guards are implemented for phase 1.
- [x] Existing core flows still function under authenticated user context (dashboard/wealth/spending/ingest/crypto).
- [x] Tests cover auth flow, ownership scoping, and migration safety rules.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement backend schema/migrations
- [x] Implement backend auth APIs + auth dependency
- [x] Scope existing backend queries by current user
- [ ] Implement frontend login/signup + auth guard
- [x] Add migration/backfill tooling for legacy ownership reassignment
- [x] Add/update tests
- [x] Run verification commands

## Implementation Plan
1. Migration design (safe and staged)
- Add migration `032_users_auth.sql`:
- create `users`, `user_credentials`, `auth_sessions`, `oauth_identities`
- add nullable `accounts.user_id` + FK + index
- Add migration `033_seed_demo_user.sql`:
- create demo user + hashed password + optional seed linkage
- Add migration `034_crypto_ownership_alignment.sql` (if required by current schema state):
- ensure `crypto_wallets.user_id` / `crypto_user_networth.user_id` indexes for migration speed
- Add migration `035_enforce_account_user_not_null.sql`:
- run only after one-time ownership reassignment is complete
- set `accounts.user_id` to `NOT NULL`

2. One-time legacy ownership reassignment tool
- Add explicit command/script (idempotent, transactional) to reassign ownership to personal user:
- input: `target_user_id`
- updates only `WHERE user_id IS NULL`
- tables: `accounts`, `crypto_wallets`, `crypto_user_networth`
- Include dry-run mode and row-count preview.
- Include safety checks:
- fail if target user not found
- fail if target user is demo account (or require explicit override flag)

3. Backend auth implementation
- Add auth router and schemas:
- signup/login/logout/me
- Add password hashing/verification service:
- argon2id (preferred)
- Add token/session service:
- issue short-lived JWS access token
- issue/rotate refresh token in HttpOnly cookie
- persist refresh hash in `auth_sessions`
- Add `get_current_user()` dependency and apply to user-scoped endpoints.

4. Backend data access scoping
- Update routers/queries to enforce ownership joins:
- `dashboard`, `spending`, `ingest`, `accounts`, `crypto`, `alerts`, `dividends` where relevant
- Query pattern:
- join to `accounts` and filter by `accounts.user_id = :current_user_id`
- For crypto tables use direct `user_id` filter.

5. Frontend implementation
- Add `/login` and `/signup` routes/pages.
- Add auth client methods for signup/login/logout/me.
- Add app-level auth bootstrap (`/auth/me`) and guarded routes.
- Add user menu/logout affordance in shell.

6. Backward-compatibility rollout path
- Dev mode support:
- if no authenticated session, show login
- one-time migration command documented and executed after personal signup
- remove/disable temporary bypass once migration complete.

7. Test strategy
- Backend tests:
- signup/login/logout/me
- invalid credentials and rate-limit path
- token refresh/session rotation
- endpoint scoping (user A cannot see user B data)
- migration script safety (`NULL`-only reassignment, demo untouched)
- Frontend tests:
- login/signup render + submit behavior
- route guard redirects unauthenticated users
- authenticated navigation still renders existing pages

8. Verification commands
- `make db-migrate`
- `make test-backend`
- `make test-frontend`
- `make typecheck`
- `make lint`
- targeted smoke checks:
- `/auth/me` unauthorized before login
- signup/login success
- dashboard data visible only for authenticated user

## Planned Paths
- `migrations/032_users_auth.sql`
- `migrations/033_seed_demo_user.sql`
- `migrations/034_crypto_ownership_alignment.sql` (if needed)
- `migrations/035_enforce_account_user_not_null.sql`
- `api/app/models/user.py` (new)
- `api/app/models/auth_session.py` (new)
- `api/app/routers/auth.py` (new)
- `api/app/services/auth.py` (new)
- `api/app/schemas/auth.py` (new)
- `api/app/main.py` (router registration + middleware config updates)
- `api/app/routers/*` user-scope updates
- `web/src/routes/Login.tsx` (new)
- `web/src/routes/Signup.tsx` (new)
- `web/src/lib/api.ts` (auth methods)
- `web/src/main.tsx` (route guards/auth bootstrap)
- `web/src/context/AuthContext.tsx` (new)
- `api/tests/test_auth.py` (new)
- `api/tests/test_user_scoping.py` (new/updated)
- `web/src/__tests__/Auth*.test.tsx` (new/updated)

## Implementation Reasoning Addendum (Codex Mutable)
_Codex appends execution reasoning entries here._

## Verification Evidence (Codex Mutable)
- `make api-rebuild` (pass)
- `make test-backend` (pass, `147 passed`)
- `make db-migrate` (pass; includes new `032_users_auth.sql` + `033_seed_demo_user.sql`)

## Review Findings (Sonnet Primary, Opus Escalation)
_Review output is appended here._

## Human Rework Input (Mutable)
_Before running `task-rework`, add/update:_
- `### Review Cycle R<n> - Human Input` with a `text` block containing:
  `HUMAN_QUESTIONS: ...`
  `UNRESOLVED_COMMENTS: ...`
  `RESPONSE_REQUIREMENTS: ...`

## Retry Log (Max 3)
_Failed command/rework retries are appended here._

## Automation Log (Mutable)
_Automation appends structured logs here._
