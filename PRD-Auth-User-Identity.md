# PRD — User Identity, Login, and Signup (v1/v2)

## 0. Product Intent

Introduce real user identity into CapitalOS without losing existing data.  
Phase 1 delivers username/password signup + login (sufficient to create a dummy/local user account).  
Phase 2 adds Google OAuth signup/login.

Core constraint: **no orphaned data**. Existing accounts, transactions, positions, imports, and wallets must map cleanly to a user.

---

## 1. Goals

- Add first-class `users` identity model.
- Support signup/login via username + password first.
- Allow creation of local dummy users for testing.
- Scope user-visible data by authenticated user.
- Migrate existing dataset into a valid owner user.
- Add Google login later without breaking local credentials.

---

## 2. Non-Goals (Initial)

- Multi-tenant org/team model.
- Social features / account sharing.
- Passwordless auth.
- RBAC beyond basic user/admin flags.
- External identity provider abstraction beyond Google (initially).

---

## 3. Current-State Constraints (as of today)

- No `users` table exists.
- Most financial data is account-centric (`accounts -> transactions/positions/import_jobs`).
- Crypto tables already have optional `user_id` in some places (`crypto_wallets`, `crypto_user_networth`) but not enforced.
- APIs are effectively single-user/global.

Implication: identity must be introduced with careful backfill and query scoping.

---

## 4. User Stories

### Phase 1 (must-have)

1. As a user, I can sign up with username + password.
2. As a user, I can log in and receive a session/token.
3. As a user, I only see my own financial data.
4. As an operator upgrading existing DB, I can run migration and keep all prior data visible to the first owner user.
5. As a developer, I can create a dummy user quickly for local testing.

### Phase 2 (later)

1. As a user, I can sign up/login with Google.
2. As a user, I can link Google identity to an existing local account.

---

## 5. Functional Requirements

## 5.1 Username/password flow (Phase 1)

- `POST /auth/signup`
  - input: `username`, `password`, optional `display_name`.
  - validates username uniqueness.
  - hashes password with strong KDF (`argon2id` recommended, `bcrypt` acceptable).
- `POST /auth/login`
  - verifies credentials.
  - returns access token + refresh token (or secure session cookie strategy).
- `POST /auth/logout`
  - invalidates refresh/session.
- `GET /auth/me`
  - returns current user profile.

Dummy-user requirement:
- same signup endpoint supports dev/test dummy account creation.
- optional CLI helper command can wrap this.

## 5.2 Google login (Phase 2)

- `GET /auth/google/start`
- `GET /auth/google/callback`
- identity linking rules:
  - if Google email matches existing user with verified local account, allow explicit link.
  - no silent account merge.

## 5.3 Credential coexistence and account-linking behavior

- One `users.id` is the canonical identity and data owner.
- A user may have multiple auth methods attached to the same account:
  - local credentials (`user_credentials`)
  - Google identity (`oauth_identities`)
- Logging in with either method must resolve to the same `users.id` and same dataset.

Linking rules:
- Local-first user can link Google only while authenticated (explicit user action).
- Google-first user can set local username/password later from authenticated settings flow.
- If Google email matches an existing local account, system must not auto-merge.
- In match cases, require explicit proof-of-ownership before linking:
  - user logs in with local password, then confirms link.

Safety rules:
- Never infer account merge by email alone.
- Never create a second user if an existing linked identity exists for that provider subject.
- Audit-log link/unlink events with timestamp and user id.

---

## 6. Data Model Design

## 6.1 New tables

### `users`
- `id BIGSERIAL PK`
- `username TEXT UNIQUE NOT NULL`
- `display_name TEXT`
- `email TEXT NULL`
- `is_active BOOLEAN DEFAULT TRUE`
- `is_admin BOOLEAN DEFAULT FALSE`
- `created_at TIMESTAMPTZ`
- `updated_at TIMESTAMPTZ`

### `user_credentials`
- `user_id BIGINT PK/FK -> users(id) ON DELETE CASCADE`
- `password_hash TEXT NOT NULL`
- `password_algo TEXT NOT NULL` (e.g., `argon2id`)
- `password_updated_at TIMESTAMPTZ`

### `auth_sessions` (or refresh-token table)
- `id BIGSERIAL PK`
- `user_id BIGINT FK -> users(id) ON DELETE CASCADE`
- `refresh_token_hash TEXT NOT NULL`
- `expires_at TIMESTAMPTZ NOT NULL`
- `revoked_at TIMESTAMPTZ NULL`
- `created_at TIMESTAMPTZ`
- index on `user_id`, `expires_at`

### `oauth_identities` (phase 2-ready)
- `id BIGSERIAL PK`
- `user_id BIGINT FK -> users(id) ON DELETE CASCADE`
- `provider TEXT NOT NULL` (`google`)
- `provider_subject TEXT NOT NULL`
- `email TEXT`
- `created_at TIMESTAMPTZ`
- unique `(provider, provider_subject)`

## 6.2 Existing tables to scope by user

Primary ownership anchor:
- `accounts.user_id BIGINT FK -> users(id)`

Why anchor on accounts:
- `transactions`, `positions`, and `import_jobs` already reference `account_id`.
- User scoping can be enforced by joining through accounts.
- This column does not exist in initial schema and must be added in migration.

Crypto ownership:
- enforce/backfill `crypto_wallets.user_id` (already present but nullable).
- enforce/backfill `crypto_user_networth.user_id` where applicable.

Global shared tables remain unowned:
- `assets`, `prices`, `platforms`, `category_taxonomy`, `parser_registry` (reference data / market data).

---

## 7. High-Level Data Migration Plan (No Orphans)

## 7.1 Migration strategy

1. Create identity tables (`users`, `user_credentials`, `auth_sessions`, `oauth_identities`).
2. Add nullable `accounts.user_id`.
3. Seed a dedicated demo/dummy user and seed demo data for that user only.
4. User signs up with personal account (normal signup flow).
5. Run one-time legacy ownership migration:
   - move only legacy records where ownership is currently null
   - `UPDATE accounts SET user_id = <personal_user_id> WHERE user_id IS NULL`
   - `UPDATE crypto_wallets SET user_id = <personal_user_id> WHERE user_id IS NULL`
   - `UPDATE crypto_user_networth SET user_id = <personal_user_id> WHERE user_id IS NULL`
6. Keep demo account data untouched (already user-owned demo records must not be reassigned).
7. Make ownership constraints strict:
   - `accounts.user_id SET NOT NULL`
   - add indexes on `accounts(user_id)`, `crypto_wallets(user_id)`

Result:
- Existing transactions/positions/import jobs remain connected via `account_id`.
- No financial records become orphaned because their parent account remains and is now owned.
- Demo data stays isolated under demo user.

## 7.2 Guardrails

- Migration must fail fast if personal target user is missing and unowned accounts exist.
- Dry-run mode should report counts before applying backfill.
- Post-migration validation queries required (see section 12).
- Reassignment query must include `WHERE user_id IS NULL` to prevent accidental ownership overwrite.

---

## 8. API & Authorization Design

## 8.1 Auth dependency

- Add FastAPI dependency `get_current_user()`.
- All user-scoped endpoints require authenticated user.

## 8.2 Query scoping rules

Any query touching:
- `accounts`
- `transactions`
- `positions`
- `import_jobs`
- `credit_card_accounts`
- `category_overrides` (via transaction->account)

must constrain by current user, typically:
- `... JOIN accounts a ON ... WHERE a.user_id = :current_user_id`

Crypto endpoints:
- filter `crypto_wallets.user_id = :current_user_id`.

---

## 9. Frontend UX Requirements

### Phase 1
- New `/login` page:
  - username
  - password
  - submit
- New `/signup` page:
  - username
  - password
  - confirm password
- route guard:
  - unauthenticated users redirected to `/login`.
- user menu:
  - show current username
  - logout action

### Phase 2
- “Continue with Google” button on login/signup pages.

---

## 10. Security Requirements

- Password hashing:
  - `argon2id` (preferred) with tuned parameters.
- Token strategy:
  - signed JWT access token (`JWS`) with short TTL, stored in-memory on client.
  - refresh token in HttpOnly + Secure + SameSite cookie.
  - refresh token rotation and revocation via `auth_sessions`.
  - avoid JWE unless confidential token payload is a hard requirement.
- Never log plaintext passwords or raw tokens.
- Rate-limit login endpoint.
- Generic error message on auth failure (`invalid credentials`).
- Secure session handling:
  - prefer HttpOnly refresh cookie + short-lived access token.
- Token/session revocation support on logout.

---

## 11. Backward Compatibility

- Existing non-auth endpoints may remain in transition mode behind local dev flag temporarily, but production path must require auth.
- Existing data model relationships stay intact; only ownership layer is added.
- No destructive rewrites of transaction/position history.

---

## 12. Verification & Validation

Post-migration checks:

1. `SELECT COUNT(*) FROM accounts WHERE user_id IS NULL` = 0
2. Existing dashboard totals for personal user match pre-migration legacy totals.
3. `import_jobs` counts unchanged.
4. `transactions` counts unchanged.
5. Crypto wallet count unchanged and assigned to personal user (except demo-owned wallets).

Auth checks:

1. Signup creates user + credential row.
2. Login returns valid session/token.
3. `/auth/me` returns expected identity.
4. Unauthorized request to user-scoped endpoint returns 401.
5. User A cannot access User B accounts/data.

---

## 13. Rollout Plan

### Phase 1 (Username/password)

- schema migrations + demo-user seed + legacy ownership migration to personal user
- auth endpoints
- frontend login/signup
- query scoping updates
- regression tests for existing financial APIs under user scope

### Phase 2 (Google)

- oauth identity table usage
- Google OAuth flow + linking rules
- tests for provider login + account-link safety

---

## 14. Acceptance Criteria

- [ ] User can sign up/login with username/password.
- [ ] Existing legacy data is reassigned only to the signed-up personal account.
- [ ] Demo seeded data remains under demo user and is not reassigned.
- [ ] No orphaned account-linked records.
- [ ] All financial endpoints are correctly user-scoped.
- [ ] Dummy user creation works in local setup.
- [ ] Google flow is documented as phase 2 with schema ready.
- [ ] Same user can authenticate with local credentials and Google after explicit linking.
- [ ] No silent auto-merge occurs when Google email matches an existing local account.

---

## 15. Open Decisions

1. Username constraints:
   - allowed characters and minimum length.
