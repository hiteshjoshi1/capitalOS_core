# Issue 46: make deploy: one command to install a merge

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/46

## Objective
- Installing merged `main` into the real-data app is one command that can't skip the backup or
  leave a half-migrated database. Adapted from InvestOS's A36d `make deploy`.

## Architecture Decisions
- `scripts/deploy.sh` via `make deploy [COMMIT=]`, main checkout on `main` only (guarded), in this order:
  1. **Refuses** a worktree, a branch other than main, uncommitted tracked changes, and a
     non-fast-forward.
  2. **Verified backup** (#41) when the range adds migrations.
  3. Fast-forwards.
  4. `make api-build` (the running API keeps serving).
  5. `make db-migrate`. On failure: `git reset --hard` to the previous commit (the tree was
     clean, so nothing is lost), the old API is untouched, and the backup is named.
  6. `make up`, `web-deps` if the lockfile changed, and observability if *this project's* is running.
  7. Health: API, Loki, Grafana.
  It appends to `deployments.log`. `make deploy-plan` / `deploy-status`.
- **Found while building it, and fixed:**
  - **`db-migrate` recorded failed migrations as applied.** Each file and its `schema_migrations`
    insert ran as separate commands joined by `;` inside the shell loop, so a failure carried
    on, recorded the file, and left partial DDL. Now each file plus its row runs in **one
    transaction** (`psql -1`), stopping at the first failure. (Migration 028's own
    BEGIN/COMMIT still applies on fresh DBs, with warnings; new migrations must not have them.)
  - **`db-wait` could pass during first-start initdb.** The entrypoint's temporary server is
    socket-only and then shuts down; the check is now over TCP (`pg_isready -h 127.0.0.1`), and
    the test instance's wait uses the same.
  - Observability detection is per compose project (`make observability-running`), not
    "a container named capitalos-loki exists", which matched the real stack from any other project.
- *Rejected:* restoring the backup automatically when a migration fails. Each migration is
  transactional, so the DB is already as it was; a restore would need the app stopped and could
  lose writes made since the backup.

## Acceptance Criteria
- [x] Sandbox (a disposable main checkout with its own origin, project `capitalos-deploytest`, ports 8044/5444; the real stack's container IDs were unchanged):
  - Deploy with migration 900: verified backup, fast-forward, build, migrated (row present),
    stack up, health OK, logged `result=ok`.
  - Deploy with failing migration 901: backup, rolled back (table absent, not recorded), code
    reset to the previous commit, same API container still serving, logged `failed`.
  - No-op ("Already at …"), dirty tree and non-main branch are refused with clear messages.
- [x] `deploy-plan` for the real commit that added migration 069 says "backup: yes".
- [x] Fresh DB: `up` then `db-migrate` with no initdb race; 48/48 recorded. A failing migration
      rolls back fully.

## How To Test
- `make deploy-plan`, then `make deploy`, then `make deploy-status`.

<!-- IMMUTABLE_PLAN_END -->
