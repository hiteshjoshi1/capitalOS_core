#!/bin/bash
# Verified database backups (issue #41). Called by the Makefile:
#   db-backup.sh create            dump, then prove it restores (exact per-table row counts)
#   db-backup.sh verify <dump>     prove an existing dump restores
#   db-backup.sh prune [KEEP]      keep the newest KEEP verified backups (default 14)
#   db-backup.sh status            newest verified backup, counts, schedule
#
# A backup is `backups/capitalos_<ts>.dump` plus:
#   .counts    per-table row counts taken in the SAME snapshot pg_dump used, so the
#              comparison is exact even while schedulers write during the backup
#   .verified  written only after the dump restored into a scratch database and
#              every table's count matched; or .failed with the reason
# Dumps without markers (made before this tool) are never pruned.
#
# Env: DB_CONTAINER, DB_USER, DB_NAME (from the Makefile), BACKUP_DIR (default backups).
set -euo pipefail

cd "$(dirname "$0")/.."
DB_CONTAINER=${DB_CONTAINER:?DB_CONTAINER is required}
DB_USER=${DB_USER:-capitalos}
DB_NAME=${DB_NAME:-capitalos}
BACKUP_DIR=${BACKUP_DIR:-backups}

# Exact row count of every table in public, one "table|count" line each, sorted.
COUNTS_SQL="SELECT table_name || '|' || (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', table_schema, table_name), false, true, '')))[1]::text
FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name;"

# One cleanup for every exit path: the snapshot session, its temp dir, the scratch DB.
WORK="" SESSION_PID="" SCRATCH=""
cleanup() {
  exec 3>&- 2>/dev/null || true
  if [ -n "$SESSION_PID" ]; then wait "$SESSION_PID" 2>/dev/null || true; fi
  if [ -n "$WORK" ]; then rm -f "$WORK"/sql "$WORK"/session.out "$WORK"/session.err; rmdir "$WORK" 2>/dev/null || true; fi
  if [ -n "$SCRATCH" ]; then
    docker exec -i "$DB_CONTAINER" psql -X -q -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS $SCRATCH" >/dev/null 2>&1 || true
  fi
  return 0
}
trap cleanup EXIT

say() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
psql_db() { docker exec -i "$DB_CONTAINER" psql -X -q -At -v ON_ERROR_STOP=1 -U "$DB_USER" "$@" 2> >(grep -vi collation >&2); }

# Dump inside one REPEATABLE READ transaction whose snapshot pg_dump reuses, and take
# the counts in that same transaction.
create() {
  mkdir -p "$BACKUP_DIR"
  local ts out work fifo snapshot=""
  ts=$(date +%Y%m%d_%H%M%S)
  out="$BACKUP_DIR/capitalos_${ts}.dump"
  work=$(mktemp -d)
  WORK=$work
  fifo="$work/sql"
  mkfifo "$fifo"
  docker exec -i "$DB_CONTAINER" psql -X -q -At -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" \
    <"$fifo" >"$work/session.out" 2>"$work/session.err" &
  SESSION_PID=$!
  exec 3>"$fifo"
  printf "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\nSELECT 'SNAPSHOT=' || pg_export_snapshot();\n" >&3
  for _ in $(seq 1 100); do
    snapshot=$(sed -n 's/^SNAPSHOT=//p' "$work/session.out")
    [ -n "$snapshot" ] && break
    sleep 0.1
  done
  [ -n "$snapshot" ] || { say "FAILED: could not open a snapshot: $(cat "$work/session.err")" >&2; return 1; }
  printf '%s\n' "$COUNTS_SQL" >&3
  printf "SELECT 'COUNTS_DONE';\n" >&3

  say "Dumping $DB_NAME from $DB_CONTAINER (snapshot $snapshot)"
  if ! docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" -F c --snapshot="$snapshot" >"$out.part"; then
    rm -f "$out.part"; say "FAILED: pg_dump exited non-zero" >&2; return 1
  fi
  for _ in $(seq 1 600); do grep -q '^COUNTS_DONE$' "$work/session.out" && break; sleep 0.1; done
  grep -q '^COUNTS_DONE$' "$work/session.out" || { rm -f "$out.part"; say "FAILED: counts did not complete" >&2; return 1; }
  printf 'COMMIT;\n' >&3
  exec 3>&-
  wait "$SESSION_PID" 2>/dev/null || true
  SESSION_PID=""
  grep '|' "$work/session.out" >"$out.counts.part"
  mv "$out.part" "$out"
  mv "$out.counts.part" "$out.counts"
  say "Wrote $out ($(wc -c <"$out" | tr -d ' ') bytes, $(wc -l <"$out.counts" | tr -d ' ') tables)"
  verify "$out"
}

# Restore into a scratch database; compare counts when the backup has them.
verify() {
  local dump=${1:?verify needs a dump file} scratch restored
  [ -f "$dump" ] || { say "FAILED: no such file $dump" >&2; return 1; }
  scratch="capitalos_verify_$$"
  SCRATCH=$scratch
  psql_db -d postgres -c "CREATE DATABASE $scratch" >/dev/null
  if ! docker exec -i "$DB_CONTAINER" pg_restore -U "$DB_USER" -d "$scratch" --no-owner --no-acl --exit-on-error \
      <"$dump" 2>"$dump.restore.log"; then
    fail "$dump" "pg_restore failed: $(grep -vi collation "$dump.restore.log" | tail -1)"; return 1
  fi
  rm -f "$dump.restore.log"
  restored=$(printf '%s\n' "$COUNTS_SQL" | psql_db -d "$scratch")
  if [ -f "$dump.counts" ]; then
    if ! diff <(sort "$dump.counts") <(printf '%s\n' "$restored" | sort) >"$dump.diff"; then
      fail "$dump" "row counts differ after restore (see $dump.diff)"; return 1
    fi
    rm -f "$dump.diff"
    printf 'verified_at=%s\ntables=%s\nrows=%s\nmethod=restore+exact-counts\n' "$(date -u +%FT%TZ)" \
      "$(wc -l <"$dump.counts" | tr -d ' ')" "$(awk -F'|' '{s+=$2} END {print s+0}' "$dump.counts")" >"$dump.verified"
    rm -f "$dump.failed"
    say "VERIFIED $dump: restored, $(wc -l <"$dump.counts" | tr -d ' ') tables, $(awk -F'|' '{s+=$2} END {print s+0}' "$dump.counts") rows, counts identical"
  else
    # A dump from before this tool: it restores, but there are no snapshot counts to compare.
    printf 'checked_at=%s\ntables=%s\nmethod=restore-only\n' "$(date -u +%FT%TZ)" \
      "$(printf '%s\n' "$restored" | grep -c '|')" >"$dump.restorable"
    say "RESTORABLE $dump: restored $(printf '%s\n' "$restored" | grep -c '|') tables (no snapshot counts to compare; not a verified backup)"
  fi
}

fail() { printf 'failed_at=%s\nreason=%s\n' "$(date -u +%FT%TZ)" "$2" >"$1.failed"; rm -f "$1.verified"; say "FAILED $1: $2" >&2; }

verified_newest_first() { ls -1t "$BACKUP_DIR"/capitalos_*.dump.verified 2>/dev/null | sed 's/\.verified$//'; }

prune() {
  local keep=${1:-14} n=0 dump
  [ "$keep" -ge 1 ] 2>/dev/null || { say "KEEP must be at least 1" >&2; return 2; }
  while IFS= read -r dump; do
    n=$((n + 1))
    [ "$n" -le "$keep" ] && continue
    rm -f "$dump" "$dump.counts" "$dump.verified"
    say "Pruned $dump"
  done < <(verified_newest_first)
  # Failed backups are kept 7 days for diagnosis, then removed.
  find "$BACKUP_DIR" -maxdepth 1 -name 'capitalos_*.dump.failed' -mtime +7 2>/dev/null | while IFS= read -r f; do
    rm -f "${f%.failed}" "${f%.failed}.counts" "${f%.failed}.diff" "${f%.failed}.restore.log" "$f"
    say "Pruned failed ${f%.failed}"
  done
  say "Kept $(verified_newest_first | wc -l | tr -d ' ') verified backup(s); dumps without markers are never pruned"
}

status() {
  local newest
  newest=$(verified_newest_first | head -1)
  if [ -n "$newest" ]; then
    echo "Newest verified backup: $newest"
    sed 's/^/  /' "$newest.verified"
  else
    echo "Newest verified backup: none"
  fi
  echo "Verified backups kept: $(verified_newest_first | wc -l | tr -d ' ')"
  local failed
  failed=$(ls -1t "$BACKUP_DIR"/capitalos_*.dump.failed 2>/dev/null | head -1 || true)
  [ -n "$failed" ] && echo "Most recent failure: ${failed%.failed} ($(sed -n 's/^reason=//p' "$failed"))"
  return 0
}

case "${1:-}" in
  create) create ;;
  verify) verify "${2:-}" ;;
  prune) prune "${2:-14}" ;;
  status) status ;;
  *) echo "usage: $0 create|verify <dump>|prune [KEEP]|status" >&2; exit 2 ;;
esac
