# CLAUDE.md

Operational quickstart for Claude Code in this repo. For principles, API-contract
rules, and coding standards, see `AGENTS.md`. For product vision, see `ReadMe.md`
and the `docs/PRD/` docs.

## Stack
Postgres 16 + FastAPI + React (Vite/TS), all in Docker via `docker-compose.yml`.

## Run
- `make up` — starts postgres + api (+ the **web container** in the main checkout, #263). With the local,
  git-ignored `docker-compose.oss-test.yml` present (this checkout) that is the **OSS stack** (postgres :5433 +
  api :8011, compose project `capitalos-oss-test`). The default-project stack (`capitalos`, API :8000) is not used in
  this checkout — don't start it. Without that file (fresh
  clone) it's the base stack on :5432 / :8000.
- **The main checkout stays on `main`** (it runs the real data; its API runs the code baked into the image at the
  last `make deploy`, without `--reload` (#155), while worktree and test-instance APIs mount the code and reload). Stack-changing targets refuse there on any other branch (#44). Do feature work in a
  worktree: `make worktree ISSUE=<n> SLUG=<slug>` → `../capitalOS-worktrees/issue-<n>-<slug>`,
  where `make up` / `web-up` / `db-migrate` run an **isolated** stack (own project, containers,
  ports and DB; `make where` prints them) and `make instance-drop` removes it. After a merge,
  `make worktree-prune` lists merged, clean worktrees and `APPLY=1` removes each with its containers,
  volumes, networks and images (#269; unmerged/dirty ones, main and the test instance are kept).
- Web (#263): in the main checkout the real app's UI is a **production build in the `web` container** (nginx,
  `127.0.0.1:5173`, proxies `/api/*` to the API). `make up` starts it in the background, Docker restarts it
  (`restart: unless-stopped`, main checkout only), `make deploy` rebuilds it; `make web-logs`. Worktrees and the
  test instance run the Vite dev server (`make web-up`, hot reload).
- Tailnet (#263): `make tailnet-serve` (once; Tailscale keeps it) serves the real app at
  `https://<mac>.<tailnet>.ts.net:8443` to your tailnet only (`tailscale serve`, never `funnel`).
  `make tailnet-serve-status` / `tailnet-serve-off`. InvestOS has port 443 of the same name.
- API: `http://localhost:8011` (health: `curl http://127.0.0.1:8011/health`). `web/.env.local` sets
  `VITE_API_BASE=/api` + `VITE_API_PORT=8011`: the browser talks only to the Vite server, which
  proxies `/api/*` to the API (works from other devices, where `localhost` would be that device).

## Network posture (dev)
- Postgres and the API are published on `127.0.0.1` only (`docker-compose*.yml`).
- Every service runs with `no-new-privileges`, `cap_drop: ALL` and a read-only root fs (tmpfs for
  scratch). All are non-root except `docker-socket-proxy`, the only container with the Docker socket:
  it exposes read-only container/event endpoints to Alloy on an internal network (`docker-api`).
  Loki/Grafana/Alloy sit on an `observability` network that can't reach Postgres.
- The web container publishes on `127.0.0.1` only: Docker Desktop hides client addresses from containers, so the
  tailnet reaches it through `tailscale serve`, never the LAN; nginx answers 421 to any Host but localhost or
  `*.ts.net` (DNS rebinding).
- Vite (worktrees/test instance) listens on all interfaces (`host: true`) but `web/vite.network.ts` drops any connection
  that isn't from localhost or Tailscale (100.64.0.0/10, fd7a:115c:a1e0::/48). `VITE_ALLOW_LAN=1`
  opens it to the local network. `*.ts.net` Host headers are allowed (`allowedHosts`).
- Demo login `demo` / `Test@1234`: **dev worktree stacks and test instances only** (#152). Migration
  072 turns it off everywhere; `make demo-enable` turns it back on (refused on the real-data stack;
  `make db-seed-demo` = demo-enable + demo data; `make test-instance` enables it on the copy).
  The dummy seed (`db-seed-dummy`, `db-seed-demo`) is refused there too, before any DB call (#221:
  it writes shared DUMMY prices). `make db-clear-dummy` removes it and marks History dirty.
- Accounts (#152): signup is off by default (`AUTH_ALLOW_SIGNUP=1` opens it). `make user-create
  USERNAME=<name> ADMIN=1` makes one; `make user-grant-admin` / `user-revoke-admin USERNAME=<name>`.
  Shared-data writes (platforms, currencies, token allowlist, market-data refresh) are admin-only (403).
  Failed sign-ins are throttled per username and per IP (429 + Retry-After; in memory, see `.env.example`).
- Google sign-in (#358, D-97): "Sign in with Google" on the login page once four `.env` settings are set (off
  otherwise; password sign-in stays as a break-glass, `AUTH_PASSWORD_LOGIN=0` turns it off). One-time setup in
  Google Cloud Console (console.cloud.google.com, any project): **Google Auth Platform → Branding** (app name),
  **Audience**: External, keep it in *Testing* and add your Gmail under Test users (no Google review needed);
  **Clients → Create client → Web application**, Authorized redirect URIs:
  `https://<mac>.<tailnet>.ts.net:8443/api/auth/google/callback` and `http://localhost:5173/api/auth/google/callback`.
  Put the client ID/secret in `.env` as `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`, the same URIs in
  `GOOGLE_OAUTH_REDIRECT_URL` (comma-separated), and `GOOGLE_ALLOWED_EMAILS=<gmail>=<username>`; then `make deploy`
  (or `make api-rebuild`). Sessions last 30 days and renew on use (`AUTH_REFRESH_TOKEN_TTL_DAYS`). Google is
  offered only at an address listed in `GOOGLE_OAUTH_REDIRECT_URL`. Worktree stacks never use it (empty there).
  The test instance has its own (#373): `https://<mac>.<tailnet>.ts.net:8444` (served by `tailscale serve`
  while it runs, removed by `test-instance-drop`) and `http://localhost:5174`, both registered in the Google client.
- Passwords: Settings → Change password (signs out your other sessions). Forgotten one:
  `make user-set-password USERNAME=<name>` prompts for a new one and signs out all its sessions (#72).
- `make down` / `make api-rebuild` / `make web-rebuild` / `make db-reset` (**deletes the DB
  volume**; now requires typing the project name — run `make db-backup` first).
- Backups (#41, #155): `make db-backup` dumps **and proves it restores** (scratch-DB restore with exact
  per-table counts from the dump's own snapshot), and archives `data/` (raw statements) as
  `capitalos_<ts>.data.tar.gz` next to the dump: every file a restored row records must be in it with
  its sha256, or the backup fails. It runs daily at `BACKUP_TIME` (`.env`, default 13:00, #387) via launchd
  (`make backup-schedule`; rerun it after changing the time; a Mac asleep then runs it on wake); `make backup-status` shows the newest verified backup and the
  schedule; `make backup-data-check` checks the live DB's files against `data/` (read-only).
  `make backup-prune` keeps every verified set of the last 14 days plus the first of each month for
  12 months (and the newest), dump and archive together, never the older unmarked dumps
  (`DRY_RUN=1` lists). Restore: `make db-restore BACKUP_FILE=<dump>` (database and `data/`; the
  current `data/` is moved to `data.pre-restore-<ts>/`). The database part is one transaction, committed
  only when every table's count matches the dump's snapshot; grants to a role the target lacks (e.g.
  `capitalos_mcp_ro` on a new stack: run `make db-create-mcp-role` after) are left out and named (#233).
  It starts from an empty `public` schema (owner and schema grants kept) and, in the same transaction,
  applies this checkout's migrations newer than the backup, so an older backup restores into a newer
  database (#416, D-116); any failure, a migration on the restored data included, changes nothing.
  `make db-restore-check` proves it against a throwaway Postgres (CI: postgres job).
- Encrypted, outside the repo (#356, D-95; one iCloud Drive folder, #383, D-105): the main checkout's `.env`
  sets `BACKUP_DIR` (`~/Library/Mobile Documents/com~apple~CloudDocs/CapitalOS_backups`, Keep Downloaded:
  the Mac's copy and the off-site one in one) and `BACKUP_AGE_RECIPIENT` (age public key); each set is made and
  verified in a private temp dir, then stored as `.age` files (dump, counts, data archive) with plain
  `.verified`/`.failed` markers. Verify/restore/the test instance decrypt with the private key
  `~/.capitalos/backup/age-identity.txt` (`BACKUP_AGE_IDENTITY`; a copy lives in Hitesh's password manager).
  `make backup-key-init` (once), `make backup-encrypt-existing` (dry run; `APPLY=1`) moves old plain sets
  over. `age` is pinned by sha256 in `scripts/age-tool.sh` (`make host-tools`). Worktrees, CI and the
  test instance (which links the main `.env`) keep `./backups`; there `BACKUP_DIR` from `.env` is ignored.
- Second copy (#357, D-96, optional; unset since #383): `BACKUP_OFFSITE_DIR` gets a copy of every verified
  encrypted set after each backup and the same retention; a missing/unwritable folder warns, never fails the
  backup. `make backup-offsite-check` / `backup-offsite-sync`. The daily job is `/bin/bash` under launchd,
  which macOS lets open/rename/delete files in iCloud Drive but not list the folder (and refused renames in
  personal folders): every backup folder keeps `.capitalos-index` (a new set is added, prune rewrites it;
  a pre-#383 `.capitalos-offsite-index` is adopted), read wherever listing is refused, rebuilt from a listing
  where it works. Don't grant `/bin/bash` Full Disk Access (too broad); keep backups out of personal folders.
- In the app (#399, D-111): after each backup, prune and `make backup-status`, the script writes
  `state/backup-status.json` (newest verified time, count, encrypted, icloud/local, daily time, UTC offset, last
  run ok; no paths or keys). Compose mounts `./state` read-only into the API: `GET /operations/backup-status`,
  Data Hub's "Last verified backup … · next … · iCloud Drive" line (amber after 2 days, red after 7 or a failed
  run) and a `backup_stale` Inbox item. `state/` is not `data/`, so it's never archived. Worktrees and the test
  instance have no status file: nothing shows. `scripts/test-db-backup.sh` writes its own temp status file.
- `/health` checks the database and reports `migrations.applied` vs `latest_file` (503 when the DB
  is down).

## Deploy (#46): installing merged main into the real app
- `make deploy` in the main checkout (on `main`, clean tree), **never a bare `git pull`**. It runs:
  a verified backup if new migrations come in, fast-forward, `make api-build`, `make db-migrate`,
  `make up` (+ observability if it's running), then health checks (API, and the web container's page + `/api` proxy). A failed migration is rolled
  back, the code reset to the previous commit, and the backup named.
- `make deploy-plan` (what would happen), `make deploy-status` (deployed commit, how far behind,
  last deploys from `deployments.log`). The web UI is rebuilt by the deploy (#263); nothing to restart.

## Test instance (#45): a batch of PRs, tested before main
From the main checkout:
- `make test-instance PRS="54 61"`: merges `main` + the PRs into `test/<date>` (worktree
  `../capitalOS-worktrees/test-instance`), runs `make verify`, takes a **fresh verified backup** of the
  real app and restores it there (counts checked; #287, `SKIP_BACKUP=1` reuses the newest; the banner
  and `make test-instance-status` show the copy's time and any newer real imports), applies the batch's migrations, and serves it with a red TEST
  banner: web **:5174** (also via Tailscale, and over HTTPS at `:8444` for Sign in with Google, #373), API :8021, Postgres :5434. Schedulers are off.
  It links the main checkout's `.env` (API keys, IBKR Flex) so refreshes work; a `DATABASE_URL` there is refused (#120).
- A conflict stops and is named: resolve and commit in that worktree, then `make test-instance-start`.
- `make test-instance-status`, then `make test-instance-pr` (one PR test/<date> → main, `Closes`
  every issue the batch closes, `Part of` the ones it only works on, #219), then `make test-instance-drop`.
  The TEST banner lists the same issues: per PR, what it closes, else its `Part of #N` / `Refs #N`,
  else the `(#N)` ending its title, else the PR itself (`scripts/test-test-instance.sh`).
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
  Then `make db-schema-update` and commit `migrations/schema.sql` with it (#154).
- Postgres check (#154, CI job `postgres`): `make db-schema-check` migrates an empty throwaway Postgres 16 (own
  container/port, removed after), re-runs the migrations (must be a no-op), diffs against `migrations/schema.sql`,
  then runs `pytest -m postgres` against it. Backend tests run with production-like auth: no bypass, no
  NULL-owner rows (the `client` fixture signs in with a real token; `tests/auth_helpers.py` for other users), and
  `tests/test_cross_user_isolation.py` checks every GET route as a second user.
- `make verify` runs frontend and backend lint + typecheck + backend/frontend tests.
- Full-stack smoke + screenshot diffs (#73, CI job `smoke`): `make e2e-smoke` runs a throwaway Postgres + API + web
  container on the demo seed and opens every page at 375/1440px in the pinned Playwright image; screenshots are
  compared with `web/tests/smoke/__screenshots__`. An intended visual change: `make e2e-smoke-update`, look at the
  PNGs, commit them. A page calling a new endpoint: `make e2e-smoke-record` (re-records the demo fixture), then update.
- Python dependency change: edit `api/requirements*.in` / `orchestration/requirements.in` (direct pins),
  then `make api-lock` / `make orch-lock` regenerates the hashed lock `requirements*.txt` the image and venv
  install with `--require-hashes` (#81). A transitive package under 14 days old fails the lock (and CI):
  hold it back with an older pin under `# Held back` in the `.in` file. Held-back pins are still age-checked
  (#94); a deliberate security exception needs a `D-1 exception` note on or right above the pin.
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
  response shapes (see `AGENTS.md` § API Contract Rules). They live per area in `web/src/lib/api/types/<area>.ts`,
  the calls in `web/src/lib/api/clients/<area>.ts`; pages import both from `web/src/lib/api` (the barrel, #368).

## Image supply chain (maintenance)
- Fast security fixes (D-18): `make image-fixes` reports, per pinned image, whether the newest release in its
  major line clears fixable HIGH/CRITICAL findings (CI runs it weekly and opens an issue). Such a release goes in
  at once, without the 14-day wait: `make verify-image`, bump the pin, test instance.
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
- Host runtimes (#91): CapitalOS's make targets use `.nvmrc`'s Node and a pinned CPython 3.13 in
  `~/.capitalos/python` (`make host-tools` installs both; `make where` shows which are in use). The
  machine-wide nvm default and Homebrew Python are shared with InvestOS: leave them alone.

## Remote dev (phone/away from the home machine)
See `docs/workflows/remote-dev.md` — `claude.ai/code` (web) for non-DB-dependent
work, or Tailscale+SSH+tmux into the home machine for anything needing the live
Postgres/containers.
