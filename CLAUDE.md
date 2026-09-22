# CLAUDE.md

Operational quickstart for Claude Code in this repo. For principles, API-contract
rules, and coding standards, see `AGENTS.md`. For product vision, see `ReadMe.md`
and the `docs/PRD/` docs.

## Stack
Postgres 16 + FastAPI + React (Vite/TS), all in Docker via `docker-compose.yml`.

## Run
- `make up` — starts postgres + api. With the local, git-ignored `docker-compose.oss-test.yml`
  present (this checkout) that is the **OSS stack** (postgres :5433 + api :8001, compose project
  `capitalos-oss-test`): the real-data stack (holds `hitesh`). The old default-project stack
  (`capitalos`, API :8000, demo-only DB) is retired — don't start it. Without that file (fresh
  clone) it's the base stack on :5432 / :8000.
- Web: `cd web && npm run dev` → `http://localhost:5173`.
- API: `http://localhost:8001` (health: `curl http://127.0.0.1:8001/health`). `web/.env.local` sets
  `VITE_API_BASE=/api` + `VITE_API_PORT=8001`: the browser talks only to the Vite server, which
  proxies `/api/*` to the API (works from a phone, where `localhost` would be the phone).

## Network posture (dev)
- Postgres and the API are published on `127.0.0.1` only (`docker-compose*.yml`).
- Vite listens on all interfaces (`host: true`) but `web/vite.network.ts` drops any connection
  that isn't from localhost or Tailscale (100.64.0.0/10, fd7a:115c:a1e0::/48). `VITE_ALLOW_LAN=1`
  opens it to the local network. `*.ts.net` Host headers are allowed (`allowedHosts`).
- Phone over Tailscale: `http://<tailscale-ip>:5173` (`tailscale ip -4`). Nothing else is exposed.
- Demo login: `demo` / `Test@1234`.
- `make down` / `make api-rebuild` / `make web-rebuild` / `make db-reset` (**deletes the real DB
  volume**; now requires typing the project name — run `make db-backup` first).

## Verify (match to what changed)
- Backend code: `make api-rebuild` then `make test-backend` (runs **inside Docker**:
  `docker compose run --rm api pytest`). For one file: `docker compose run --rm --no-deps api pytest tests/test_X.py`
  (`--no-deps` so it doesn't start the retired default-project Postgres; tests use SQLite, no DB needed).
- Frontend code: `cd web && npx vitest run <file>` (fast) or `npm test -- --run` (full).
- New/changed migration: add `migrations/NNN_*.sql`, then `make db-migrate`
  (tracked in `schema_migrations`; safe to re-run, already-applied files are skipped).
- `make verify` runs frontend and backend lint + typecheck + backend/frontend tests.
- `/verify` and `/run` skills exist under `.claude/skills/` — prefer them over rediscovering this by hand.

## Known gaps (not regressions if you hit these)
- Postgres logs a "collation version mismatch" warning on every query — benign, ignore.
- The backend ruff/mypy baseline is intentionally permissive while the pre-existing
  warning backlog is addressed incrementally; both tools run and fail on configured checks.

## Conventions
- One `tasks/issue-NNN-<slug>.md` doc per unit of work (see `tasks/_template.md`).
- One feature branch + one PR per issue. **Never commit directly to `main`.**
- Numbered, sequential `migrations/NNN_*.sql` — never edit an already-applied migration.
- Never remove a field from an API response; only add. Keep TS types mirroring backend
  response shapes (see `AGENTS.md` § API Contract Rules).

## Headless browser QA (screenshots)
Playwright works. With `web/.env.local` → `VITE_API_BASE=/api` (this checkout) everything is
same-origin through the Vite proxy and no special flags are needed. If the web app calls the API
directly instead, the dev server (5173) and API are different origins and the api container
doesn't set permissive CORS for arbitrary tooling — then launch Chromium with
`--disable-web-security --disable-site-isolation-trials` for local screenshot/QA scripts
only (never ship this flag anywhere real).

## Config facts
- `SNAPSHOT_DAY=1` (env var, see `.env`) — controls the monthly snapshot anchor day.
- Node 22, Python 3.12 (inside container only).

## Remote dev (phone/away from the home machine)
See `docs/workflows/remote-dev.md` — `claude.ai/code` (web) for non-DB-dependent
work, or Tailscale+SSH+tmux into the home machine for anything needing the live
Postgres/containers.
