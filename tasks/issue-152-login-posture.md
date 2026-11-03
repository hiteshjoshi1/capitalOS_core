# Issue 152: Login posture: no seeded demo user on real installs, signup off by default, admin-only shared writes, login throttle

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/152

## Objective
- The demo login (published password) never works on a real install; it stays available on dev worktree stacks and test instances through an explicit make target.
- Signup is closed by default; failed sign-ins are throttled and don't reveal which usernames exist.
- Data every user sees (platforms, currencies, token allowlist, market-data refresh) is changed only by an admin.

## Architecture Decisions
- Migration 072 deactivates `demo`, revokes its open sessions and replaces its password hash with an invalid one (`!`), so re-activating the row by hand doesn't bring back the published password. Its data stays. Idempotent.
- `make demo-enable` (`scripts/demo-enable.sql`) re-activates `demo` with `Test@1234`; refused when the stack is the real-data project or its DB container is `capitalos-oss-postgres` (recipe-level check, in addition to the worktree guard). `make demo-disable` turns it off again. `make db-seed-demo` = demo-enable + demo data; `seed_dummy.sql` no longer flips `is_active` (data only). `scripts/test-instance.sh` runs `demo-enable` on the restored copy after its migrations.
- `AUTH_ALLOW_SIGNUP` defaults to off (only 1/true/yes/on open it). First accounts: `make user-create USERNAME=<name> ADMIN=1` (password prompted). `make user-grant-admin` / `user-revoke-admin`.
- Login throttle is in memory, per API process (one uvicorn process here): per-username (5) and per-IP (20) failures in a 15-min window; past the limit each further try waits 30s doubling up to 15 min, with 429 + Retry-After, before any password check. Success clears the username counter. A restart forgets counters: accepted for a single-process self-hosted app. The per-username lockout lets someone keep a known username locked for at most the cap.
- Client IP: the TCP peer; X-Forwarded-For (right-most entry) only when the peer is a trusted proxy (loopback + private ranges by default; `AUTH_TRUSTED_PROXIES`). The Vite proxy now sets `xfwd: true` so the API sees the browser's address instead of counting every proxied browser as one IP.
- Unknown or inactive usernames are checked against a lazily-made dummy hash so the timing matches a wrong password.
- `require_admin` dependency (403 "Admin only ...") on POST /currencies, POST /platforms, POST /crypto/allowlist, POST /market-data/refresh-now (the admin key, when configured, is still required on top). Reads stay open.

## Acceptance Criteria
- [x] Seeded demo login disabled by migration (072); make target re-enables it on non-real stacks only; test instance keeps it usable.
- [x] Signup off by default (documented, `.env.example`).
- [x] Per-username and per-IP throttle with backoff.
- [x] Dummy hash for unknown users.
- [x] Admin-only shared writes + make target to grant admin.
- [x] Tests for each; docs updated (CLAUDE.md, ReadMe.md, run skill, remote-dev doc).

## How To Test
- `make verify`.
- `docker run --rm --network none -v $PWD/migrations:/app/migrations:ro -v $PWD/scripts:/app/scripts:ro <api-dev image> pytest tests/test_login_posture.py` runs the migration/demo-enable SQL test too (the api-dev container has no `migrations/`, so `make verify` skips that one test).
- On a scratch Postgres: migrations 001-071, then 072 twice, `seed_dummy.sql`, `demo-enable.sql`, `demo-disable.sql`: demo inactive with no open sessions after 072, seeding doesn't re-enable it, enable/disable toggle it.

<!-- IMMUTABLE_PLAN_END -->

## Deterministic Gate Results (Codex Mutable)
- `lint`: pass (make verify)
- `typecheck`: pass (make verify)
- `tests`: pass. Backend 599 passed, 1 skipped (the SQL-file test, run separately with the mounts: passed); frontend 296 passed
- `policy-checks`: pass (check-pinned-refs via make lint)

## Human Action Summary (Codex Mutable)
- After deploy, on the real stack: `make user-grant-admin USERNAME=<owner>`: no migration makes anyone admin, so until then adding a platform/currency/allowlist token or refreshing market data returns 403.
- The `api-smoke` / `ingest-smoke` / `crypto-smoke` targets sign in as demo: on the real stack pass `SMOKE_USER`/`SMOKE_PASSWORD`.
