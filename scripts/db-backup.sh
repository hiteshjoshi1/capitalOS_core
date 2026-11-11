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
# Encryption (#356, D-95): with BACKUP_AGE_RECIPIENT set (an age public key), a new set is made and
# verified in a private temp dir, then the dump, its counts and its data archive are encrypted
# into BACKUP_DIR as <file>.age and the plaintext is deleted. Only the public key is needed to
# make a backup. The markers (.verified, .failed) stay plain: they hold dates and counts, nothing
# from the data. A set is still named by its logical dump path (capitalos_<ts>.dump) everywhere;
# verify/restore/open decrypt into a private temp dir with BACKUP_AGE_IDENTITY (the private key,
# outside the repo). Plain sets (older ones, worktrees, CI) work as before.
#   db-backup.sh open <dump>         decrypt (or copy) a set into a new private temp dir and print
#                                    its dump's path; the caller deletes that dir (test instance)
#   db-backup.sh encrypt-existing    move plain sets from SRC_DIR (default <repo>/backups) into
#                                    BACKUP_DIR encrypted, each file decrypted back and compared by
#                                    sha256 before its plaintext goes; lists only unless APPLY=1
#   db-backup.sh key-init            create the age key pair (refuses if one exists)
#   db-backup.sh offsite-sync        copy verified encrypted sets missing from BACKUP_OFFSITE_DIR
#                                    (#357; also run after every backup); prune keeps both folders
#   db-backup.sh offsite-check       decrypt the newest off-site set and run the restore check
#
# Env: DB_CONTAINER, DB_USER, DB_NAME (from the Makefile), BACKUP_DIR, BACKUP_AGE_RECIPIENT,
#      BACKUP_AGE_IDENTITY (scripts/backup-env.sh: environment, then .env, then defaults),
#      BACKUP_DATA_DIR (default data, the host side of the api's /app/data).
set -euo pipefail

# shellcheck source=backup-env.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/backup-env.sh"
AGE_TOOL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/age-tool.sh"

DB_USER=${DB_USER:-capitalos}
DB_NAME=${DB_NAME:-capitalos}
# Run: main() resolves BACKUP_DIR and the keys (backup_env). Sourced (the tests): plain defaults.
if [ "${BASH_SOURCE[0]}" != "$0" ]; then
  : "${BACKUP_DIR:=backups}" "${BACKUP_AGE_RECIPIENT:=}" "${BACKUP_AGE_IDENTITY:=$HOME/.capitalos/backup/age-identity.txt}" "${BACKUP_OFFSITE_DIR:=}"
fi
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
WORK="" SESSION_PID="" SCRATCH="" UNPACK="" STAGE="" OPEN_DIR="" PLAIN_DIR=""
cleanup() {
  exec 3>&- 2>/dev/null || true
  if [ -n "$SESSION_PID" ]; then wait "$SESSION_PID" 2>/dev/null || true; fi
  # Decrypted or not-yet-encrypted plaintext (#356): always wiped.
  if [ -n "$OPEN_DIR" ] && [ -d "$OPEN_DIR" ]; then rm -rf "$OPEN_DIR"; fi
  if [ -n "$PLAIN_DIR" ] && [ -d "$PLAIN_DIR" ]; then rm -rf "$PLAIN_DIR"; fi
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

# ---- encryption (#356) ----

sha256_of() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -c1-64; else shasum -a 256 "$1" | cut -c1-64; fi; }
age_bin() { "$AGE_TOOL" path; }
encrypting() { [ -n "$BACKUP_AGE_RECIPIENT" ]; }

need_identity() {
  [ -r "$BACKUP_AGE_IDENTITY" ] && return 0
  say "FAILED: this backup is encrypted and the key to open it isn't at $BACKUP_AGE_IDENTITY (BACKUP_AGE_IDENTITY). Put the key saved in your password manager there (chmod 600), or point BACKUP_AGE_IDENTITY at it" >&2
  return 1
}

encrypt_file() {  # <plain file> <out.age>
  local age
  age=$(age_bin) || return 1
  "$age" -r "$BACKUP_AGE_RECIPIENT" -o "$2.part" "$1" || { rm -f "$2.part"; say "FAILED: could not encrypt $1" >&2; return 1; }
  mv "$2.part" "$2"
}

decrypt_file() {  # <in.age> <plain out>
  local age
  age=$(age_bin) || return 1
  need_identity || return 1
  ( umask 077; "$age" -d -i "$BACKUP_AGE_IDENTITY" -o "$2" "$1" ) || { rm -f "$2"; say "FAILED: cannot decrypt $1 with $BACKUP_AGE_IDENTITY: wrong or missing key" >&2; return 1; }
}

set_present() { [ -f "$1" ] || [ -f "$1.age" ]; }  # <dump>
set_encrypted() { [ -f "$1.age" ]; }

# The files of a set, relative to its dump: the dump, its snapshot counts, its data archive.
set_members() { printf '%s\n%s\n%s\n' "$1" "$1.counts" "$(archive_of "$1")"; }

# Puts a plaintext copy of a set in OPEN_DIR (private, wiped on exit) and its dump path in
# OPEN_DUMP. A plain set is used where it is unless <copy> is given.
open_set() {  # <dump> [copy]
  local dump=$1 copy=${2:-} m base
  if ! set_encrypted "$dump" && [ -z "$copy" ]; then OPEN_DUMP=$dump; return 0; fi
  OPEN_DIR=$(mktemp -d)
  chmod 700 "$OPEN_DIR"
  while IFS= read -r m; do
    base=${m##*/}
    if [ -f "$m.age" ]; then decrypt_file "$m.age" "$OPEN_DIR/$base" || return 1
    elif [ -f "$m" ]; then cp -p "$m" "$OPEN_DIR/$base"; fi
  done < <(set_members "$dump")
  OPEN_DUMP="$OPEN_DIR/${dump##*/}"
}

# Encrypts a verified (or failed) plain set from its temp dir into <dir>: each member to .age,
# then the markers; .verified last, so a set counts only once all of it is in place. When the
# private key is here too, each .age is decrypted back and compared before the plaintext goes.
# Copies <src> to <dest> as <dest>.part, checks the sha256, then renames it into place (#383).
put_file() {  # <src> <dest>
  cp -p "$1" "$2.part" 2>/dev/null &&
    [ "$(sha256_of "$1")" = "$(sha256_of "$2.part")" ] &&
    mv "$2.part" "$2" ||
    { rm -f "$2.part"; say "FAILED: could not copy $1 to $2" >&2; return 1; }
}

seal_set() {  # <plain dump> <dir>
  local dump=$1 dir=$2 m base f roundtrip=""
  mkdir -p "$dir"
  [ -r "$BACKUP_AGE_IDENTITY" ] && roundtrip=1
  while IFS= read -r m; do
    [ -f "$m" ] || continue
    base=${m##*/}
    # Encrypt next to the plain file (private temp dir), then copy in: under launchd macOS refused
    # bash renaming a file that age had just written inside iCloud Drive (#383, 11 Nov), while a
    # file bash itself copies in can be renamed.
    encrypt_file "$m" "$m.age" || return 1
    # The round trip reads the private copy: under launchd, reading a just-copied file back out of
    # iCloud Drive hung (#383). put_file then checks the copy's sha256 against it.
    if [ -n "$roundtrip" ]; then
      decrypt_file "$m.age" "$m.check" || return 1
      [ "$(sha256_of "$m")" = "$(sha256_of "$m.check")" ] || { say "FAILED: $m.age does not decrypt to the file it was made from" >&2; return 1; }
      rm -f "$m.check"
    fi
    put_file "$m.age" "$dir/$base.age" || { tcc_hint "$dir" >&2; return 1; }
    rm -f "$m.age"
  done < <(set_members "$dump")
  for f in "$dump".failed "$dump".diff "$dump".restore.log "$dump".data-check "$dump".restorable "$dump".verified; do
    if [ -f "$f" ]; then put_file "$f" "$dir/${f##*/}" && rm -f "$f" || return 1; fi
  done
  say "Encrypted to $dir/${dump##*/}.age (+ counts, data archive)$([ -n "$roundtrip" ] && echo '; each decrypted back and compared' || echo '; not decrypted back (no private key here)')"
}

# ---- off-site copy (#357) ----
# BACKUP_OFFSITE_DIR (main checkout's .env; Hitesh: iCloud Drive) gets a copy of every verified,
# ENCRYPTED set in BACKUP_DIR it doesn't have yet (so a missed day or a late-enabled iCloud catches
# up), and the same retention (prune). Plain sets never go off-site. A missing or unwritable
# off-site folder is a loud WARNING, never a failed backup: the local set is already safe.

# macOS privacy controls (TCC) treat the daily launchd job (/bin/bash) differently from Terminal.
# Probed 2026-11-10/11: in iCloud Drive the job may create, rename, delete, stat and read files but
# may NOT list the folder; in the user's personal folders it was refused renames too (#383), so
# backups live in one iCloud Drive folder and nothing here lists a backup folder without falling
# back to its index (INDEX_NAME below). No Full Disk Access is needed (and Hitesh doesn't want
# /bin/bash to have it: far too broad).
tcc_hint() {  # <dir>
  case "$1" in
    "$HOME/Library/Mobile Documents"*)
      echo "  If this ran from the daily job: macOS privacy controls may be blocking it from $1. Run make backup-now in Terminal to see whether it works there, and check $1 is a folder you own." ;;
  esac
}

offsite_warn() { say "WARNING (off-site copy): $*" >&2; }

offsite_ready() {  # 0 when BACKUP_OFFSITE_DIR is set and writable
  [ -n "${BACKUP_OFFSITE_DIR:-}" ] || return 1
  local parent
  parent=$(dirname "$BACKUP_OFFSITE_DIR")
  if [ ! -d "$parent" ]; then
    offsite_warn "$parent does not exist (iCloud Drive not turned on?); no off-site copy was made"; return 1
  fi
  if ! mkdir -p "$BACKUP_OFFSITE_DIR" 2>/dev/null || ! touch "$BACKUP_OFFSITE_DIR/.write-check" 2>/dev/null; then
    offsite_warn "can't write to $BACKUP_OFFSITE_DIR; no off-site copy was made"; tcc_hint "$BACKUP_OFFSITE_DIR" >&2; return 1
  fi
  rm -f "$BACKUP_OFFSITE_DIR/.write-check"
  return 0
}

# Copies one encrypted set; each .age file compared by sha256; the marker last.
offsite_copy_set() {  # <dump in BACKUP_DIR>
  local dump=$1 base m mb dest
  base=${dump##*/}; dest="$BACKUP_OFFSITE_DIR/$base"
  while IFS= read -r m; do
    [ -f "$m.age" ] || continue
    mb=${m##*/}
    cp -p "$m.age" "$BACKUP_OFFSITE_DIR/$mb.age.part" 2>/dev/null &&
      [ "$(sha256_of "$m.age")" = "$(sha256_of "$BACKUP_OFFSITE_DIR/$mb.age.part")" ] &&
      mv "$BACKUP_OFFSITE_DIR/$mb.age.part" "$BACKUP_OFFSITE_DIR/$mb.age" ||
      { rm -f "$BACKUP_OFFSITE_DIR/$mb.age.part"; offsite_warn "copying $m.age failed"; tcc_hint "$BACKUP_OFFSITE_DIR" >&2; return 1; }
  done < <(set_members "$dump")
  cp -p "$dump.verified" "$dest.verified" || { offsite_warn "copying $dump.verified failed"; return 1; }
}

# The set index (#357, #383): one verified set name (capitalos_<ts>.dump) per line, kept in each
# backup folder (BACKUP_DIR and the optional BACKUP_OFFSITE_DIR). Under launchd macOS lets the
# daily job open, write, rename and delete files in iCloud Drive but not LIST the folder, so
# every "which sets are there" question is answered from a listing when one is allowed (and the
# index refreshed from it) and from the index otherwise. The pre-#383 off-site index name is
# read too, so a folder that was the off-site copy keeps its history (adopted, then rewritten).
INDEX_NAME=.capitalos-index
LEGACY_INDEX_NAME=.capitalos-offsite-index
# Where a folder's index lives. In iCloud Drive the daily job (launchd) could neither read nor
# replace an index file Terminal had written there ("Operation not permitted", #383), so an iCloud
# folder's index is kept on the Mac in ~/.capitalos/backup/index/ (no privacy controls there; it
# is only a list of names, rebuilt from a listing in Terminal if lost). BACKUP_INDEX_DIR overrides
# it for every folder; other folders keep it inside (worktrees, tests).
index_of() { backup_index_of "$1"; }  # <dir>; see backup_index_of (scripts/backup-env.sh)

# BACKUP_TEST_UNLISTABLE simulates the refusal (scripts/test-db-backup.sh): 1 or offsite = the
# off-site folder, local = BACKUP_DIR, all = both.
listing_refused() {  # <dir>
  case "${BACKUP_TEST_UNLISTABLE:-}" in
    all) return 0 ;;
    local) [ "$1" = "$BACKUP_DIR" ] ;;
    1|offsite) [ -n "${BACKUP_OFFSITE_DIR:-}" ] && [ "$1" = "$BACKUP_OFFSITE_DIR" ] ;;
    *) return 1 ;;
  esac
}

# The folder's verified set names from a listing, or fails where listing is refused.
dir_listing() {  # <dir>
  listing_refused "$1" && return 1
  ls -1 "$1" >/dev/null 2>&1 || return 1
  ls -1 "$1" 2>/dev/null | sed -n 's/^\(capitalos_.*\.dump\)\.verified$/\1/p'
}

index_write() {  # <dir>; names on stdin; atomic (tmp + mv); quiet when unchanged
  local idx tmp
  idx=$(index_of "$1"); tmp="$idx.part"
  mkdir -p "$(dirname "$idx")" 2>/dev/null || true
  sort -u | grep . >"$tmp" 2>/dev/null || true
  if [ -f "$idx" ] && cmp -s "$tmp" "$idx"; then rm -f "$tmp"; return 0; fi
  mv "$tmp" "$idx" 2>/dev/null || { rm -f "$tmp"; say "WARNING: could not write $idx" >&2; return 1; }
}

# The index's names (the current file, else the pre-#383 one), kept to sets whose marker is there.
index_names() {  # <dir>
  local idx n
  idx=$(index_of "$1")
  # Before the index moved out of iCloud: the folder's own index files (may be unreadable here).
  [ -f "$idx" ] || idx="$1/$INDEX_NAME"
  [ -f "$idx" ] || idx="$1/$LEGACY_INDEX_NAME"
  [ -f "$idx" ] && [ -r "$idx" ] || return 1
  { while IFS= read -r n; do [ -n "$n" ] && [ -e "$1/$n.verified" ] && echo "$n"; done <"$idx"; } 2>/dev/null || true
}

# The verified set names in <dir>, oldest first. A listing when allowed (the index is refreshed
# from it if the folder is writable), else the index, else nothing (a warning says why).
dir_names() {  # <dir>
  local dir=$1 names
  [ -d "$dir" ] || return 0
  if names=$(dir_listing "$dir"); then
    [ -w "$dir" ] && printf '%s\n' "$names" | index_write "$dir" 2>/dev/null
  elif ! names=$(index_names "$dir"); then
    say "WARNING: can't list $dir (macOS lets the daily job open files there, not list them) and it has no $INDEX_NAME yet; run make backup-status once in Terminal to create it" >&2
    names=""
  fi
  printf '%s\n' "$names" | grep . | sort -u || true
}

# Rewrites <dir>'s index to the sets still there (after a prune). With no listing and no index
# there is nothing to go by, so nothing is written.
index_refresh() {  # <dir>
  local names
  names=$(dir_names "$1")
  [ -n "$names" ] || [ -f "$(index_of "$1")" ] || [ -f "$1/$INDEX_NAME" ] || [ -f "$1/$LEGACY_INDEX_NAME" ] || return 0
  printf '%s\n' "$names" | index_write "$1"
}

index_add() {  # <dir> <set name>: records one more set
  { dir_names "$1"; printf '%s\n' "$2"; } | index_write "$1"
}

offsite_index() { index_of "$BACKUP_OFFSITE_DIR"; }

# The verified set names off-site. With neither a listing nor an index, the local sets that are
# off-site too. [write] also saves the index it worked out.
offsite_names() {  # [write]
  local names n
  if names=$(dir_listing "$BACKUP_OFFSITE_DIR"); then
    :
  elif names=$(index_names "$BACKUP_OFFSITE_DIR"); then
    :
  else
    offsite_warn "can't list $BACKUP_OFFSITE_DIR (macOS allows the daily job to open files there, not to list them) and it has no $INDEX_NAME yet; using the local set names" >&2
    names=$(verified_sets | while IFS= read -r n; do n=${n##*/}; [ -e "$BACKUP_OFFSITE_DIR/$n.verified" ] && echo "$n"; done || true)
  fi
  [ "${1:-}" = write ] && printf '%s\n' "$names" | index_write "$BACKUP_OFFSITE_DIR"
  printf '%s\n' "$names" | grep . | sort -u || true
}

# Every verified encrypted set missing off-site is copied. Never fails the caller.
offsite_sync() {
  local dump n=0 bad=0 names
  offsite_ready || return 0
  names=$(offsite_names)
  while IFS= read -r dump; do
    [ -n "$dump" ] || continue
    set_encrypted "$dump" || continue
    if [ -e "$BACKUP_OFFSITE_DIR/${dump##*/}.verified" ]; then names=$(printf '%s\n%s' "$names" "${dump##*/}"); continue; fi
    if offsite_copy_set "$dump"; then n=$((n + 1)); names=$(printf '%s\n%s' "$names" "${dump##*/}"); else bad=$((bad + 1)); fi
  done < <(verified_sets)
  printf '%s\n' "$names" | index_write "$BACKUP_OFFSITE_DIR" || true
  say "Off-site: $n set(s) copied to $BACKUP_OFFSITE_DIR$([ "$bad" -gt 0 ] && echo "; $bad FAILED (above)")"
  return 0
}

# Retention off-site (#357): the same rule over the index's names; the index is rewritten.
offsite_prune() {
  local today=$1 cutoff=$2 months=$3 names gone n=0 verb=Pruned
  [ -n "${DRY_RUN:-}" ] && verb="Would prune"
  names=$(offsite_names)
  gone=$(printf '%s\n' "$names" | grep . | sed "s|^|$BACKUP_OFFSITE_DIR/|" | retention_prune_list "$today" "$cutoff" "$months")
  while IFS= read -r dump; do
    [ -n "$dump" ] || continue
    n=$((n + 1))
    [ -z "${DRY_RUN:-}" ] && remove_set "$dump"
    say "$verb $dump"
  done <<<"$gone"
  [ -n "${DRY_RUN:-}" ] && return 0
  printf '%s\n' "$names" | grep -vxF -f <(printf '%s\n' "$gone" | sed 's|.*/||' | grep . || echo '/') | index_write "$BACKUP_OFFSITE_DIR" || true
  say "Off-site: kept $(( $(printf '%s\n' "$names" | grep -c . || true) - n )) set(s)"
}

# `offsite-check`: the newest off-site set, copied to a private temp dir (nothing off-site is
# written), decrypted and put through the full restore check.
offsite_check() {
  local newest tmpset m base
  [ -n "${BACKUP_OFFSITE_DIR:-}" ] || { say "FAILED: no BACKUP_OFFSITE_DIR set" >&2; return 1; }
  newest=$(offsite_names | tail -1)
  [ -n "$newest" ] || { say "FAILED: no verified set in $BACKUP_OFFSITE_DIR" >&2; return 1; }
  newest="$BACKUP_OFFSITE_DIR/$newest"
  need_identity || return 1
  PLAIN_DIR=$(mktemp -d); chmod 700 "$PLAIN_DIR"
  base=${newest##*/}
  while IFS= read -r m; do
    [ -f "$m.age" ] && cp "$m.age" "$PLAIN_DIR/${m##*/}.age"
  done < <(set_members "$newest")
  tmpset="$PLAIN_DIR/$base"
  set_encrypted "$tmpset" || { say "FAILED: $newest has no .age dump" >&2; return 1; }
  say "Checking the newest off-site set $newest"
  verify "$tmpset" || { say "FAILED: the off-site set $newest did not pass the restore check" >&2; return 1; }
  say "OFF-SITE OK: $newest decrypts and restores (counts identical, data files present)"
}

offsite_status() {
  [ -n "${BACKUP_OFFSITE_DIR:-}" ] || { echo "Off-site copy: not set up (BACKUP_OFFSITE_DIR, #357)"; return 0; }
  if [ ! -d "$BACKUP_OFFSITE_DIR" ]; then
    echo "Off-site copy: WARNING $BACKUP_OFFSITE_DIR does not exist$([ -d "$(dirname "$BACKUP_OFFSITE_DIR")" ] || echo ' (iCloud Drive not turned on?)'); no off-site copy yet"
    return 0
  fi
  local names newest age_h n
  names=$(offsite_names 2>/dev/null)
  n=$(printf '%s\n' "$names" | grep -c . || true)
  newest=$(printf '%s\n' "$names" | grep . | tail -1 || true)
  if [ -z "$newest" ]; then echo "Off-site copy: WARNING no set in $BACKUP_OFFSITE_DIR yet"; return 0; fi
  newest="$BACKUP_OFFSITE_DIR/$newest.verified"
  age_h=$(( ($(date +%s) - $(stat -c %Y "$newest" 2>/dev/null || stat -f %m "$newest")) / 3600 ))
  echo "Off-site copy: $BACKUP_OFFSITE_DIR, $n set(s), newest ${newest##*/} (${age_h}h ago)$([ "$age_h" -gt 48 ] && echo '  <- WARNING: OLDER THAN 2 DAYS')"
}

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
  local ts out work fifo snapshot="" dir=$BACKUP_DIR rc=0
  # Loud when the folder can't be written: under launchd that is usually macOS privacy (#356).
  if ! mkdir -p "$BACKUP_DIR" 2>/dev/null || ! touch "$BACKUP_DIR/.write-check" 2>/dev/null; then
    say "FAILED: can't write to the backup folder $BACKUP_DIR" >&2; tcc_hint "$BACKUP_DIR" >&2; return 1
  fi
  rm -f "$BACKUP_DIR/.write-check"
  if encrypting; then
    # #356: made and verified in a private temp dir; only the encrypted files reach BACKUP_DIR.
    age_bin >/dev/null || return 1
    PLAIN_DIR=$(mktemp -d)
    chmod 700 "$PLAIN_DIR"
    dir=$PLAIN_DIR
  fi
  ts=$(date +%Y%m%d_%H%M%S)
  out="$dir/capitalos_${ts}.dump"
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
  if ! make_archive "$(archive_of "$out")"; then
    fail "$out" "could not archive $BACKUP_DATA_DIR/"; rc=1
  else
    verify "$out" || rc=$?
  fi
  if encrypting; then
    seal_set "$out" "$BACKUP_DIR" || { say "FAILED: the backup was made but not stored encrypted; nothing written to $BACKUP_DIR counts as a backup" >&2; tcc_hint "$BACKUP_DIR" >&2; return 1; }
  fi
  # #383: recorded in the folder's index, which the daily job reads where it can't list.
  [ -e "$BACKUP_DIR/${out##*/}.verified" ] && { index_add "$BACKUP_DIR" "${out##*/}" || true; }
  # #357: the off-site copy; a problem there warns, it never fails the backup.
  [ "$rc" -ne 0 ] || offsite_sync
  return $rc
}

# Restore into a scratch database; compare counts when the backup has them; then check the
# data archive against the restored rows.
verify() {
  local dump=${1:?verify needs a dump file} scratch restored archive rows result tables nrows src
  set_present "$dump" || { say "FAILED: no such file $dump" >&2; return 1; }
  # An encrypted set is checked from a decrypted copy (#356); markers stay next to the set. A
  # missing or wrong key says nothing about the set itself, so no marker or log is written.
  if set_encrypted "$dump"; then need_identity || return 1; fi
  open_set "$dump" || return 1
  src=$OPEN_DUMP
  scratch="capitalos_verify_$$"
  SCRATCH=$scratch
  psql_db -d postgres -c "CREATE DATABASE $scratch" >/dev/null
  if ! docker exec -i "$DB_CONTAINER" pg_restore -U "$DB_USER" -d "$scratch" --no-owner --no-acl --exit-on-error \
      <"$src" 2>"$dump.restore.log"; then
    fail "$dump" "pg_restore failed: $(grep -vi collation "$dump.restore.log" | tail -1)"; return 1
  fi
  rm -f "$dump.restore.log"
  restored=$(printf '%s\n' "$COUNTS_SQL" | psql_db -d "$scratch")
  if [ ! -f "$src.counts" ]; then
    # A dump from before this tool: it restores, but there are no snapshot counts to compare.
    printf 'checked_at=%s\ntables=%s\nmethod=restore-only\n' "$(date -u +%FT%TZ)" \
      "$(printf '%s\n' "$restored" | grep -c '|')" >"$dump.restorable"
    say "RESTORABLE $dump: restored $(printf '%s\n' "$restored" | grep -c '|') tables (no snapshot counts to compare; not a verified backup)"
    return 0
  fi
  if ! diff <(sort "$src.counts") <(printf '%s\n' "$restored" | sort) >"$dump.diff"; then
    fail "$dump" "row counts differ after restore (see $dump.diff)"; return 1
  fi
  rm -f "$dump.diff"
  tables=$(wc -l <"$src.counts" | tr -d ' ')
  nrows=$(awk -F'|' '{s+=$2} END {print s+0}' "$src.counts")

  archive=$(archive_of "$src")
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
  local dump=${1:?restore needs a dump file} archive ts rows result roles acl skipped src
  set_present "$dump" || { say "FAILED: no such file $dump" >&2; return 1; }
  # An encrypted set is restored from a decrypted copy in a private temp dir (#356).
  open_set "$dump" || { say "FAILED: $dump was not opened (see above); nothing was changed" >&2; return 1; }
  src=$OPEN_DUMP
  archive=$(archive_of "$src")
  ts=$(date +%Y%m%d_%H%M%S)
  [ -f "$dump.verified" ] || say "WARNING: $dump has no .verified marker"
  WORK=$(mktemp -d)
  roles="$WORK/roles" acl="$WORK/acl.sql" skipped="$WORK/skipped"
  psql_db -d "$DB_NAME" -c "SELECT rolname FROM pg_catalog.pg_roles" >"$roles" ||
    { say "FAILED: could not list the roles of $DB_CONTAINER; nothing was changed" >&2; return 1; }
  : >"$skipped"
  if ! docker exec -i "$DB_CONTAINER" pg_restore --schema-only -f - <"$src" | acl_statements "$roles" "$skipped" >"$acl"; then
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
  if ! restore_sql "$src" "$acl" |
      docker exec -i "$DB_CONTAINER" psql -X -q -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" >/dev/null \
      2> >(grep -vi collation >&2); then
    say "FAILED: the database restore failed and was rolled back; $BACKUP_DATA_DIR/ is unchanged" >&2; return 1
  fi
  if [ -f "$src.counts" ]; then
    say "Database restored: $(wc -l <"$src.counts" | tr -d ' ') tables, $(awk -F'|' '{s+=$2} END {print s+0}' "$src.counts") rows, counts identical to the dump's snapshot; $(grep -c . "$acl" || true) of its privilege statements applied"
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
  say "Restored $BACKUP_DATA_DIR/ from $(archive_of "$dump")$(set_encrypted "$dump" && echo .age)"
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

remove_set() {  # <dump>: plain and encrypted (#356) files alike
  rm -f "$1" "$1.counts" "$1.verified" "$1.failed" "$1.diff" "$1.restore.log" "$1.data-check" "$(archive_of "$1")" \
    "$1.age" "$1.counts.age" "$(archive_of "$1").age"
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
  [ -n "${DRY_RUN:-}" ] || index_refresh "$BACKUP_DIR"
  say "$([ -n "${DRY_RUN:-}" ] && echo 'Dry run: would keep' || echo Kept) $((total - n)) verified set(s): every one since $cutoff, the first of each of the last $months months, and the newest; dumps without markers are never pruned"
  # #357: the off-site folder keeps the same sets.
  if [ -n "${BACKUP_OFFSITE_DIR:-}" ] && [ -d "$BACKUP_OFFSITE_DIR" ] && ! [ "$BACKUP_DIR" -ef "$BACKUP_OFFSITE_DIR" ]; then
    say "Off-site, $BACKUP_OFFSITE_DIR:"
    offsite_prune "$today" "$cutoff" "$months" || offsite_warn "pruning $BACKUP_OFFSITE_DIR failed"
  fi
}

# BACKUP_DIR's verified sets as paths (#383: from a listing or the folder's index, never a bare
# glob, which the daily job can't do in iCloud Drive). Names carry the timestamp: name order is age.
verified_sets() { dir_names "$BACKUP_DIR" | sed "s|^|$BACKUP_DIR/|"; }
verified_newest_first() { verified_sets | sort -r; }

status() {
  local newest archive n_enc=0 n_all=0 s
  echo "Backup folder: $BACKUP_DIR"
  if encrypting; then
    echo "Encryption: on (age, to $BACKUP_AGE_RECIPIENT); private key $([ -r "$BACKUP_AGE_IDENTITY" ] && echo "at $BACKUP_AGE_IDENTITY" || echo "NOT at $BACKUP_AGE_IDENTITY: restores need it (your password manager copy)")"
  else
    echo "Encryption: OFF (no BACKUP_AGE_RECIPIENT): new backups are plain files (make backup-key-init)"
  fi
  newest=$(verified_newest_first | head -1)
  if [ -n "$newest" ]; then
    echo "Newest verified backup: $newest ($(set_encrypted "$newest" && echo encrypted || echo PLAIN))"
    sed 's/^/  /' "$newest.verified"
    archive=$(archive_of "$newest")
    if [ -f "$archive.age" ]; then echo "  data archive: $archive.age ($(wc -c <"$archive.age" | tr -d ' ') bytes, encrypted)"
    elif [ -f "$archive" ]; then echo "  data archive: $archive ($(wc -c <"$archive" | tr -d ' ') bytes)"
    else echo "  data archive: none (backup predates #155)"; fi
  else
    echo "Newest verified backup: none"
  fi
  while IFS= read -r s; do
    [ -n "$s" ] || continue
    n_all=$((n_all + 1)); set_encrypted "$s" && n_enc=$((n_enc + 1))
  done < <(verified_newest_first)
  echo "Verified backups kept: $n_all, $n_enc encrypted (retention: every set from the last 14 days + the first of each month for 12 months)"
  local failed
  failed=$(ls -1t "$BACKUP_DIR"/capitalos_*.dump.failed 2>/dev/null | head -1 || true)
  [ -n "$failed" ] && echo "Most recent failure: ${failed%.failed} ($(sed -n 's/^reason=//p' "$failed"))"
  offsite_status
  return 0
}

# ---- status file for the app (#399, D-111) ----
# The API runs in Docker and can't see the backup folder, so after a backup, a prune and
# `make backup-status` this writes a small JSON file into the checkout's state/ folder, which
# compose mounts read-only into the API (Data Hub's "Last verified backup" line and the Inbox).
# No paths or keys: when the newest verified set was made, how many are kept, encrypted or not,
# icloud or local, the daily time and this Mac's UTC offset, and how the last run went.
# state/ is not data/, so it's never in a backup archive. Writing it never fails a backup.
utc_offset() { local z; z=$(date +%z); printf '%s:%s' "${z:0:3}" "${z:3:2}"; }
iso_now() { printf '%s%s' "$(date +%Y-%m-%dT%H:%M:%S)" "$(utc_offset)"; }
set_iso_time() {  # <dump path>: its name's local time as ISO 8601 with this Mac's offset
  local ts=${1##*/capitalos_}
  ts=${ts%.dump}
  [[ "$ts" =~ ^([0-9]{4})([0-9]{2})([0-9]{2})_([0-9]{2})([0-9]{2})([0-9]{2})$ ]] || return 1
  printf '%s-%s-%sT%s:%s:%s%s' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}" "${BASH_REMATCH[3]}" \
    "${BASH_REMATCH[4]}" "${BASH_REMATCH[5]}" "${BASH_REMATCH[6]}" "$(utc_offset)"
}
json_field() {  # <file> <name>: a string or bare value from our own one-field-per-line JSON
  sed -n "s/^  \"$2\": \"\{0,1\}\([^\",]*\)\"\{0,1\},\{0,1\}$/\1/p" "$1" 2>/dev/null | head -1
}
write_status() {  # [run <rc>]: rewrite the status file; with `run`, record this run's result
  local f=${BACKUP_STATUS_FILE:-$PWD/state/backup-status.json} newest="" newest_at=null n=0 enc=null loc=local
  local last_at=null last_ok=null old t prev
  mkdir -p "$(dirname "$f")" 2>/dev/null || return 1
  newest=$(verified_newest_first 2>/dev/null | head -1 || true)
  n=$(verified_sets 2>/dev/null | grep -c . || true)
  if [ -n "$newest" ]; then
    t=$(set_iso_time "$newest" || true)
    [ -n "$t" ] && newest_at="\"$t\""
    if set_encrypted "$newest"; then enc=true; else enc=false; fi
  fi
  case "$BACKUP_DIR" in "$HOME/Library/Mobile Documents/"*) loc=icloud ;; esac
  if [ "${1:-}" = run ]; then
    last_at="\"$(iso_now)\""
    if [ "${2:-1}" = 0 ]; then last_ok=true; else last_ok=false; fi
  elif [ -f "$f" ]; then
    prev=$(json_field "$f" last_run_at); [ -n "$prev" ] && [ "$prev" != null ] && last_at="\"$prev\""
    old=$(json_field "$f" last_run_ok); case "$old" in true|false) last_ok=$old ;; esac
  fi
  {
    printf '{\n'
    printf '  "version": 1,\n'
    printf '  "written_at": "%s",\n' "$(iso_now)"
    printf '  "newest_verified_at": %s,\n' "$newest_at"
    printf '  "sets": %s,\n' "${n:-0}"
    printf '  "encrypted": %s,\n' "$enc"
    printf '  "location": "%s",\n' "$loc"
    printf '  "daily_time": "%s",\n' "$(backup_time "$PWD")"
    printf '  "utc_offset": "%s",\n' "$(utc_offset)"
    printf '  "last_run_at": %s,\n' "$last_at"
    printf '  "last_run_ok": %s\n' "$last_ok"
    printf '}\n'
  } >"$f.part" && mv "$f.part" "$f"
}
write_status_quietly() { write_status "$@" || say "WARNING: could not write the backup status file for the app" >&2; }

# `open <dump>` (#356): a plaintext copy of a set in a new private temp dir, its dump's path
# printed. The caller owns (and deletes) the dir: the test instance restores from it.
open_cmd() {
  local dump=${1:?open needs a dump file}
  set_present "$dump" || { say "FAILED: no such file $dump" >&2; return 1; }
  open_set "$dump" copy || return 1
  printf '%s\n' "$OPEN_DUMP"
  OPEN_DIR=""   # handed to the caller: not wiped on exit
}

# `key-init` (#356): the age key pair. The private key (identity) goes outside the repo, the
# public key (recipient) into .env as BACKUP_AGE_RECIPIENT. Never overwrites a key.
key_init() {
  local keygen pub
  keygen=$("$AGE_TOOL" keygen-path) || return 1
  if [ -e "$BACKUP_AGE_IDENTITY" ]; then
    say "A backup key already exists at $BACKUP_AGE_IDENTITY; not replacing it (backups made with it would become unreadable)." >&2
    pub=$("$keygen" -y "$BACKUP_AGE_IDENTITY") && echo "Its public key: $pub"
    return 1
  fi
  mkdir -p "$(dirname "$BACKUP_AGE_IDENTITY")"
  chmod 700 "$(dirname "$BACKUP_AGE_IDENTITY")"
  ( umask 077; "$keygen" -o "$BACKUP_AGE_IDENTITY" 2>/dev/null )
  chmod 600 "$BACKUP_AGE_IDENTITY"
  pub=$("$keygen" -y "$BACKUP_AGE_IDENTITY")
  echo "Created the backup key: $BACKUP_AGE_IDENTITY (private, chmod 600, outside the repo)"
  if ! backup_is_main_checkout "$PWD"; then
    echo "Not the main checkout: add this line to the main checkout's .env: BACKUP_AGE_RECIPIENT=$pub"
  elif [ -f .env ] && grep -q '^BACKUP_AGE_RECIPIENT=' .env; then
    echo "WARNING: .env already has a BACKUP_AGE_RECIPIENT; set it to: $pub"
  else
    printf '\n# Backups are encrypted to this age public key (#356); the private key is %s\nBACKUP_AGE_RECIPIENT=%s\n' "$BACKUP_AGE_IDENTITY" "$pub" >>.env
    echo "Added BACKUP_AGE_RECIPIENT=$pub to .env"
  fi
  echo
  echo "NOW save the private key somewhere off this Mac (password manager, as a secure note):"
  echo "  cat $BACKUP_AGE_IDENTITY"
  echo "Without it no encrypted backup can be restored, including after a lost or dead Mac."
}

# `encrypt-existing` (#356): plain sets in SRC_DIR (default <repo>/backups) go to BACKUP_DIR as
# .age, markers alongside. Each encrypted file is decrypted back and compared by sha256 before
# its plaintext is deleted. Lists only unless APPLY=1. Unmarked old dumps are encrypted too.
encrypt_existing() {
  local src=${SRC_DIR:-$PWD/backups} apply=${APPLY:-} f base dump m mb n=0 bad=0 marker
  encrypting || { say "FAILED: no BACKUP_AGE_RECIPIENT (make backup-key-init first)" >&2; return 1; }
  age_bin >/dev/null || return 1
  need_identity || return 1
  [ -d "$src" ] || { say "Nothing to do: no $src"; return 0; }
  [ -n "$apply" ] || say "Dry run (APPLY=1 to do it): $src -> $BACKUP_DIR"
  mkdir -p "$BACKUP_DIR"
  PLAIN_DIR=$(mktemp -d); chmod 700 "$PLAIN_DIR"
  for f in "$src"/capitalos_*.dump; do
    [ -f "$f" ] || continue
    base=${f##*/}; dump="$BACKUP_DIR/$base"; n=$((n + 1))
    if [ -z "$apply" ]; then
      say "Would encrypt $f$([ -f "$f.verified" ] && echo ' (verified)' || echo ' (no .verified marker)') -> $dump.age (+ counts, data archive, markers)"
      continue
    fi
    while IFS= read -r m; do
      [ -f "$m" ] || continue
      mb=${m##*/}
      encrypt_file "$m" "$BACKUP_DIR/$mb.age" || { bad=$((bad + 1)); continue 2; }
      decrypt_file "$BACKUP_DIR/$mb.age" "$PLAIN_DIR/$mb" || { bad=$((bad + 1)); continue 2; }
      if [ "$(sha256_of "$m")" != "$(sha256_of "$PLAIN_DIR/$mb")" ]; then
        say "FAILED: $BACKUP_DIR/$mb.age does not decrypt to $m; its plaintext is kept" >&2
        rm -f "$PLAIN_DIR/$mb"; bad=$((bad + 1)); continue 2
      fi
      rm -f "$PLAIN_DIR/$mb"
    done < <(set_members "$f")
    for marker in verified failed restorable diff restore.log data-check; do
      [ -f "$f.$marker" ] || continue
      [ "$src" -ef "$BACKUP_DIR" ] || cp -p "$f.$marker" "$dump.$marker"
    done
    # Every member is safely encrypted: the plaintext goes (and, when moving, its markers).
    rm -f "$f" "$f.counts" "$(archive_of "$f")"
    [ "$src" -ef "$BACKUP_DIR" ] || for marker in verified failed restorable diff restore.log data-check; do rm -f "$f.$marker"; done
    [ -e "$dump.verified" ] && { index_add "$BACKUP_DIR" "$base" || true; }
    say "Encrypted $f -> $dump.age (each file decrypted back and compared)"
  done
  if [ -n "$apply" ]; then say "Done: $((n - bad)) of $n set(s) encrypted into $BACKUP_DIR$([ "$bad" -gt 0 ] && echo "; $bad left as they were (above)")"; offsite_sync
  else say "Dry run: $n set(s) would be encrypted into $BACKUP_DIR"; fi
  [ "$bad" -eq 0 ]
}

main() {
  cd "$(dirname "$0")/.."
  trap cleanup EXIT
  backup_env "$PWD"
  case "${1:-}" in
    create|verify|restore|check-data|offsite-check) DB_CONTAINER=${DB_CONTAINER:?DB_CONTAINER is required} ;;
  esac
  case "${1:-}" in
    create) local rc=0; create || rc=$?; write_status_quietly run "$rc"; return "$rc" ;;
    # A set is named by its dump; capitalos_<ts>.dump.age (what ls shows for an encrypted set) works too.
    verify) verify "${2%.age}" ;;
    restore) restore "${2%.age}" ;;
    open) open_cmd "${2%.age}" ;;
    check-data) check_live ;;
    prune) local rc=0; prune || rc=$?; [ -n "${DRY_RUN:-}" ] || write_status_quietly; return "$rc" ;;
    status) status; write_status_quietly ;;
    key-init) key_init ;;
    encrypt-existing) encrypt_existing ;;
    offsite-sync) offsite_sync ;;
    offsite-check) offsite_check ;;
    *) echo "usage: $0 create|verify <dump>|restore <dump>|open <dump>|check-data|prune|status|key-init|encrypt-existing|offsite-sync|offsite-check" >&2; exit 2 ;;
  esac
}

# Sourced by scripts/test-db-backup.sh for the pure functions; run otherwise.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then main "$@"; fi
