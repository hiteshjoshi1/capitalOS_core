# Issue 72: Change password in Settings, and a way back in when it's forgotten

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/72

## Objective
- Change your password from Settings.
- Get back in when it's forgotten, without hand-editing the database.

## Architecture Decisions
- `POST /auth/change-password` (current + new): a wrong current password is **400**, not 401, because the web app treats any 401 as "signed out".
- Every other refresh session is revoked (`revoke_reason = 'password_change'`); the caller's own (its refresh cookie) stays. Access tokens already issued live out their 15 minutes.
- Forgotten password: `make user-set-password USERNAME=` runs `app.scripts.set_password` in the API container, reading the password with `getpass` (never argv/history) and revoking all sessions (`password_reset`). Same helper (`services/passwords.py`) as the endpoint.

## Acceptance Criteria
- [x] Change keeps this session, signs out the others, old password stops working (backend test).
- [x] Wrong current → 400, same as current → 400, too short → 422, no login → 401 (backend test).
- [x] Reset script: mismatch changes nothing; success signs out every session; unknown user fails (backend test).
- [x] Settings card: success clears the form, mismatch/same caught before the API, API errors shown (frontend tests).
- [ ] Hitesh: change a password on the test instance and sign in with the new one.

## How To Test
- `make verify`.
- Test instance → Settings → Change password; then sign in elsewhere with the new one.

<!-- IMMUTABLE_PLAN_END -->
