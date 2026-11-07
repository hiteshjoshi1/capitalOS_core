# Issue 263: Real app's web UI as a production build in a container

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/263

## Objective
- The real app's UI runs in the background (no terminal), comes back after a Docker or machine restart, and
  always matches the deployed commit.
- Only Hitesh's devices reach it: localhost, and the tailnet through one stable HTTPS URL that works the same on
  the laptop and the phone.

## Architecture Decisions
- `web/Dockerfile`: node build stage (`npm ci --ignore-scripts` from the lock, `.npmrc` for D-15), then
  nginx-unprivileged serving `dist/` and proxying `/api/*` to `api:8000` (prefix stripped, websocket, XFF).
  `apk upgrade` + no curl in the runtime (Trivy: 0 fixable HIGH/CRITICAL). Read-only, no caps, uid 101.
- Compose `web` service, `127.0.0.1:5173` only. Docker Desktop shows every client as 192.168.65.1 (tested), so
  access control is the loopback binding plus `tailscale serve` (`make tailnet-serve`, HTTPS port 8443 on the
  Mac's tailnet name; InvestOS keeps 443). nginx refuses Hosts other than localhost / `*.ts.net` (421).
- nginx resolves `api` per request (Docker DNS, valid=10s) so a recreated API (new IP) is followed.
- Main checkout only: `CORE_SERVICES` gains `web`, `CAPITALOS_RESTART=unless-stopped` (hardening anchor's
  `restart:`), `make web-up` = the container, `make web-build` / `web-rebuild` / `web-logs`. Worktrees and the
  test instance keep Vite and `restart: "no"`.
- `make deploy`: builds api + web, health-checks the page and `/api/health` through the proxy.
- D-71 in `docs/decisions.md`.

## Acceptance Criteria
- [x] Image builds; container runs read-only, no caps, non-root.
- [x] Page, deep link (SPA fallback), hashed assets cached, index not cached, security headers.
- [x] `/api/health`, login (refresh cookie) and the websocket upgrade go through the proxy.
- [x] Unknown Host → 421; `*.ts.net` Host → 200.
- [x] API container restarted with a new IP: the proxy follows it.
- [x] Trivy: 0 fixable HIGH/CRITICAL (`make security-scan`, CI `web-image`).
- [ ] After merge: `make deploy`, then `make tailnet-serve`; check from the phone.

## How To Test
- Worktree: `docker build -t capitalos-web:test web`, run it on the worktree's network with
  `--read-only --tmpfs /tmp --cap-drop ALL -p 127.0.0.1:5998:8080`, then curl `/`, `/wealth/history`,
  `/api/health`, and `-H 'Host: evil.example.com'` (421).
- Main checkout after merge: `make deploy` (prints `Web: ok`), `make tailnet-serve`, open
  `https://hiteshs-macbook-pro.tailb99000.ts.net:8443` on the phone.

<!-- IMMUTABLE_PLAN_END -->
