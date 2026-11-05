# Migrations

`make db-migrate` applies every `NNN_*.sql` file here in name order that isn't yet recorded in
`schema_migrations`. Each file runs in **one transaction** together with its
`schema_migrations` row (`psql -1`); it stops at the first failure, and that file is rolled back
and not recorded. `migrations/schema.sql` is what all of them produce on an empty Postgres 16
(`make db-schema-check` proves it in CI; `make db-schema-update` rewrites it).

## Rules

`make lint` (and CI) runs `scripts/check-migrations.py`, which enforces the first three.

1. **No transaction control in a file**: no `BEGIN;`, `START TRANSACTION`, `COMMIT`, `ROLLBACK`
   or `END;` statement. The runner already wraps the file; an inner `COMMIT` would commit half a
   migration and record it separately. PL/pgSQL bodies (`DO $$ BEGIN ... END $$;`, functions)
   are fine.
2. **One file per number**: the next free number, three digits, never reused.
3. **Name**: `NNN_lower_snake_case.sql`.
4. **Never edit an applied migration.** Fix forward with a new file. Existing databases record
   the filename and won't run a changed file again, so an edit only changes fresh installs.
5. **Commit the regenerated `schema.sql`** with every new migration (`make db-schema-update`).
6. **Postgres-only behaviour gets a test** marked `@pytest.mark.postgres` (the default suite
   runs on SQLite, which doesn't enforce foreign keys or these CHECK constraints).
7. **A new CHECK constraint is added `NOT VALID`, then `VALIDATE CONSTRAINT`**, in the same file,
   as one `ALTER TABLE <t> ADD CONSTRAINT <name> CHECK (...) NOT VALID;` line (the precheck below
   reads that form). Before such a migration reaches a database with data, run
   `make db-constraint-check` there: read-only, it lists the rows each pending constraint would
   reject (`DB_CONTAINER=<name>` for another stack's database). A rejected row would make the
   migration fail and roll back.

## Allowed exceptions (applied before the lint existed; not edited)

- `028_crypto_base_asset.sql` has its own `BEGIN;` / `COMMIT;`. Under `psql -1` its `COMMIT`
  ends the runner's transaction early (its `schema_migrations` row is then written on its
  own). It is applied on every existing database.
- Two files share `028`: `028_crypto_base_asset.sql` and `028_fix_dbs_salary_type.sql`. Both are
  applied and recorded by filename, so both stay.

## Numbering gaps

These numbers have no file: **035-038, 040-054, 058, 066-067**. They were migrations of the
private deployment removed when the repository was open-sourced. Databases that existed before
that ran them, so a long-running database can differ from a fresh install (`schema.sql` is the
fresh install). Don't reuse those numbers: take the next number after the highest file.

## Allowed values (CHECK constraints, 079)

Enum-like TEXT columns carry CHECK constraints (079). The values come from the code that writes
them, and `api/tests/test_db_guardrails.py` fails when a code constant (a new upload adapter's
source kind, a new status) is missing from the constraint, so a new value needs a migration that
widens the constraint first. Columns that are already Postgres ENUM types (`accounts.account_type`,
`transactions.type`, `import_jobs.status`, `assets.asset_class`, `platforms.platform_type`) need no CHECK.

## ON DELETE (079)

Facts and raw documents point at their import run, facts at their raw document and canonical
rows at their legacy account with `ON DELETE RESTRICT`: deleting one of those while rows still
point at it fails. Delete the rows explicitly first (as `seed_dummy.sql` does), or better, keep
the run (removing an upload marks its run `removed`).
