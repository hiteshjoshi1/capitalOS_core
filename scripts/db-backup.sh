#!/bin/bash
# Verified backups (#41, #155). Called by the Makefile:
#   db-backup.sh create            dump + data/ archive, then prove both restore
#   db-backup.sh verify <dump>     prove an existing backup set restores
#   db-backup.sh restore <dump>    restore the database and data/ (the Makefile asks first)
#   db-backup.sh check-data        check the live database's recorded files against data/
#   db-backup.sh prune             retention: every verified set from the last KEEP_DAYS (14)
#                                  days, plus the first verified set of each of the last
#                                  KEEP_MONTHS (12) months; DRY_RUN=1 only lists
#   db-backup.sh status            newest verified backup, counts, schedule
#
# A backup set is `backups/capitalos_<ts>.dump` plus:
#   .dump.counts       per-table row counts taken in the SAME snapshot pg_dump used, so the
#                      comparison is exact even while schedulers write during the backup
#   .data.tar.gz       the contents of data/ (raw statements, IBKR Flex XMLs; #155), taken
#                      right after the dump, so every file a dumped row names is already on
#                      disk (files are written before their rows and never deleted)
#   .dump.verified     written only when BOTH parts passed: the dump restored into a scratch
#                      database with every table's count matching, and every file that a
#                      restored row records (import_jobs.stored_path + file_sha256,
#                      raw_broker_documents.storage_path + content_hash) is in the unpacked
#                      archive with that sha256. Otherwise .dump.failed with the reason.
# Dumps without markers (made before this tool) are never pruned (D-11).
#
# Env: DB_CONTAINER, DB_USER, DB_NAME (from the Makefile), BACKUP_DIR (default backups),
#      BACKUP_DATA_DIR (default data, the host side of the api's /app/data).
set -euo pipefail

DB_USER=${DB_USER:-capitalos}
DB_NAME=${DB_NAME:-capitalos}
BACKUP_DIR=${BACKUP_DIR:-backups}
BACKUP_DATA_DIR=${BACKUP_DATA_DIR:-data}
# Where the api container sees data/ (docker-compose.yml: ./data:/app/data).
CONTAINER_DATA_DIR=/app/data
# The signing key the API generates in data/ (app/services/auth.py) stays out of backups;
# a restore keeps the current one.
SECRET_FILE=.auth_secret

# Exact row count of every table in public, one "table|count" line each, sorted.
COUNTS_SELECT="SELECT table_name || '|' || (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', table_schema, table_name), false, true, '')))[1]::text
FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
COUNTS_SQL="$COUNTS_SELECT ORDER BY table_name;"

# One cleanup for every exit path: the snapshot session, temp dirs, the scratch DB.
WORK="" SESSION_PID="" SCRATCH="" UNPACK="" STAGE=""
cleanup() {
  exec 3>&- 2>/dev/null || true
  if [ -n "$SESSION_PID" ]; then wait "$SESSION_PID" 2>/dev/null || true; fi
  if [ -n "$WORK" ]; then rm -f "$WORK"/sql "$WORK"/session.out "$WORK"/session.err "$WORK"/roles "$WORK"/acl.sql "$WORK"/skipped; rmdir "$WORK" 2>/dev/null || true; fi
  if [ -n "$UNPACK" ] && [ -d "$UNPACK" ]; then rm -rf "$UNPACK"; fi
  if [ -n "$STAGE" ] && [ -d "$STAGE" ]; then rm -rf "$STAGE"; fi
  if [ -n "$SCRATCH" ]; then
    docker exec -i "$DB_CONTAINER" psql -X -q -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS $SCRATCH" >/dev/null 2>&1 || true
  fi
  return 0
}

say() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
psql_db() { docker exec -i "$DB_CONTAINER" psql -X -q -At -v ON_ERROR_STOP=1 -U "$DB_USER" "$@" 2> >(grep -vi collation >&2); }
archive_of() { printf '%s.data.tar.gz' "${1%.dump}"; }

# ---- data/ (#155) ----

# "<sha256>|<path relative to the dir>" for every file under a directory.
file_hashes() {
  local tool
  if command -v sha256sum >/dev/null 2>&1; then tool="sha256sum"; else tool="shasum -a 256"; fi
  # shellcheck disable=SC2086 # $tool is a command and its flags
  (cd "$1" && find . -type f -exec $tool {} +) | sed 's#^\([0-9a-fA-F]*\)[ *]*\./#\1|#'
}

# The files a database records, "table|id|hash|path" per row (tables that don't exist yet,
# in an old dump, are skipped).
file_rows() {  # <database>
  local db=$1 spec table path_col hash_col
  for spec in import_jobs:stored_path:file_sha256 raw_broker_documents:storage_path:content_hash; do
    IFS=: read -r table path_col hash_col <<<"$spec"
    [ "$(psql_db -d "$db" -c "SELECT to_regclass('public.$table') IS NOT NULL")" = t ] || continue
    psql_db -d "$db" -c "SELECT '$table|' || id || '|' || coalesce($hash_col, '') || '|' || coalesce($path_col, '') FROM $table ORDER BY id"
  done
}

# Every row that records a file must find it under <dir> with the recorded sha256.
# A row records a file when it has a path AND a sha256 digest (64 hex characters). Rows
# without one have nothing to check and are counted, not failed: an upload whose copy failed
# before the path and hash were written (both empty), and the demo seed's history rows
# (made-up /app/data/uploads paths with md5 placeholders, migrations/seed_dummy.sql).
# Paths map from the container (/app/data/<rel>) or the repo (data/<rel>) to <dir>/<rel>.
# Prints failure lines, then "RESULT checked=.. no_file=.. files=.. failed=..". Exit 1 on any failure.
check_data() {  # <rows file> <dir>
  local rows=$1 dir=$2 hashes rc=0
  hashes=$(mktemp)
  file_hashes "$dir" >"$hashes"
  awk -F'|' -v cdir="$CONTAINER_DATA_DIR/" -v max_lines=20 '
    function report(kind, msg) { failed++; if (failed <= max_lines) print kind " " msg }
    NR == FNR { h[substr($0, index($0, "|") + 1)] = tolower($1); files++; next }
    {
      table = $1; id = $2; hash = tolower($3)
      path = $0; sub(/^[^|]*\|[^|]*\|[^|]*\|/, "", path)
      if (path == "" || length(hash) != 64 || hash ~ /[^0-9a-f]/) { no_file++; next }
      rel = ""
      if (index(path, cdir) == 1) rel = substr(path, length(cdir) + 1)
      else if (index(path, "./data/") == 1) rel = substr(path, 8)
      else if (index(path, "data/") == 1) rel = substr(path, 6)
      gsub(/\/\/+/, "/", rel)
      if (rel == "" || rel ~ /^\// || rel ~ /(^|\/)\.\.(\/|$)/) { report("OUTSIDE", table " id=" id ": " path " is not under data/"); next }
      checked++
      if (!(rel in h)) report("MISSING", table " id=" id ": " rel)
      else if (h[rel] != hash) report("CHANGED", table " id=" id ": " rel " (sha256 differs)")
    }
    END {
      if (failed > max_lines) print "... and " failed - max_lines " more"
      printf "RESULT checked=%d no_file=%d files=%d failed=%d\n", checked, no_file, files, failed
      exit (failed > 0)
    }' "$hashes" "$rows" || rc=1
  rm -f "$hashes"
  return $rc
}

result_field() { sed -n "s/^RESULT.* $1=\([0-9]*\).*/\1/p" <<<"$2"; }

# The contents of data/ (not the directory itself), so a restore can unpack anywhere.
make_archive() {  # <archive>
  local out=$1 src=$BACKUP_DATA_DIR empty=""
  if [ ! -d "$src" ]; then empty=$(mktemp -d); src=$empty; say "WARNING: no $BACKUP_DATA_DIR/ to archive; the archive is empty"; fi
  if ! tar -czf "$out.part" --exclude "./$SECRET_FILE" -C "$src" .; then
    rm -f "$out.part"; [ -n "$empty" ] && rmdir "$empty"; say "FAILED: could not archive $BACKUP_DATA_DIR/" >&2; return 1
  fi
  [ -n "$empty" ] && rmdir "$empty"
  mv "$out.part" "$out"
  say "Wrote $out ($(wc -c <"$out" | tr -d ' ') bytes, $(tar -tzf "$out" | grep -cv '/$' || true) files)"
}

# Puts a restored data dir in place of data/; the current one is moved aside, never deleted.
swap_in_data() {  # <stage dir> <timestamp>
  local stage=$1 ts=$2 aside
  if [ -f "$BACKUP_DATA_DIR/$SECRET_FILE" ] && [ ! -e "$stage/$SECRET_FILE" ]; then
    cp -p "$BACKUP_DATA_DIR/$SECRET_FILE" "$stage/$SECRET_FILE"
  fi
  if [ -e "$BACKUP_DATA_DIR" ]; then
    aside="$BACKUP_DATA_DIR.pre-restore-$ts"
    [ -e "$aside" ] && { say "FAILED: $aside already exists" >&2; return 1; }
    mv "$BACKUP_DATA_DIR" "$aside"
    say "Moved the current $BACKUP_DATA_DIR/ aside to $aside (delete it once you're happy)"
  fi
  mv "$stage" "$BACKUP_DATA_DIR"
}

# ---- database ----

# Dump inside one REPEATABLE READ transaction whose snapshot pg_dump reuses, and take
# the counts in that same transaction. Then archive data/ and verify both.
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
  # After the dump: every file a dumped row names already exists (written before its row).
  make_archive "$(archive_of "$out")" || { fail "$out" "could not archive $BACKUP_DATA_DIR/"; return 1; }
  verify "$out"
}

# Restore into a scratch database; compare counts when the backup has them; then check the
# data archive against the restored rows.
verify() {
  local dump=${1:?verify needs a dump file} scratch restored archive rows result tables nrows
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
  if [ ! -f "$dump.counts" ]; then
    # A dump from before this tool: it restores, but there are no snapshot counts to compare.
    printf 'checked_at=%s\ntables=%s\nmethod=restore-only\n' "$(date -u +%FT%TZ)" \
      "$(printf '%s\n' "$restored" | grep -c '|')" >"$dump.restorable"
    say "RESTORABLE $dump: restored $(printf '%s\n' "$restored" | grep -c '|') tables (no snapshot counts to compare; not a verified backup)"
    return 0
  fi
  if ! diff <(sort "$dump.counts") <(printf '%s\n' "$restored" | sort) >"$dump.diff"; then
    fail "$dump" "row counts differ after restore (see $dump.diff)"; return 1
  fi
  rm -f "$dump.diff"
  tables=$(wc -l <"$dump.counts" | tr -d ' ')
  nrows=$(awk -F'|' '{s+=$2} END {print s+0}' "$dump.counts")

  archive=$(archive_of "$dump")
  if [ ! -f "$archive" ]; then
    # A backup from before #155: the database part is proven, there is no data part. Its
    # markers are left as they are (a .verified marker needs both parts).
    say "DATABASE VERIFIED $dump: $tables tables, $nrows rows, counts identical. WARNING: no data archive (backup predates #155); markers unchanged"
    return 0
  fi
  UNPACK=$(mktemp -d)
  if ! tar -xzf "$archive" -C "$UNPACK" 2>"$dump.data-check"; then
    fail "$dump" "the data archive does not unpack (see $dump.data-check)"; return 1
  fi
  rows=$(mktemp)
  file_rows "$scratch" >"$rows" || { rm -f "$rows"; fail "$dump" "could not read the recorded files from the restored database"; return 1; }
  if ! result=$(check_data "$rows" "$UNPACK"); then
    rm -f "$rows"
    printf '%s\n' "$result" >"$dump.data-check"
    fail "$dump" "data: $(result_field failed "$result") recorded file(s) missing or changed in the archive (see $dump.data-check)"; return 1
  fi
  rm -f "$rows" "$dump.data-check"
  rm -rf "$UNPACK"; UNPACK=""
  printf 'verified_at=%s\ntables=%s\nrows=%s\ndata_files=%s\ndata_rows_checked=%s\ndata_rows_without_file=%s\nmethod=restore+exact-counts+data-sha256\n' \
    "$(date -u +%FT%TZ)" "$tables" "$nrows" "$(result_field files "$result")" \
    "$(result_field checked "$result")" "$(result_field no_file "$result")" >"$dump.verified"
  rm -f "$dump.failed"
  say "VERIFIED $dump: restored, $tables tables, $nrows rows, counts identical; data: $(result_field files "$result") files, $(result_field checked "$result") recorded files present with their sha256 ($(result_field no_file "$result") rows record no file)"
}

fail() { printf 'failed_at=%s\nreason=%s\n' "$(date -u +%FT%TZ)" "$2" >"$1.failed"; rm -f "$1.verified"; say "FAILED $1: $2" >&2; }

# ---- privileges on restore (#233) ----
# A dump carries GRANTs to roles that live outside the database, such as capitalos_mcp_ro
# (make db-create-mcp-role). The schema and rows are restored without privileges, then the
# dump's own privilege statements are applied, minus those naming a role the target doesn't
# have (reported, not an error). On a target with the role, the restored objects get exactly
# the dump's privileges: what the target's default privileges grant to a role on a re-created
# table is revoked first (otherwise user_credentials would come back readable by the MCP role,
# whose access the dump left out).

# Reads pg_restore's schema-only SQL on stdin; prints the statements of its ACL and DEFAULT ACL
# entries that name only roles listed in <roles file> (one name per line; PUBLIC always
# exists). One "SKIPPED <role>|<statement>" line per left-out statement goes to <skipped file>.
# A statement of a form it doesn't know fails the whole call (exit 2) rather than dropping it.
acl_statements() {  # <roles file> <skipped file>
  awk -v skipped="$2" -v q="'" '
    function ident(s) {  # a role name as pg_dump writes it: plain lower-case or "double ""quoted"""
      if (s ~ /^"/) { s = substr(s, 2, length(s) - 2); gsub(/""/, "\"", s) }
      return s
    }
    function missing(stmt,   rest, r, name) {  # the first role the statement names that is absent
      rest = stmt
      while (match(rest, "(^| )(FOR ROLE|TO|FROM|AUTHORIZATION) (\"([^\"]|\"\")+\"|" q "[^" q "]+" q "|[a-z_][a-z0-9_$]*)")) {
        r = substr(rest, RSTART, RLENGTH); rest = substr(rest, RSTART + RLENGTH)
        sub(/^ ?(FOR ROLE|TO|FROM|AUTHORIZATION) /, "", r)
        if (substr(r, 1, 1) == q) r = substr(r, 2, length(r) - 2); else r = ident(r)
        if (r != "PUBLIC" && !(r in role)) return r
      }
      return ""
    }
    NR == FNR { role[$0] = 1; next }
    /^-- .*Name: .*; Type: / { t = $0; sub(/.*; Type: /, "", t); sub(/;.*/, "", t); next }
    /^-- / { t = ""; next }
    t != "ACL" && t != "DEFAULT ACL" { next }
    /^--/ || /^[[:space:]]*$/ || /^\\(un)?restrict / { next }
    {
      known = /^(GRANT|REVOKE|ALTER DEFAULT PRIVILEGES) .*;$/ || /^(SET|RESET) SESSION AUTHORIZATION/
      if (!known) { print "acl_statements: unexpected privilege statement: " $0 > "/dev/stderr"; bad = 1; exit 2 }
      if ($0 ~ /^RESET SESSION AUTHORIZATION/) { if (as_missing != "") { as_missing = ""; next } print; next }
      if (as_missing != "") { print "SKIPPED " as_missing "|" $0 > skipped; next }
      r = missing($0)
      if (r != "") {
        print "SKIPPED " r "|" $0 > skipped
        if ($0 ~ /^SET SESSION AUTHORIZATION/) as_missing = r  # skip what it would have run as r
        next
      }
      print
    }
    END { if (bad) exit 2 }' "$1" -
}

# SQL run after the restore, in its transaction, before the dump's own privileges: for every
# role the target's default privileges grant to (other than the granting role), take back
# what it got on the re-created tables, sequences and functions.
RESET_DEFAULT_GRANTS_SQL="DO \$reset\$ DECLARE r record; BEGIN
  FOR r IN SELECT DISTINCT a.grantee::regrole::text AS grantee, d.defaclobjtype AS objtype
           FROM pg_catalog.pg_default_acl d, pg_catalog.aclexplode(d.defaclacl) a
           WHERE a.grantee <> 0 AND a.grantee <> d.defaclrole AND d.defaclobjtype IN ('r', 'S', 'f') LOOP
    EXECUTE pg_catalog.format('REVOKE ALL ON ALL %s IN SCHEMA public FROM %s',
      CASE r.objtype WHEN 'r' THEN 'TABLES' WHEN 'S' THEN 'SEQUENCES' ELSE 'FUNCTIONS' END, r.grantee);
  END LOOP;
END \$reset\$;"

# SQL that fails the restore's transaction unless every table's row count equals the dump's
# snapshot counts (<dump>.counts): the same exact check as verify, before anything is committed.
counts_check_sql() {  # <counts file>
  printf '%s\n' "DO \$counts\$ DECLARE diff text; BEGIN
  WITH expected(x) AS (SELECT line FROM pg_catalog.string_to_table(\$expected\$$(cat "$1")\$expected\$, E'\\n') line WHERE line <> ''),
       restored(x) AS ($COUNTS_SELECT)
  SELECT pg_catalog.string_agg(d, ', ' ORDER BY d) INTO diff FROM (
    (SELECT 'dump ' || x AS d FROM (SELECT x FROM expected EXCEPT SELECT x FROM restored) e)
    UNION ALL (SELECT 'restored ' || x FROM (SELECT x FROM restored EXCEPT SELECT x FROM expected) r)) both_ways;
  IF diff IS NOT NULL THEN RAISE EXCEPTION 'row counts differ from the dump''s snapshot: %', pg_catalog.left(diff, 500); END IF;
END \$counts\$;"
}

# The restore script for psql: one transaction, committed only if pg_restore produced the whole
# script (a pg_restore failure leaves no COMMIT, so psql's session ends and rolls back) and,
# when the dump has snapshot counts, every table's count matches them.
restore_sql() {  # <dump> <acl sql file>
  printf 'BEGIN;\n'
  docker exec -i "$DB_CONTAINER" pg_restore --clean --if-exists --no-privileges -f - <"$1" || return 1
  printf '%s\n' "$RESET_DEFAULT_GRANTS_SQL"
  cat "$2"
  [ ! -f "$1.counts" ] || counts_check_sql "$1.counts"
  printf 'COMMIT;\n'
}

# Database first (data/ untouched if it fails), then data/ from the same set.
restore() {
  local dump=${1:?restore needs a dump file} archive ts rows result roles acl skipped
  [ -f "$dump" ] || { say "FAILED: no such file $dump" >&2; return 1; }
  archive=$(archive_of "$dump")
  ts=$(date +%Y%m%d_%H%M%S)
  [ -f "$dump.verified" ] || say "WARNING: $dump has no .verified marker"
  WORK=$(mktemp -d)
  roles="$WORK/roles" acl="$WORK/acl.sql" skipped="$WORK/skipped"
  psql_db -d "$DB_NAME" -c "SELECT rolname FROM pg_catalog.pg_roles" >"$roles" ||
    { say "FAILED: could not list the roles of $DB_CONTAINER; nothing was changed" >&2; return 1; }
  : >"$skipped"
  if ! docker exec -i "$DB_CONTAINER" pg_restore --schema-only -f - <"$dump" | acl_statements "$roles" "$skipped" >"$acl"; then
    say "FAILED: could not read the privileges in $dump; nothing was changed" >&2; return 1
  fi
  if [ -f "$archive" ]; then
    STAGE="$BACKUP_DATA_DIR.restore-$ts"
    mkdir "$STAGE"
    tar -xzf "$archive" -C "$STAGE" || { say "FAILED: $archive does not unpack; nothing was changed" >&2; return 1; }
  else
    say "WARNING: no data archive for $dump (backup predates #155): only the database is restored, $BACKUP_DATA_DIR/ is left as it is"
  fi
  say "Restoring the database $DB_NAME in $DB_CONTAINER (one transaction)"
  if ! restore_sql "$dump" "$acl" |
      docker exec -i "$DB_CONTAINER" psql -X -q -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" >/dev/null \
      2> >(grep -vi collation >&2); then
    say "FAILED: the database restore failed and was rolled back; $BACKUP_DATA_DIR/ is unchanged" >&2; return 1
  fi
  if [ -f "$dump.counts" ]; then
    say "Database restored: $(wc -l <"$dump.counts" | tr -d ' ') tables, $(awk -F'|' '{s+=$2} END {print s+0}' "$dump.counts") rows, counts identical to the dump's snapshot; $(grep -c . "$acl" || true) of its privilege statements applied"
  else
    say "Database restored (no snapshot counts to compare: the dump predates #41); $(grep -c . "$acl" || true) of its privilege statements applied"
  fi
  if [ -s "$skipped" ]; then
    say "Left out $(grep -c . "$skipped") privilege statement(s) for role(s) this Postgres doesn't have: $(sed 's/^SKIPPED \([^|]*\)|.*/\1/' "$skipped" | sort -u | tr '\n' ' ')(for capitalos_mcp_ro: make db-create-mcp-role grants them)"
  fi
  [ -n "$STAGE" ] || return 0
  rows=$(mktemp)
  file_rows "$DB_NAME" >"$rows"
  if result=$(check_data "$rows" "$STAGE"); then
    say "Data: every recorded file present with its sha256 ($(result_field checked "$result") rows, $(result_field files "$result") files)"
  else
    printf '%s\n' "$result"
    say "WARNING: the restored data/ lacks or differs from files the restored database records (above); restoring it anyway"
  fi
  rm -f "$rows"
  swap_in_data "$STAGE" "$ts"
  STAGE=""
  say "Restored $BACKUP_DATA_DIR/ from $archive"
}

# The live database against data/ (read-only): would a backup's data check pass?
check_live() {
  local rows result rc=0
  rows=$(mktemp)
  file_rows "$DB_NAME" >"$rows"
  result=$(check_data "$rows" "$BACKUP_DATA_DIR") || rc=1
  rm -f "$rows"
  printf '%s\n' "$result"
  return $rc
}

# ---- retention (#155) ----

date_minus_days() {  # <YYYYmmdd> <days>
  date -j -v-"$2"d -f %Y%m%d "$1" +%Y%m%d 2>/dev/null || date -d "$1 -$2 days" +%Y%m%d
}

# Reads verified dump paths (any order) and prints the ones retention would remove: kept are
# every set dated on/after <cutoff>, the first set of each month in the last <months>
# calendar months (this month included), and the newest set whatever its age. Names that
# don't carry a capitalos_<YYYYmmdd>_<HHMMSS> timestamp are kept.
retention_prune_list() {  # <today YYYYmmdd> <cutoff YYYYmmdd> <months>
  local today=$1 cutoff=$2 months=$3 sorted newest seen=" " path base d m idx min_idx first
  sorted=$(sort)
  [ -n "$sorted" ] || return 0
  newest=$(printf '%s\n' "$sorted" | tail -1)
  min_idx=$(( 10#${today:0:4} * 12 + 10#${today:4:2} - months ))
  while IFS= read -r path; do
    base=${path##*/}
    [[ $base =~ ^capitalos_([0-9]{8})_[0-9]{6}\.dump$ ]] || continue
    d=${BASH_REMATCH[1]}
    m=${d:0:6}
    first=0
    case "$seen" in *" $m "*) ;; *) first=1; seen="$seen$m " ;; esac
    [ "$path" = "$newest" ] && continue
    [ "$d" -ge "$cutoff" ] && continue
    idx=$(( 10#${d:0:4} * 12 + 10#${d:4:2} ))
    [ "$first" = 1 ] && [ "$idx" -gt "$min_idx" ] && continue
    printf '%s\n' "$path"
  done <<<"$sorted"
}

remove_set() {  # <dump>
  rm -f "$1" "$1.counts" "$1.verified" "$1.failed" "$1.diff" "$1.restore.log" "$1.data-check" "$(archive_of "$1")"
}

prune() {
  local days=${KEEP_DAYS:-14} months=${KEEP_MONTHS:-12} today=${BACKUP_TODAY:-$(date +%Y%m%d)} cutoff dump n=0 total verb=Pruned
  [ "$days" -ge 0 ] 2>/dev/null && [ "$months" -ge 0 ] 2>/dev/null || { say "KEEP_DAYS and KEEP_MONTHS must be whole numbers" >&2; return 2; }
  cutoff=$(date_minus_days "$today" "$days")
  [ -n "${DRY_RUN:-}" ] && verb="Would prune"
  total=$(verified_sets | grep -c . || true)
  while IFS= read -r dump; do
    [ -n "$dump" ] || continue
    n=$((n + 1))
    [ -z "${DRY_RUN:-}" ] && remove_set "$dump"
    say "$verb $dump (+ its data archive)"
  done < <(verified_sets | retention_prune_list "$today" "$cutoff" "$months")
  # Failed backups are kept 7 days for diagnosis, then removed (with their archive).
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    [ -z "${DRY_RUN:-}" ] && remove_set "${f%.failed}"
    say "$verb failed ${f%.failed}"
  done < <(find "$BACKUP_DIR" -maxdepth 1 -name 'capitalos_*.dump.failed' -mtime +7 2>/dev/null)
  say "$([ -n "${DRY_RUN:-}" ] && echo 'Dry run: would keep' || echo Kept) $((total - n)) verified set(s): every one since $cutoff, the first of each of the last $months months, and the newest; dumps without markers are never pruned"
}

verified_sets() { ls -1 "$BACKUP_DIR"/capitalos_*.dump.verified 2>/dev/null | sed 's/\.verified$//' || true; }
verified_newest_first() { ls -1t "$BACKUP_DIR"/capitalos_*.dump.verified 2>/dev/null | sed 's/\.verified$//'; }

status() {
  local newest archive
  newest=$(verified_newest_first | head -1)
  if [ -n "$newest" ]; then
    echo "Newest verified backup: $newest"
    sed 's/^/  /' "$newest.verified"
    archive=$(archive_of "$newest")
    if [ -f "$archive" ]; then echo "  data archive: $archive ($(wc -c <"$archive" | tr -d ' ') bytes)"
    else echo "  data archive: none (backup predates #155)"; fi
  else
    echo "Newest verified backup: none"
  fi
  echo "Verified backups kept: $(verified_newest_first | wc -l | tr -d ' ') (retention: every set from the last 14 days + the first of each month for 12 months)"
  local failed
  failed=$(ls -1t "$BACKUP_DIR"/capitalos_*.dump.failed 2>/dev/null | head -1 || true)
  [ -n "$failed" ] && echo "Most recent failure: ${failed%.failed} ($(sed -n 's/^reason=//p' "$failed"))"
  return 0
}

main() {
  cd "$(dirname "$0")/.."
  trap cleanup EXIT
  case "${1:-}" in
    create|verify|restore|check-data) DB_CONTAINER=${DB_CONTAINER:?DB_CONTAINER is required} ;;
  esac
  case "${1:-}" in
    create) create ;;
    verify) verify "${2:-}" ;;
    restore) restore "${2:-}" ;;
    check-data) check_live ;;
    prune) prune ;;
    status) status ;;
    *) echo "usage: $0 create|verify <dump>|restore <dump>|check-data|prune|status" >&2; exit 2 ;;
  esac
}

# Sourced by scripts/test-db-backup.sh for the pure functions; run otherwise.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then main "$@"; fi
