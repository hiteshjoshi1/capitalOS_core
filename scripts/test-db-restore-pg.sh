#!/bin/bash
# Restore against a real, throwaway Postgres (#416): an older backup into a newer database.
# Synthetic migrations and data only, in its own container (pinned image, no published port,
# removed on exit); never a real stack. Run by `make db-restore-check` and the CI postgres job.
#   001 users        002 user_last_visit -> users (FK)        003 fails on purpose (failure case)
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
image=$(sed -n 's/^ *image: *\(postgres:[^ ]*@sha256:[0-9a-f]*\).*/\1/p' "$root/docker-compose.yml" | head -1)
[ -n "$image" ] || { echo "no pinned postgres image in docker-compose.yml" >&2; exit 2; }
name=capitalos-restore-check-$$
tmp=$(mktemp -d)
cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; rm -rf "$tmp"; }
trap cleanup EXIT
pass=0 fail=0
ok() { echo "ok   $*"; pass=$((pass + 1)); }
bad() { echo "FAIL $*"; fail=$((fail + 1)); }

docker run -d --name "$name" -e POSTGRES_USER=capitalos -e POSTGRES_PASSWORD=capitalos -e POSTGRES_DB=capitalos "$image" >/dev/null
for _ in $(seq 1 60); do docker exec "$name" pg_isready -U capitalos -d capitalos >/dev/null 2>&1 && break; sleep 1; done
# The image's entrypoint restarts the server once after init; wait for the final one.
sleep 2; for _ in $(seq 1 60); do docker exec "$name" psql -U capitalos -d capitalos -c 'SELECT 1' >/dev/null 2>&1 && break; sleep 1; done
sql() { docker exec -i "$name" psql -X -q -At -v ON_ERROR_STOP=1 -U capitalos -d "${2:-capitalos}" -c "$1" 2> >(grep -vi collation >&2); }

mig=$tmp/migrations; mkdir -p "$mig"
printf 'CREATE TABLE users (id integer PRIMARY KEY, name text NOT NULL);\n' >"$mig/001_users.sql"
printf 'CREATE TABLE user_last_visit (user_id integer PRIMARY KEY REFERENCES users (id), seen_at timestamptz);\n' >"$mig/002_last_visit.sql"
apply() { "$root/scripts/migration-sql.sh" "$@" | docker exec -i "$name" psql -X -q -1 -v ON_ERROR_STOP=1 -U capitalos -d capitalos >/dev/null; }
sql "CREATE TABLE IF NOT EXISTS schema_migrations (filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW());"

# The "old" backup: at 001, with data; the snapshot counts the way db-backup.sh writes them.
apply "$mig/001_users.sql"
sql "INSERT INTO users VALUES (1, 'hitesh'), (2, 'demo');"
dump=$tmp/capitalos_20261101_030000.dump
docker exec "$name" pg_dump -U capitalos -d capitalos -F c >"$dump"
printf 'schema_migrations|1\nusers|2\n' >"$dump.counts"

# The target moves on: 002 adds a table depending on users, and the data changes.
apply "$mig/002_last_visit.sql"
sql "INSERT INTO users VALUES (3, 'later'); INSERT INTO user_last_visit VALUES (1, now());"

restore() {  # [<migrations dir>]: db-backup.sh restore of the old dump into the target
  DB_CONTAINER=$name BACKUP_DATA_DIR=$tmp/data BACKUP_DIR=$tmp BACKUP_OFFSITE_DIR= BACKUP_AGE_RECIPIENT= \
    MIGRATIONS_DIR=${1:-$mig} "$root/scripts/db-backup.sh" restore "$dump" 2>&1
}
mkdir -p "$tmp/data"

# A newer migration that fails on the restored data: everything rolls back.
bad_mig=$tmp/migrations-bad; cp -R "$mig" "$bad_mig"; printf 'SELECT 1/0;\n' >"$bad_mig/003_fails.sql"
rc=0; out=$(restore "$bad_mig") || rc=$?
if [ "$rc" != 0 ] && [ "$(sql 'SELECT count(*) FROM users')" = 3 ] && [ "$(sql 'SELECT count(*) FROM user_last_visit')" = 1 ] &&
  [ "$(sql 'SELECT max(filename) FROM schema_migrations')" = 002_last_visit.sql ]; then
  ok "a newer migration failing on the restored data leaves the target exactly as it was"
else bad "failure leaves the target as it was (exit $rc): $out"; fi

# The old backup into the newer database: restored, then brought up to 002.
rc=0; out=$(restore) || rc=$?
if [ "$rc" = 0 ] && [ "$(sql "SELECT string_agg(name, ',' ORDER BY id) FROM users")" = "hitesh,demo" ] &&
  [ "$(sql "SELECT string_agg(filename, ',' ORDER BY filename) FROM schema_migrations")" = "001_users.sql,002_last_visit.sql" ] &&
  [ "$(sql 'SELECT count(*) FROM user_last_visit')" = 0 ] &&
  printf '%s' "$out" | grep -q '1 newer migration(s) applied (002_last_visit.sql)'; then
  ok "an older backup restores into a newer database and ends at the latest migration"
else bad "older backup into newer database (exit $rc): $out"; fi
if [ "$(sql "SELECT nspowner::regrole FROM pg_namespace WHERE nspname = 'public'")" = pg_database_owner ] &&
  [ "$(sql "SELECT has_schema_privilege('public', 'public', 'USAGE')")" = t ]; then
  ok "the public schema keeps its owner and its USAGE grant to PUBLIC"
else bad "schema owner/grants: $(sql "SELECT nspowner::regrole, nspacl FROM pg_namespace WHERE nspname = 'public'")"; fi

# The same backup again, now that the target is at its version's successor: still restores.
rc=0; out=$(restore) || rc=$?
[ "$rc" = 0 ] && [ "$(sql 'SELECT count(*) FROM users')" = 2 ] && ok "restoring again (target already migrated) works" ||
  bad "restore again (exit $rc): $out"

# A same-version backup: no migrations to apply.
docker exec "$name" pg_dump -U capitalos -d capitalos -F c >"$dump"
printf 'schema_migrations|2\nuser_last_visit|0\nusers|2\n' >"$dump.counts"
rc=0; out=$(restore) || rc=$?
if [ "$rc" = 0 ] && ! printf '%s' "$out" | grep -q 'newer migration' && [ "$(sql 'SELECT count(*) FROM schema_migrations')" = 2 ]; then
  ok "a same-version backup restores with no migrations"
else bad "same-version restore (exit $rc): $out"; fi

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
