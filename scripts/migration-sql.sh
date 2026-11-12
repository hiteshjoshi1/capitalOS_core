#!/bin/sh
# The SQL that applies one numbered migration (#46, #416): the file, then its schema_migrations
# row. `make db-migrate` runs it per file in its own transaction (psql -1); a restore (#416)
# appends it, for each migration newer than the backup, inside the restore's one transaction.
#   migration-sql.sh <migrations/NNN_*.sql>...
set -eu
for f in "$@"; do
  cat "$f"
  printf "\nINSERT INTO schema_migrations (filename) VALUES ('%s');\n" "$(basename "$f")"
done
