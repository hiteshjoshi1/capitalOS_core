# CLAUDE.md

Operational quickstart for Claude Code in this repo. For principles, API-contract
rules, and coding standards, see `AGENTS.md`. For product vision, see `ReadMe.md`
and the `docs/PRD/` docs.

## Stack
Postgres 16 + FastAPI + React (Vite/TS), all in Docker via `docker-compose.yml`.

## Run
- `make up` — starts postgres + api. With the local, git-ignored `docker-compose.oss-test.yml`
  present (this checkout) that is the **OSS stack** (postgres :5433 + api :8011, compose project
  `capitalos-oss-test`). The default-project stack (`capitalos`, API :8000) is not used in
  this checkout — don't start it. Without that file (fresh
  clone) it's the base stack on :5432 / :8000.
- **The main checkout stays on `main`** (it runs the real data, and its API reloads this checkout's
  code). Stack-changing targets refuse there on any other branch (#44). Do feature work in a
  worktree: `make worktree ISSUE=<n> SLUG=<slug>` → `../capitalOS-worktrees/issue-<n>-<slug>`,
  where `make up` / `web-up` / `db-migrate` run an **isolated** stack (own project, containers,
  ports and DB; `make where` prints them) and `make instance-drop` removes it.
- Web: `cd web && npm run dev` → `http://localhost:5173`.
- API: `http://localhost:8011` (health: `curl http://127.0.0.1:8011/health`). `web/.env.local` sets
  `VITE_API_BASE=/api` + `VITE_API_PORT=8011`: the browser talks only to the Vite server, which
  proxies `/api/*` to the API (works from other devices, where `localhost` would be that device).

## Network posture (dev)
- Postgres and the API are published on `127.0.0.1` only (`docker-compose*.yml`).
- Every service runs with `no-new-privileges`, `cap_drop: ALL` and a read-only root fs (tmpfs for
  scratch). All are non-root except `docker-socket-proxy`, the only container with the Docker socket:
  it exposes read-only container/event endpoints to Alloy on an internal network (`docker-api`).
  Loki/Grafana/Alloy sit on an `observability` network that can't reach Postgres.
- Vite listens on all interfaces (`host: true`) but `web/vite.network.ts` drops any connection
  that isn't from localhost or Tailscale (100.64.0.0/10, fd7a:115c:a1e0::/48). `VITE_ALLOW_LAN=1`
  opens it to the local network. `*.ts.net` Host headers are allowed (`allowedHosts`).
- Demo login: `demo` / `Test@1234`.
- Passwords: Settings → Change password (signs out your other sessions). Forgotten one:
  `make user-set-password USERNAME=<name>` prompts for a new one and signs out all its sessions (#72).
- `make down` / `make api-rebuild` / `make web-rebuild` / `make db-reset` (**deletes the DB
  volume**; now requires typing the project name — run `make db-backup` first).
- Backups (#41): `make db-backup` dumps **and proves it restores** (scratch-DB restore with exact
  per-table counts from the dump's own snapshot). It runs daily at 03:00 via launchd
  (`make backup-schedule`); `make backup-status` shows the newest verified backup and the
  schedule. `make backup-prune KEEP=14` only removes verified backups beyond the newest 14, never
  the older unmarked dumps. Restore: `make db-restore BACKUP_FILE=<dump>`.

## Deploy (#46): installing merged main into the real app
- `make deploy` in the main checkout (on `main`, clean tree), **never a bare `git pull`**. It runs:
  a verified backup if new migrations come in, fast-forward, `make api-build`, `make db-migrate`,
  `make up` (+ observability if it's running), then health checks. A failed migration is rolled
  back, the code reset to the previous commit, and the backup named.
- `make deploy-plan` (what would happen), `make deploy-status` (deployed commit, how far behind,
  last deploys from `deployments.log`). Restart `make web-up` when it says web deps changed.

## Test instance (#45): a batch of PRs, tested before main
From the main checkout:
- `make test-instance PRS="54 61"`: merges `main` + the PRs into `test/<date>` (worktree
  `../capitalOS-worktrees/test-instance`), runs `make verify`, restores the newest verified
  backup there (counts checked), applies the batch's migrations, and serves it with a red TEST
  banner: web **:5174** (also via Tailscale), API :8021, Postgres :5434. Schedulers are off.
- A conflict stops and is named: resolve and commit in that worktree, then `make test-instance-start`.
- `make test-instance-status`, then `make test-instance-pr` (one PR test/<date> → main, `Closes`
  every batch issue), then `make test-instance-drop`.
- Every worktree's `make web-up` shows an amber DEV banner the same way (`VITE_INSTANCE_LABEL`).
- Each dev/test instance has its own login cookie (`capitalos_refresh_<instance>`; the real app keeps
  `capitalos_refresh`). Browsers don't scope cookies by port, so a shared name logged each other out (#65).

## Verify (match to what changed)
- Backend code: `make api-rebuild` then `make test-backend` (runs **inside Docker**:
  `docker compose run --rm --build api-dev pytest`). For one file: `docker compose run --rm --build --no-deps api-dev pytest tests/test_X.py`
  (`--no-deps` so it doesn't start the default-project Postgres; tests use SQLite, no DB needed).
- Frontend code: `cd web && npx vitest run <file>` (fast) or `npm test -- --run` (full).
- New/changed migration: add `migrations/NNN_*.sql` (no `BEGIN`/`COMMIT` of its own), then `make db-migrate`
  (each file + its `schema_migrations` row in one transaction; stops at the first failure; already-applied files are skipped).
- `make verify` runs frontend and backend lint + typecheck + backend/frontend tests.
- Python dependency change: edit `api/requirements*.in` / `orchestration/requirements.in` (direct pins),
  then `make api-lock` / `make orch-lock` regenerates the hashed lock `requirements*.txt` the image and venv
  install with `--require-hashes` (#81). A transitive package under 14 days old fails the lock (and CI):
  hold it back with an older pin in the `.in` file.
- Dependency or image change: `make security-scan` (Trivy; fails on fixable HIGH/CRITICAL in the
  runtime API image, reports compose images). CI twin: `.github/workflows/security-scan.yml`.
- `/verify` and `/run` skills exist under `.claude/skills/` — prefer them over rediscovering this by hand.

## Known gaps (not regressions if you hit these)
- Postgres logs a "collation version mismatch" warning on every query — benign, ignore.
- The backend ruff/mypy baseline is intentionally permissive while the pre-existing
  warning backlog is addressed incrementally; both tools run and fail on configured checks.

## Session start
- `make status` (also printed by the SessionStart hook): board items in progress / waiting /
  for review, open PRs with CI, real-stack health, deployed vs origin/main, newest verified
  backup's age, worktrees and the test instance. Read-only, about 2s; degrades when offline.

## Conventions
- Work is tracked on the GitHub board ([CapitalOS backlog](https://github.com/users/hiteshjoshi1/projects/2)),
  one issue per unit of work; `scripts/board.sh list|add|move`. See `AGENTS.md` § Work Tracking.
- One `tasks/issue-<n>-<slug>.md` doc per issue, where `<n>` is the GitHub issue number (see `tasks/_template.md`).
- One feature branch + one PR per issue. **Never commit directly to `main`.**
- **Sprints are okayed and PRs merged only on Hitesh's word**; self-review before "done"; real
  choices go in `docs/decisions.md`. See `AGENTS.md` § Process Rules.
- Numbered, sequential `migrations/NNN_*.sql` — never edit an already-applied migration.
- Pin every image by `tag@sha256:` and every Action by commit SHA (`scripts/check-pinned-refs.sh`, run
  by `make lint`). Images used outside compose live in `tools/Dockerfile`. Dependabot bumps the pins.
- Never remove a field from an API response; only add. Keep TS types mirroring backend
  response shapes (see `AGENTS.md` § API Contract Rules).

## Image supply chain (maintenance)
- Before merging a Dependabot image bump: `make verify-image IMAGE=<new ref>` (signature or
  provenance per `scripts/verify-image.sh`; a repo without a policy fails on purpose).
- CVE triage: `make sbom` then `make sbom-find PKG=<name>` shows which images ship a package.
- Monthly: `make docker-prune` (dry run) then `APPLY=1`; only touches unused images of repos we pin.
- Docker Hub allows 100 anonymous manifest requests/hour/IP; `docker login` (free account) raises it.

## Postgres MCP (`capitalos-postgres`)
- Google MCP Toolbox (`--prebuilt postgres`, image pinned in `tools/Dockerfile`) via
  `scripts/mcp-postgres.sh`. It connects as `capitalos_mcp_ro`: read-only at the DB level, and no
  access to `user_credentials`/`auth_sessions`. Set it up once with `make db-create-mcp-role`
  (password in `.env` as `MCP_DB_PASSWORD`), and re-run it after rotating the password.

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
