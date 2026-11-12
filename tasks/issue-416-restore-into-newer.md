# Issue #416: an older backup restores into a newer database

## Problem
`db-backup.sh restore` ran `pg_restore --clean --if-exists` in one transaction. A backup from before migration 086 could not be restored into today's database: dropping `users` failed on `user_last_visit`'s foreign key (not in the dump), and the restore rolled back. Reproduced with the real 12 Nov 12:12 (pre-086) backup.

## Change (D-116)
- One transaction: keep the target's `public` schema owner and grants, drop and recreate the schema, restore the dump (no `--clean`), reset default grants, apply the dump's privileges, check the snapshot counts, then apply every newer migration from `migrations/` with the same SQL `make db-migrate` runs (`scripts/migration-sql.sh`, now shared), and COMMIT.
- Any failure, including a newer migration failing on the restored data, leaves the database as it was; `data/` is only swapped after the commit.
- Warnings: a backup from newer code (migrations this checkout lacks), or a dump without migration tracking (restored as is).
- Unchanged: `verify` (scratch database, no migrations) and the test instance (restores into an empty database, then `db-migrate`).

## Tests
- `scripts/test-db-backup.sh`: empty-schema start, same version (no migrations), older backup migrated after the counts check, failure leaves everything, newer-code warning, untracked dump.
- `scripts/test-db-restore-pg.sh` (`make db-restore-check`, CI postgres job): real throwaway Postgres; older backup into a newer FK schema ends at the latest migration; failing migration leaves the target exactly as it was; schema owner and PUBLIC usage kept; restoring again; same version.
- Real drill (worktree stack at 086): main's code fails on the pre-086 backup; the new code restores it, 086 applied, counts identical; with `capitalos_mcp_ro` present it regains schema usage and SELECT (also on the 086 table) and still can't read `user_credentials`.
