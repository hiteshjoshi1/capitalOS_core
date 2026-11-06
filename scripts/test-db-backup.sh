#!/bin/bash
# Tests for the backup script's data archive and retention logic (#155), run by `make lint`.
# Synthetic files in a throwaway directory only: no containers, no database, and never this
# checkout's data/ or backups/.
set -euo pipefail

src=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
# shellcheck source=db-backup.sh
. "$src/scripts/db-backup.sh"

pass=0 fail=0
ok() { pass=$((pass + 1)); echo "ok   $1"; }
bad() { fail=$((fail + 1)); echo "FAIL $1"; }
sha() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -c1-64; else shasum -a 256 "$1" | cut -c1-64; fi; }

# A synthetic data/: one upload, one IBKR Flex XML, a fixture, and the API's signing key.
data=$tmp/data
mkdir -p "$data/raw/7" "$data/broker_raw/ibkr_flex" "$data/fixtures"
printf 'date,amount\n2026-01-02,10.00\n' >"$data/raw/7/upload.csv"
printf '<FlexQueryResponse queryName="synthetic"/>\n' >"$tmp/flex.xml"
flex_hash=$(sha "$tmp/flex.xml")
mv "$tmp/flex.xml" "$data/broker_raw/ibkr_flex/$flex_hash.xml"
printf 'a,b\n' >"$data/fixtures/sample.csv"
printf 'synthetic-secret\n' >"$data/.auth_secret"
up_hash=$(sha "$data/raw/7/upload.csv")

good_rows() {
  echo "import_jobs|7|$up_hash|/app/data/raw/7/upload.csv"
  echo "import_jobs|8||"                                                   # copy failed: no path, no hash
  echo "import_jobs|9|0123456789abcdef0123456789abcdef|/app/data/uploads/DUMMY_x.csv"   # demo seed (md5)
  echo "raw_broker_documents|1|$flex_hash|/app/data/broker_raw/ibkr_flex/$flex_hash.xml"
  echo "raw_broker_documents|2|$up_hash|data/raw/7/upload.csv"             # repo-relative path
}

expect_check() {  # <description> <expected exit 0|1> <grep pattern> <rows file> <dir>
  local d=$1 want=$2 pattern=$3 out rc=0
  out=$(check_data "$4" "$5") || rc=1
  if [ "$rc" = "$want" ] && printf '%s\n' "$out" | grep -qE -- "$pattern"; then ok "$d"
  else bad "$d (exit $rc, got: $out)"; fi
}

good_rows >"$tmp/rows"
expect_check "every recorded file present with its sha256: passes" 0 \
  '^RESULT checked=3 no_file=2 files=4 failed=0$' "$tmp/rows" "$data"

{ good_rows; echo "import_jobs|10|$up_hash|/app/data/raw/10/upload.csv"; } >"$tmp/rows"
expect_check "a row whose file is missing: fails, named" 1 'MISSING import_jobs id=10: raw/10/upload.csv' "$tmp/rows" "$data"

{ good_rows; echo "import_jobs|11|$flex_hash|/app/data/raw/7/upload.csv"; } >"$tmp/rows"
expect_check "a file whose sha256 differs: fails, named" 1 'CHANGED import_jobs id=11: raw/7/upload.csv' "$tmp/rows" "$data"

{ good_rows; echo "import_jobs|12|$up_hash|/somewhere/else/upload.csv"; } >"$tmp/rows"
expect_check "a path outside data/: fails" 1 'OUTSIDE import_jobs id=12' "$tmp/rows" "$data"

{ good_rows; echo "import_jobs|13|$up_hash|/app/data/../data/raw/7/upload.csv"; } >"$tmp/rows"
expect_check "a path that climbs out with ..: fails" 1 'OUTSIDE import_jobs id=13' "$tmp/rows" "$data"

{ good_rows; echo "import_jobs|14|$(printf '%s' "$up_hash" | tr a-f A-F)|/app/data/raw/7/upload.csv"; } >"$tmp/rows"
expect_check "an upper-case recorded hash still matches" 0 'failed=0$' "$tmp/rows" "$data"

# Archive round trip: the archive holds data/'s contents minus the signing key.
mkdir -p "$tmp/backups"
BACKUP_DATA_DIR=$data make_archive "$tmp/backups/capitalos_20261104_030000.data.tar.gz" >/dev/null
mkdir "$tmp/unpacked"
tar -xzf "$tmp/backups/capitalos_20261104_030000.data.tar.gz" -C "$tmp/unpacked"
good_rows >"$tmp/rows"
expect_check "the archive unpacks to a dir that passes the check" 0 'files=3 failed=0$' "$tmp/rows" "$tmp/unpacked"
if [ ! -e "$tmp/unpacked/.auth_secret" ] && [ -f "$tmp/unpacked/fixtures/sample.csv" ]; then ok "the archive leaves out the signing key, keeps the rest"
else bad "the archive leaves out the signing key, keeps the rest"; fi
[ "$(archive_of backups/capitalos_20261104_030000.dump)" = backups/capitalos_20261104_030000.data.tar.gz ] &&
  ok "the archive is named after its dump" || bad "the archive is named after its dump"
if BACKUP_DATA_DIR=$tmp/none make_archive "$tmp/empty.data.tar.gz" >/dev/null && [ -z "$(tar -tzf "$tmp/empty.data.tar.gz" | grep -v '^\./$' || true)" ]; then
  ok "no data/ yet: an empty archive"; else bad "no data/ yet: an empty archive"; fi

# Restore swap: the current data/ is moved aside (never deleted), the signing key carried over.
cp -R "$tmp/unpacked" "$tmp/stage"
printf 'only-in-current\n' >"$data/new-since-backup.txt"
BACKUP_DATA_DIR=$data swap_in_data "$tmp/stage" 20261104_120000 >/dev/null
if [ -f "$tmp/data.pre-restore-20261104_120000/new-since-backup.txt" ] && [ ! -e "$data/new-since-backup.txt" ] &&
  [ -f "$data/raw/7/upload.csv" ] && [ "$(cat "$data/.auth_secret")" = synthetic-secret ] && [ ! -e "$tmp/stage" ]; then
  ok "restore: data/ replaced, the old one kept aside, the signing key kept"
else bad "restore: data/ replaced, the old one kept aside, the signing key kept"; fi
mkdir "$tmp/stage2"
if BACKUP_DATA_DIR=$data swap_in_data "$tmp/stage2" 20261104_120000 >/dev/null 2>&1; then bad "restore: an existing aside folder is never overwritten"
elif [ -d "$tmp/stage2" ] && [ -f "$data/raw/7/upload.csv" ]; then ok "restore: an existing aside folder is never overwritten"
else bad "restore: an existing aside folder is never overwritten (state changed)"; fi
mkdir "$tmp/stage3"
if BACKUP_DATA_DIR=$tmp/absent swap_in_data "$tmp/stage3" 20261104_130000 >/dev/null && [ -d "$tmp/absent" ]; then
  ok "restore: no data/ yet: the restored one is put in place"; else bad "restore: no data/ yet: the restored one is put in place"; fi

# Privileges on restore (#233): grants to a role the target lacks are left out, not fatal.
schema=$tmp/schema.sql
cat >"$schema" <<'SQL'
--
-- PostgreSQL database dump
--

\restrict synthetickey

SET statement_timeout = 0;

--
-- Name: import_jobs; Type: TABLE; Schema: public; Owner: capitalos
--

CREATE TABLE public.import_jobs (
    id integer NOT NULL
);

--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: pg_database_owner
--

GRANT USAGE ON SCHEMA public TO capitalos_mcp_ro;

--
-- Name: TABLE import_jobs; Type: ACL; Schema: public; Owner: capitalos
--

REVOKE ALL ON TABLE public.import_jobs FROM PUBLIC;
GRANT SELECT ON TABLE public.import_jobs TO capitalos_mcp_ro;
GRANT SELECT ON TABLE public.import_jobs TO "Report Reader";

--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: public; Owner: capitalos
--

ALTER DEFAULT PRIVILEGES FOR ROLE capitalos IN SCHEMA public GRANT SELECT ON TABLES TO capitalos_mcp_ro;

--
-- PostgreSQL database dump complete
--

\unrestrict synthetickey
SQL
printf 'capitalos\nReport Reader\n' >"$tmp/roles"
kept=$(acl_statements "$tmp/roles" "$tmp/skipped" <"$schema")
if [ "$kept" = "$(printf 'REVOKE ALL ON TABLE public.import_jobs FROM PUBLIC;\nGRANT SELECT ON TABLE public.import_jobs TO "Report Reader";')" ] &&
  [ "$(grep -c '^SKIPPED capitalos_mcp_ro|' "$tmp/skipped")" = 3 ]; then
  ok "privileges: statements for a missing role are left out and listed, the rest kept (quoted names too)"
else bad "privileges: missing role left out, rest kept (kept: $kept; skipped: $(cat "$tmp/skipped"))"; fi
printf 'capitalos\ncapitalos_mcp_ro\nReport Reader\n' >"$tmp/roles-all"
rm -f "$tmp/skipped"
if [ "$(acl_statements "$tmp/roles-all" "$tmp/skipped" <"$schema" | grep -c .)" = 5 ] && [ ! -s "$tmp/skipped" ]; then
  ok "privileges: every role present: every privilege statement kept, none listed"
else bad "privileges: every role present: every statement kept"; fi
printf -- '-- Name: TABLE x; Type: ACL; Schema: public; Owner: capitalos\nSET SESSION AUTHORIZATION gone;\nGRANT SELECT ON TABLE public.x TO capitalos;\nRESET SESSION AUTHORIZATION;\nGRANT SELECT ON TABLE public.y TO capitalos;\n' >"$tmp/as.sql"
if [ "$(acl_statements "$tmp/roles" "$tmp/skipped" <"$tmp/as.sql")" = "GRANT SELECT ON TABLE public.y TO capitalos;" ]; then
  ok "privileges: grants made as a missing role are left out up to its RESET"
else bad "privileges: grants made as a missing role are left out"; fi
printf -- '-- Name: TABLE x; Type: ACL; Schema: public; Owner: capitalos\nSECURITY LABEL ON TABLE public.x IS $$a$$;\n' >"$tmp/odd.sql"
if acl_statements "$tmp/roles" "$tmp/skipped" <"$tmp/odd.sql" >/dev/null 2>&1; then
  bad "privileges: an unknown statement form fails instead of being dropped"
else ok "privileges: an unknown statement form fails instead of being dropped"; fi

# restore() end to end against a fake Postgres (a docker function): the target has no MCP role.
fake=$tmp/fake; mkdir -p "$fake"
fake_roles=$(printf 'capitalos\nReport Reader')   # no capitalos_mcp_ro
fake_psql_fails=""
docker() {  # docker exec [-i] <container> <command> <args...>
  [ "$1" = exec ] || return 99
  shift; [ "$1" = -i ] && shift; shift
  local cmd=$1 sql
  case "$cmd" in
    pg_restore)
      cat >/dev/null
      case " $* " in
        *" --schema-only "*) cat "$schema" ;;
        *" --no-privileges "*) printf '\\restrict k\nCREATE TABLE public.import_jobs (id integer);\n\\unrestrict k\n' ;;
        *) echo "unexpected pg_restore $*" >&2; return 1 ;;
      esac ;;
    psql)
      sql=${*: -1}
      case " $* " in
        *" -c "*)
          case "$sql" in
            *pg_roles*) printf '%s\n' "$fake_roles" ;;
            *to_regclass*) echo t ;;
            *"FROM import_jobs"*) echo "import_jobs|7|$up_hash|/app/data/raw/7/upload.csv" ;;
            *"FROM raw_broker_documents"*) echo "raw_broker_documents|1|$flex_hash|/app/data/broker_raw/ibkr_flex/$flex_hash.xml" ;;
          esac ;;
        *)
          cat >"$fake/applied.sql"
          [ -z "$fake_psql_fails" ] || { echo 'ERROR:  synthetic failure' >&2; return 3; }
          # Like Postgres: a grant to a role that doesn't exist is an error.
          if grep -q 'TO capitalos_mcp_ro;' "$fake/applied.sql" && ! printf '%s\n' "$fake_roles" | grep -qx capitalos_mcp_ro; then
            echo 'ERROR:  role "capitalos_mcp_ro" does not exist' >&2; return 3
          fi ;;
      esac ;;
    *) echo "unexpected docker exec $cmd" >&2; return 99 ;;
  esac
}
target=$tmp/target; rset=$tmp/rset
new_target() {
  rm -rf "$target" "$target".pre-restore-*; mkdir -p "$target"
  printf 'current-only\n' >"$target/current.txt"; printf 'target-secret\n' >"$target/.auth_secret"
}
mkdir -p "$rset"
printf 'synthetic dump\n' >"$rset/capitalos_20261104_030000.dump"
printf 'import_jobs|1\n' >"$rset/capitalos_20261104_030000.dump.counts"
cp "$tmp/backups/capitalos_20261104_030000.data.tar.gz" "$rset/"
run_restore() { (trap cleanup EXIT; BACKUP_DATA_DIR=$target DB_CONTAINER=fake restore "$rset/capitalos_20261104_030000.dump") 2>&1; }

new_target
rc=0; out=$(run_restore) || rc=$?
if [ "$rc" = 0 ] && [ -f "$target/raw/7/upload.csv" ] && [ ! -e "$target/current.txt" ] &&
  [ -f "$(echo "$target".pre-restore-*)/current.txt" ] && [ "$(cat "$target/.auth_secret")" = target-secret ] &&
  ! grep -q capitalos_mcp_ro "$fake/applied.sql" && printf '%s' "$out" | grep -q "Left out 3 privilege statement(s) .*capitalos_mcp_ro"; then
  ok "restore: a target without the MCP role completes, data/ restored, the role's grants left out and named"
else bad "restore: a target without the MCP role completes (exit $rc): $out"; fi
if [ "$(head -1 "$fake/applied.sql")" = "BEGIN;" ] && [ "$(tail -1 "$fake/applied.sql")" = "COMMIT;" ] &&
  grep -q 'pg_default_acl' "$fake/applied.sql"; then
  ok "restore: one transaction, the target's default grants taken back before the dump's own"
else bad "restore: one transaction with the default-grant reset"; fi
if grep -q "row counts differ from the dump''s snapshot" "$fake/applied.sql" && grep -qF '$expected$import_jobs|1$expected$' "$fake/applied.sql" &&
  printf '%s' "$out" | grep -q 'counts identical to the dump.s snapshot'; then
  ok "restore: the snapshot counts are checked inside the transaction, before COMMIT"
else bad "restore: the snapshot counts are checked before COMMIT: $out"; fi

new_target
fake_roles=$(printf 'capitalos\ncapitalos_mcp_ro\nReport Reader')
rc=0; out=$(run_restore) || rc=$?
reset_line=$(grep -n 'pg_default_acl' "$fake/applied.sql" | head -1 | cut -d: -f1)
grant_line=$(grep -n 'TO capitalos_mcp_ro;' "$fake/applied.sql" | head -1 | cut -d: -f1)
if [ "$rc" = 0 ] && [ "$(grep -c 'TO capitalos_mcp_ro;' "$fake/applied.sql")" = 3 ] && [ "$reset_line" -lt "$grant_line" ] &&
  ! printf '%s' "$out" | grep -q 'Left out'; then
  ok "restore: a target with the MCP role gets the dump's grants to it, after the reset"
else bad "restore: a target with the MCP role gets its grants (exit $rc): $out"; fi

new_target
fake_psql_fails=1
rc=0; out=$(run_restore) || rc=$?
if [ "$rc" != 0 ] && [ -f "$target/current.txt" ] && [ ! -e "$target/raw" ] && ! ls -d "$target".pre-restore-* >/dev/null 2>&1 &&
  ! ls -d "$target".restore-* >/dev/null 2>&1; then
  ok "restore: a failed database restore leaves data/ untouched (and no staging folder behind)"
else bad "restore: a failed database restore leaves data/ untouched (exit $rc): $out"; fi
fake_psql_fails=""
unset -f docker

# Retention: every set from the last 14 days, the first of each of the last 12 months, the newest.
names() { for d in "$@"; do echo "$tmp/b/capitalos_${d}_030000.dump"; done; }
expect_pruned() {  # <description> <today> <expected pruned dates, space separated> <dates...>
  local d=$1 today=$2 want=$3 got; shift 3
  got=$(names "$@" | retention_prune_list "$today" "$(date_minus_days "$today" 14)" 12 | sed 's/.*capitalos_\([0-9]*\)_.*/\1/' | tr '\n' ' ' | sed 's/ $//')
  if [ "$got" = "$want" ]; then ok "$d"; else bad "$d (want '$want', got '$got')"; fi
}
[ "$(date_minus_days 20261104 14)" = 20261021 ] && ok "14 days before 2026-11-04 is 2026-10-21" || bad "date arithmetic ($(date_minus_days 20261104 14))"
[ "$(date_minus_days 20260310 14)" = 20260224 ] && ok "date arithmetic across February" || bad "date arithmetic across February"
expect_pruned "retention: 14 days + first of each month for 12 months" 20261104 \
  "20251015 20251102 20251220 20261002 20261020" \
  20251015 20251102 20251203 20251220 20260101 20261001 20261002 20261020 20261021 20261103 20261104
expect_pruned "retention: the newest set is kept even when old" 20261104 "20251001" 20251001 20251002
expect_pruned "retention: the first verified set of a month, whatever its day" 20261104 "" 20260917 20261104
if printf '%s\n' "$tmp/b/capitalos_manual.dump" | retention_prune_list 20261104 20261021 12 | grep -q .; then
  bad "retention: an undatable name is kept"; else ok "retention: an undatable name is kept"; fi
expect_pruned "retention: a January reaches back into the previous year" 20260115 "20250101" \
  20250101 20250201 20250301 20251201 20260115

# prune end to end: a set goes with its archive; unmarked dumps stay; DRY_RUN changes nothing.
b=$tmp/b; mkdir -p "$b"
for d in 20250101 20251220 20251221 20261103; do
  for ext in .dump .dump.counts .dump.verified .data.tar.gz; do touch "$b/capitalos_${d}_030000$ext"; done
done
touch "$b/capitalos_20240101_030000.dump"                      # made before markers existed
run_prune() { BACKUP_DIR=$b BACKUP_TODAY=20261104 "$src/scripts/db-backup.sh" prune; }
before=$(ls "$b" | sort)
out=$(DRY_RUN=1 run_prune)
if [ "$(ls "$b" | sort)" = "$before" ] && printf '%s' "$out" | grep -q 'Would prune .*capitalos_20251221_030000.dump'; then
  ok "prune DRY_RUN=1: lists, removes nothing"; else bad "prune DRY_RUN=1: lists, removes nothing ($out)"; fi
run_prune >/dev/null
left=$(ls "$b" | sed 's/_030000.*//' | sort | uniq -c | awk '{print $2 ":" $1}' | tr '\n' ' ')
if [ "$left" = "capitalos_20240101:1 capitalos_20251220:4 capitalos_20261103:4 " ]; then
  ok "prune: whole sets removed (dump, counts, marker, archive); unmarked dump kept"
else bad "prune: whole sets removed; unmarked dump kept (left: $left)"; fi

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
