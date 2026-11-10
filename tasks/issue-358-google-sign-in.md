# Issue 358: Sign in with Google

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/358

## Objective
- Hitesh signs in with his Google account instead of remembering a password (option A, chosen 2026-11-10).
- Nobody else gets in: one allow-list in `.env`; password sign-in stays as a break-glass.

## Architecture Decisions
- D-97: server-side OAuth 2.0 authorization code flow with PKCE (S256), state and nonce; ID token verified with
  PyJWT against Google's JWKS (no new dependency: PyJWT, cryptography and httpx are already locked).
- A signed, 10-minute, HttpOnly, SameSite=Lax flow cookie (per-instance name) carries state/nonce/verifier.
- Success creates the same auth_sessions row + Strict refresh cookie as a password login (30 days, renewed on use).
- The redirect URL is chosen from `GOOGLE_OAUTH_REDIRECT_URL` by the address the browser used (host and port);
  nginx now forwards `X-Forwarded-Host` (tailscale serve's, else the Host as sent).

## Acceptance Criteria
- [x] `/auth/google/start` → Google with PKCE/state/nonce; `/auth/google/callback` verifies and signs in.
- [x] Unknown or unverified email → 403 page; failures throttled like password sign-ins.
- [x] Unset config → no Google button, nothing else changes; `AUTH_PASSWORD_LOGIN=0` turns passwords off.
- [x] Login page: Google first, password form after; tests for both.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_google_sign_in.py` (Google mocked; real RS256 tokens).
- `cd web && npx vitest run src/__tests__/LoginGoogle.test.tsx`.
- With `.env` set up (CLAUDE.md "Google sign-in"): open the tailnet URL, Sign in with Google, land on /wealth.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [ ] Verify with a real Google client (needs Hitesh's OAuth client in `.env`)

## Execution Journal (Codex Mutable)
- Current Stage: `PR open`
- Workflow Status: `shipped`
- Checked through a real nginx (web/nginx/default.conf) and Vite: the right redirect URL per address, 400 on
  another port.
