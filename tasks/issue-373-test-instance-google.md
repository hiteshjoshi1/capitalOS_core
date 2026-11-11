# Issue #373: Google sign-in on the test instance

Okayed by Hitesh 2026-11-10; he registered both redirect URIs in the Google client.

## Change (D-104)
- `docker-compose.isolated.yml`: the API's `GOOGLE_OAUTH_REDIRECT_URL` comes from `ISO_GOOGLE_OAUTH_REDIRECT_URL`,
  empty by default, so worktree stacks (and anything with a linked main `.env`) never get the real app's callbacks.
- `scripts/test-instance.sh`: sets it to `https://<tailnet name>:8444/api/auth/google/callback,http://localhost:5174/...`;
  after the web is up runs `tailscale serve --bg --https=8444 http://127.0.0.1:5174`; `drop` runs
  `tailscale serve --https=8444 off`. :443 (InvestOS) and :8443 (real app) are refused as `TEST_TAILNET_PORT`.
  No Tailscale CLI → localhost only, with a note. `status` prints the HTTPS URL.
- CLAUDE.md updated.

## Checked
- `scripts/test-test-instance.sh`: redirect list with/without a tailnet name, tailnet name parsing, serve on/off
  calls (stub tailscale), :443/:8443 refused before reaching tailscale, the compose override present.
- Live, on this worktree's isolated stack with the main `.env` linked (as the test instance does) and the same
  override: `/auth/methods` says google=true at localhost:<web> and `<mac>:8444`, false at `<mac>:8443` and
  localhost:5173; through a real `tailscale serve --https=8444` → Vite → API, `/api/auth/google/start` redirected to
  Google with `redirect_uri=https://<mac>:8444/api/auth/google/callback`; then :8444 was turned off and :443/:8443
  were unchanged. Without the override the API had an empty redirect list (google=false).
- The full sign-in on the test instance itself is checked on the next batch.
