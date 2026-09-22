# Issue 204: Restrict dev network exposure and allow trusted-network access

## Objective
- Let devices on a trusted private network (e.g. a tailnet) use the dev web app, addressed by IP or MagicDNS name.
- Stop exposing Postgres, the API and the dev server to every network the laptop joins.
- Make `make` targets follow the local compose override when one exists, instead of always using the default project.

## Architecture Decisions
- Vite keeps `host: true` (survives restarts, no CLI flag) but a small plugin (`web/vite.network.ts`) drops any TCP connection that isn't from localhost or Tailscale (`100.64.0.0/10`, `fd7a:115c:a1e0::/48`). `VITE_ALLOW_LAN=1` opts out.
- `server.allowedHosts: [".ts.net"]` — Vite 7 otherwise returns 403 for MagicDNS names. Never `true`.
- The browser talks only to the dev server: `VITE_API_BASE=/api` (in the git-ignored `web/.env.local`) plus a Vite proxy `/api/* -> http://127.0.0.1:${VITE_API_PORT}` (HTTP + WebSocket). The refresh cookie is `Path=/`, so it works through the proxy. This means the API needs no LAN/Tailscale exposure and CORS is not involved.
- `VITE_API_PORT` sets only the port of the derived API base (keeps the opened hostname) for setups that call the API directly.
- Postgres and API host ports are published on `127.0.0.1` only (base compose and the local OSS override).
- The Makefile layers the git-ignored `docker-compose.oss-test.yml` (compose project `capitalos-oss-test`, API :8001, Postgres :5433) when it exists, else falls back to the base stack (:8000 / :5432) so fresh clones are unaffected. `up` starts only postgres + api. The DB-reset target now requires typing the project name because it deletes the data volume.
- Realtime WebSocket URL is built by `buildRealtimeUrl`, which resolves a relative API base against the page URL.
- `make api-url` prints the API base for the current checkout so docs/skills never hardcode a port; `AGENTS.md`, `CLAUDE.md` and the `run` skill use it. `README.md` is intentionally unchanged (its `:8000` is correct for a fresh clone).
- `scripts/observability-smoke.sh` starts only the API in the Makefile's compose project (`API_COMPOSE`) and the observability services in the default project, so it no longer starts the default-project stack. Alloy already discovers containers by the `capitalos.*` compose-project label.

## Acceptance Criteria
- [x] A tailnet device can load the app, log in and use the data screens.
- [x] From the laptop's LAN address: dev server, API and Postgres connections are refused/dropped.
- [x] From the laptop's loopback and tailnet addresses: dev server works, `/api` proxy works incl. WebSocket (101).
- [x] Unknown `Host` headers still get 403.
- [x] Fresh-clone `make -n up` (no override file) targets the base stack.

## How To Test
- `cd web && npx vitest run src/__tests__/viteNetwork.test.ts src/__tests__/api.test.ts` — guard + URL builders.
- With `npm run dev` running: `curl -m3 http://<lan-ip>:5173/` must fail; `curl http://<tailscale-ip>:5173/api/health` must return `{"status":"ok"}`.
- `curl -m3 http://<lan-ip>:8001/` and `:5433` must be refused; `curl http://127.0.0.1:8001/health` works.
- From a tailnet device: `http://<tailscale-ip>:5173`, log in, open Stocks and Crypto.

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
- `lint`: `pass` — `npm run lint` in web/
- `typecheck`: `pass` — `npx tsc -b --pretty false`
- `tests`: `pass` — vitest 40 files / 268 tests (one unrelated Platforms test flaked once under load, passed on rerun and in isolation)
- `e2e`: `skip` — not run
- `api-smoke`: `skip` — replaced by manual proxy check: login, `/auth/me`, dashboard summary, stock holdings, crypto summary all 200; WebSocket upgrade 101
- `policy-checks`: `pass` — no migrations or API response shapes changed
