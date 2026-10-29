# Issue 65: Test and dev instances share the real app's login cookie

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/65

## Objective
- Logging in on the test instance or a worktree's dev instance must not log you out of the real app, or the other way round.

## Architecture Decisions
- Cause: browsers scope cookies by host, not port. All instances run on `localhost` (or one Tailscale IP) and set the same `capitalos_refresh` cookie (path `/`), so they overwrite and clear each other's.
- Fix: `docker-compose.isolated.yml` sets `AUTH_REFRESH_COOKIE_NAME=capitalos_refresh_${ISO_NAME}` (the API already reads it). The real app keeps the default, so its existing logins stay valid. Rejected: a cookie `path` per instance (all instances serve the API at `/api` through Vite), and a different hostname per instance (needs DNS/hosts setup on every device).

## Acceptance Criteria
- [x] Each isolated instance's API uses its own cookie name (guard test, fails without the fix).
- [x] With a custom name the API sets, rotates and clears only its own cookie and ignores the default one (backend test).
- [ ] On the test instance, logging in there leaves the real app logged in, and the other way round.

## How To Test
- `make lint` (guard 14/14), `make test-backend`.
- Log in on http://localhost:5173 and http://localhost:5174 in the same browser, reload both: both stay logged in.

<!-- IMMUTABLE_PLAN_END -->
