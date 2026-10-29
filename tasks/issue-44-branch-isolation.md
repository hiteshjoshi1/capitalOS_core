# Issue 44: Branch isolation: real-data stack targets refuse to run outside the main checkout

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/44

## Objective
- Branch code can never run against, or change, the real-data stack. Each worktree gets an
  isolated stack of its own (the base #45's test instance builds on).

## Architecture Decisions
- **The real gap was the main checkout, not worktrees.** The real-data API bind-mounts the main
  checkout's `./api/app` with `--reload`, so any feature branch checked out there ran against the
  real data. That was the workflow until now. Fix: in the main checkout (with the real-data
  override), stack-changing targets (`up`, `api-rebuild`, `db-migrate`, `db-restore`, seeding,
  observability, …) refuse on any branch but `main`. `ALLOW_BRANCH=1` is the deliberate escape
  hatch. Read-only targets (`where`, `ps`, `logs`, `db-backup`) still work.
- **Worktrees are always isolated:** `docker-compose.isolated.yml` sets every container name and
  host port from `ISO_*` (stable per worktree, derived from its path; overridable). Named volumes
  are project-scoped, so each worktree has its own database. The Makefile passes `-p` / `-f`
  explicitly and blanks `COMPOSE_PROJECT_NAME` / `COMPOSE_FILE`, because the local `.env` sets
  both, and a `.env` copied into a worktree would otherwise point bare compose at the real stack.
  Parse-time checks refuse the real project, its containers and its ports even when overridden.
- Tooling (`lint`, `typecheck`, `test-backend`, `contract-backend`, `api-coverage`) runs `api-dev`
  with **`--no-deps`**: tests use SQLite, so they never start or recreate a Postgres container.
- `make worktree ISSUE=<n> SLUG=<slug>`, `make where`, worktree-aware `make web-up` (Vite on the
  worktree's port, proxying to its API), and `make instance-drop` (worktree only; deletes its volumes).
- *Not covered:* bare `docker compose` typed by hand in a worktree with a copied `.env`. Use `make`
  (CLAUDE.md says so).

## Acceptance Criteria
- [x] In a worktree, `make up` runs an isolated project and never touches `capitalos-oss-*`
      containers or volumes. Tested live with the real `.env` copied in: isolated API :8278 and
      Postgres :15278 healthy, worktree DB migrated (0 transactions) vs real (597), real
      containers unchanged.
- [x] Main checkout on `main`: unchanged. On a feature branch: guarded targets refuse.
- [x] `scripts/test-checkout-guard.sh` (13 cases, run by `make lint`, no Docker) passes.

## How To Test
- `make worktree ISSUE=99 SLUG=try`, then in it: `make where && make up && make api-url`, then `make instance-drop`.
- `scripts/test-checkout-guard.sh`

<!-- IMMUTABLE_PLAN_END -->
