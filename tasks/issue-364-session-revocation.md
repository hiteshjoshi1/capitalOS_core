# Issue #364: sessions end on refresh-token replay; the live-updates socket follows the login

From #353 T7 (#130 §8.6).

## Change
- `POST /auth/refresh`: a token that was rotated more than `AUTH_REFRESH_GRACE_SECONDS` (30) ago and is used
  again ends every session of its user (`revoke_reason = 'replay'`, warning logged). Inside the window, the
  replay rotates the session that token was rotated into (`_active_successor`, matched by `created_at` =
  `revoked_at`), never another device's; if that line of sessions ended (logout), it's refused and nothing
  else changes.
- `/realtime/ws`: closes with 4401 when the access token expires, or (each heartbeat) when the user has no
  live session or is deactivated. `web/src/lib/realtime.ts`: on 4401 it refreshes, then reconnects; a
  refused refresh stops it.
- D-102.

## Tests
- `api/tests/test_session_replay.py`: replay outside the window (all sessions end, other device too),
  inside the window with two devices (the other device's session untouched), inside the window after
  sign-out, socket closed on ended sessions and on expiry. Three of them fail on the old code.
- `web/src/__tests__/realtime.test.ts`: 4401 → refresh → reconnect with the new token; refused refresh → stays down.
