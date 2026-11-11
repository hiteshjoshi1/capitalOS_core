#!/bin/bash
# Tests for the backup script's data archive and retention logic (#155), run by `make lint`.
# Synthetic files in a throwaway directory only: no containers, no database, and never this
# checkout's data/ or backups/.
set -euo pipefail

src=$(cd "$(dirname "$0")/.." && pwd)
# Never the real backup folders, whatever the caller exported (the test instance exports them).
export BACKUP_DIR="" BACKUP_OFFSITE_DIR="" BACKUP_AGE_RECIPIENT="" BACKUP_AGE_IDENTITY=""
unset BACKUP_DIR BACKUP_AGE_IDENTITY
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

# ---- encrypted sets (#356): the pinned age, a throwaway key pair ----
if ! "$src/scripts/age-tool.sh" path >/dev/null 2>&1; then "$src/scripts/age-tool.sh" install >/dev/null; fi
keygen=$("$src/scripts/age-tool.sh" keygen-path)
BACKUP_AGE_IDENTITY=$tmp/key/age-identity.txt
mkdir -p "$tmp/key"
"$keygen" -o "$BACKUP_AGE_IDENTITY" 2>/dev/null
BACKUP_AGE_RECIPIENT=$("$keygen" -y "$BACKUP_AGE_IDENTITY")

# seal: a verified plain set (in its temp dir) becomes .age files + plain markers in the backup dir.
plainset=$tmp/plainset; enc=$tmp/enc; mkdir -p "$plainset"
cp "$rset"/capitalos_20261104_030000.* "$plainset/"
printf 'verified_at=x\n' >"$plainset/capitalos_20261104_030000.dump.verified"
seal_set "$plainset/capitalos_20261104_030000.dump" "$enc" >/dev/null
edump=$enc/capitalos_20261104_030000.dump
if [ "$(ls "$enc" | tr '\n' ' ')" = "capitalos_20261104_030000.data.tar.gz.age capitalos_20261104_030000.dump.age capitalos_20261104_030000.dump.counts.age capitalos_20261104_030000.dump.verified " ] &&
  ! grep -q 'synthetic dump' "$edump.age"; then
  ok "encrypt: the set is stored as .age files (dump, counts, archive), only the marker plain"
else bad "encrypt: the set is stored as .age files, only the marker plain ($(ls "$enc" | tr '\n' ' '))"; fi
if (OPEN_DIR=""; open_set "$edump" && [ "$(sha "$OPEN_DUMP")" = "$(sha "$plainset/capitalos_20261104_030000.dump")" ] &&
    [ "$(sha "$(archive_of "$OPEN_DUMP")")" = "$(sha "$plainset/capitalos_20261104_030000.data.tar.gz")" ] &&
    [ "$(stat -f %Lp "$OPEN_DIR" 2>/dev/null || stat -c %a "$OPEN_DIR")" = 700 ]; cleanup); then
  ok "open: decrypts every file of the set, byte for byte, into a private (700) temp dir"
else bad "open: decrypts every file of the set into a private temp dir"; fi

# restore() of an encrypted set, end to end against the fake Postgres above.
new_target
rc=0; out=$( (trap cleanup EXIT; BACKUP_DATA_DIR=$target DB_CONTAINER=fake restore "$edump") 2>&1) || rc=$?
if [ "$rc" = 0 ] && [ -f "$target/raw/7/upload.csv" ] && grep -q '^COMMIT;$' "$fake/applied.sql" &&
  printf '%s' "$out" | grep -q 'counts identical to the dump.s snapshot'; then
  ok "restore: an encrypted set restores (database and data/) with the private key"
else bad "restore: an encrypted set restores (exit $rc): $out"; fi

# No private key: restore changes nothing; verify fails without marking the set failed.
new_target
rc=0; out=$( (trap cleanup EXIT; BACKUP_AGE_IDENTITY=$tmp/nokey BACKUP_DATA_DIR=$target DB_CONTAINER=fake restore "$edump") 2>&1) || rc=$?
if [ "$rc" != 0 ] && [ -f "$target/current.txt" ] && printf '%s' "$out" | grep -q "key to open it isn't at $tmp/nokey"; then
  ok "restore: without the private key it stops, names the missing key, changes nothing"
else bad "restore: without the private key it stops and changes nothing (exit $rc): $out"; fi
rc=0; out=$( (trap cleanup EXIT; BACKUP_AGE_IDENTITY=$tmp/nokey DB_CONTAINER=fake verify "$edump") 2>&1) || rc=$?
if [ "$rc" != 0 ] && [ -f "$edump.verified" ] && [ ! -e "$edump.failed" ]; then
  ok "verify: without the private key it fails, but leaves the set's .verified marker alone"
else bad "verify: without the private key, markers untouched (exit $rc; $(ls "$enc" | tr '\n' ' '))"; fi
"$keygen" -o "$tmp/key/other.txt" 2>/dev/null
rc=0; out=$( (trap cleanup EXIT; BACKUP_AGE_IDENTITY=$tmp/key/other.txt BACKUP_DATA_DIR=$target DB_CONTAINER=fake restore "$edump") 2>&1) || rc=$?
if [ "$rc" != 0 ] && [ -f "$target/current.txt" ] && printf '%s' "$out" | grep -q "cannot decrypt .* with $tmp/key/other.txt: wrong or missing key"; then
  ok "restore: the wrong private key stops it, names the key, nothing changed"
else bad "restore: the wrong private key stops it (exit $rc): $out"; fi
rc=0; out=$( (trap cleanup EXIT; BACKUP_AGE_IDENTITY=$tmp/key/other.txt DB_CONTAINER=fake verify "$edump") 2>&1) || rc=$?
if [ "$rc" != 0 ] && [ -f "$edump.verified" ] && [ ! -e "$edump.failed" ] && [ ! -e "$edump.restore.log" ] && [ ! -e "$edump.age.failed" ] &&
  printf '%s' "$out" | grep -q "with $tmp/key/other.txt: wrong or missing key"; then
  ok "verify: the wrong private key fails, names the key, writes no .failed or log next to the good set"
else bad "verify: wrong key leaves the set alone (exit $rc; $(ls "$enc" | tr '\n' ' ')): $out"; fi
# Named by its .age file (what ls shows), through the script: the same set, the same answer.
rc=0; out=$(BACKUP_DIR=$enc BACKUP_AGE_IDENTITY=$tmp/key/other.txt DB_CONTAINER=fake "$src/scripts/db-backup.sh" verify "$edump.age" 2>&1) || rc=$?
if [ "$rc" != 0 ] && [ ! -e "$edump.age.failed" ] && [ ! -e "$edump.age.restore.log" ] && [ ! -e "$edump.failed" ] &&
  printf '%s' "$out" | grep -q "wrong or missing key"; then
  ok "verify <set>.dump.age: treated as the set, not as a plain dump (no pg_restore of ciphertext, no marker)"
else bad "verify <set>.dump.age (exit $rc; $(ls "$enc" | tr '\n' ' ')): $out"; fi
unset -f docker

# encrypt-existing: plain sets move into the backup dir encrypted, checked, plaintext gone.
src_plain=$tmp/oldplain; enc2=$tmp/enc2; mkdir -p "$src_plain"
cp "$rset"/capitalos_20261104_030000.* "$src_plain/"
printf 'verified_at=x\n' >"$src_plain/capitalos_20261104_030000.dump.verified"
printf 'old dump, no markers\n' >"$src_plain/capitalos_20240101_030000.dump"
printf 'log\n' >"$src_plain/backup.log"
before=$(ls "$src_plain" | sort)
(trap cleanup EXIT; SRC_DIR=$src_plain BACKUP_DIR=$enc2 encrypt_existing) >/dev/null
if [ "$(ls "$src_plain" | sort)" = "$before" ] && [ ! -e "$enc2/capitalos_20261104_030000.dump.age" ]; then
  ok "encrypt-existing: a dry run changes nothing"; else bad "encrypt-existing: a dry run changes nothing"; fi
want_sha=$(sha "$src_plain/capitalos_20261104_030000.dump")
(trap cleanup EXIT; APPLY=1 SRC_DIR=$src_plain BACKUP_DIR=$enc2 encrypt_existing) >/dev/null
if [ "$(ls "$src_plain")" = backup.log ] && [ -f "$enc2/capitalos_20261104_030000.dump.verified" ] &&
  [ -f "$enc2/capitalos_20240101_030000.dump.age" ] && [ ! -e "$enc2/capitalos_20240101_030000.dump.verified" ] &&
  (OPEN_DIR=""; open_set "$enc2/capitalos_20261104_030000.dump" && [ "$(sha "$OPEN_DUMP")" = "$want_sha" ]; cleanup); then
  ok "encrypt-existing APPLY=1: sets (and an unmarked old dump) encrypted with their markers, plaintext removed, other files left"
else bad "encrypt-existing APPLY=1 (left in src: $(ls "$src_plain" | tr '\n' ' '); enc: $(ls "$enc2" | tr '\n' ' '))"; fi
if (trap cleanup EXIT; BACKUP_AGE_RECIPIENT="" APPLY=1 SRC_DIR=$src_plain BACKUP_DIR=$enc2 encrypt_existing) >/dev/null 2>&1; then
  bad "encrypt-existing: refuses without a public key"; else ok "encrypt-existing: refuses without a public key"; fi

# prune treats encrypted sets like plain ones: the whole set goes.
b2=$tmp/b2; mkdir -p "$b2"
for d in 20250101 20261103; do
  for ext in .dump.age .dump.counts.age .dump.verified .data.tar.gz.age; do touch "$b2/capitalos_${d}_030000$ext"; done
done
BACKUP_DIR=$b2 BACKUP_TODAY=20261104 "$src/scripts/db-backup.sh" prune >/dev/null
if [ "$(ls "$b2" | sed 's/_030000.*//' | sort | uniq -c | awk '{print $2 ":" $1}' | tr '\n' ' ')" = "capitalos_20261103:4 " ]; then
  ok "prune: an encrypted set is removed whole (.age files and marker)"
else bad "prune: an encrypted set is removed whole (left: $(ls "$b2" | tr '\n' ' '))"; fi

# Where backups go (backup-env.sh): .env's BACKUP_DIR counts in the main checkout only.
repo=$tmp/repo
git init -q "$repo"
git -C "$repo" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
printf 'BACKUP_DIR="~/Somewhere/Backups"\nBACKUP_AGE_RECIPIENT=age1example\n' >"$repo/.env"
git -C "$repo" worktree add -q "$tmp/wt" 2>/dev/null
ln -s "$repo/.env" "$tmp/wt/.env"
got_main=$(unset BACKUP_DIR BACKUP_AGE_RECIPIENT BACKUP_AGE_IDENTITY; backup_env "$repo"; echo "$BACKUP_DIR|$BACKUP_AGE_RECIPIENT|$BACKUP_AGE_IDENTITY")
got_wt=$(unset BACKUP_DIR BACKUP_AGE_RECIPIENT BACKUP_AGE_IDENTITY; backup_env "$tmp/wt"; echo "$BACKUP_DIR")
got_env=$(BACKUP_DIR=/x; unset BACKUP_AGE_RECIPIENT BACKUP_AGE_IDENTITY; backup_env "$repo"; echo "$BACKUP_DIR")
if [ "$got_main" = "$HOME/Somewhere/Backups|age1example|$HOME/.capitalos/backup/age-identity.txt" ] &&
  [ "$got_wt" = "$tmp/wt/backups" ] && [ "$got_env" = /x ]; then
  ok "backup dir: .env in the main checkout (~ expanded); a worktree linking it keeps its own backups/; the environment wins"
else bad "backup dir: main '$got_main', worktree '$got_wt', env '$got_env'"; fi

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

# ---- off-site copy (#357) ----
# The backup dir: one encrypted verified set (enc2 from above), one plain verified set, one unmarked.
local_dir=$enc2
mkdir -p "$local_dir"
for ext in .dump .dump.counts .dump.verified .data.tar.gz; do printf 'plain\n' >"$local_dir/capitalos_20261001_030000$ext"; done
out=$( (BACKUP_DIR=$local_dir BACKUP_OFFSITE_DIR=$tmp/no-icloud/CapitalOS_backups offsite_sync) 2>&1) && rc=0 || rc=$?
if [ "$rc" = 0 ] && [ ! -e "$tmp/no-icloud" ] && printf '%s' "$out" | grep -q "WARNING (off-site copy): .*no-icloud does not exist (iCloud Drive not turned on?)"; then
  ok "off-site: no iCloud folder: a clear warning, no failure, nothing created"
else bad "off-site: no iCloud folder warns without failing (exit $rc): $out"; fi
mkdir -p "$tmp/icloud"
off=$tmp/icloud/CapitalOS_backups
(BACKUP_DIR=$local_dir BACKUP_OFFSITE_DIR=$off offsite_sync) >/dev/null 2>&1
if [ "$(ls "$off" | tr '\n' ' ')" = "capitalos_20261104_030000.data.tar.gz.age capitalos_20261104_030000.dump.age capitalos_20261104_030000.dump.counts.age capitalos_20261104_030000.dump.verified " ] &&
  [ "$(sha "$off/capitalos_20261104_030000.dump.age")" = "$(sha "$local_dir/capitalos_20261104_030000.dump.age")" ]; then
  ok "off-site: verified encrypted sets copied byte for byte; plain and unmarked sets never leave the Mac"
else bad "off-site: only verified encrypted sets copied (got: $(ls "$off" | tr '\n' ' '))"; fi
out=$( (BACKUP_DIR=$local_dir BACKUP_OFFSITE_DIR=$off offsite_sync) 2>&1)
printf '%s' "$out" | grep -q "Off-site: 0 set(s) copied" && ok "off-site: a set already there isn't copied again" || bad "off-site: idempotent ($out)"
chmod 500 "$off"
out=$( (BACKUP_DIR=$local_dir BACKUP_OFFSITE_DIR=$off offsite_sync) 2>&1) && rc=0 || rc=$?
chmod 700 "$off"
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q "can't write to $off"; then
  ok "off-site: an unwritable folder warns, never fails the backup"
else bad "off-site: unwritable folder warns (exit $rc): $out"; fi
touch -t 202611010300 "$off/capitalos_20261104_030000.dump.verified"
out=$(BACKUP_OFFSITE_DIR=$off offsite_status)
printf '%s' "$out" | grep -q "1 set(s), newest capitalos_20261104_030000.dump.verified .*WARNING: OLDER THAN 2 DAYS" &&
  ok "off-site status: the newest copy and a warning when it's over 2 days old" || bad "off-site status, stale: $out"
out=$(BACKUP_OFFSITE_DIR=$tmp/no-icloud/x offsite_status)
printf '%s' "$out" | grep -q "WARNING .* does not exist (iCloud Drive not turned on?)" &&
  ok "off-site status: a missing folder is a warning" || bad "off-site status, missing: $out"
# macOS under launchd may open files in iCloud Drive but not list the folder: nothing may list it.
# BACKUP_TEST_UNLISTABLE=1 makes listing fail; files stay reachable by name.
grep -qx capitalos_20261104_030000.dump "$off/.capitalos-index" &&
  ok "off-site: the sets copied are recorded in .capitalos-index" || bad "off-site: index written ($(cat "$off/.capitalos-index" 2>&1))"
off2=$tmp/icloud/Unlistable
mkdir -p "$off2"
out=$( (BACKUP_TEST_UNLISTABLE=1 BACKUP_DIR=$local_dir BACKUP_OFFSITE_DIR=$off2 offsite_sync) 2>&1) && rc=0 || rc=$?
if [ "$rc" = 0 ] && [ -f "$off2/capitalos_20261104_030000.dump.verified" ] && grep -qx capitalos_20261104_030000.dump "$off2/.capitalos-index" &&
  printf '%s' "$out" | grep -q "Off-site: 1 set(s) copied"; then
  ok "off-site, unlistable folder: the sync copies by name and writes the index"
else bad "off-site, unlistable folder: sync (exit $rc): $out"; fi
out=$( (BACKUP_TEST_UNLISTABLE=1 BACKUP_DIR=$local_dir BACKUP_OFFSITE_DIR=$off2 offsite_sync) 2>&1)
printf '%s' "$out" | grep -q "Off-site: 0 set(s) copied" && ok "off-site, unlistable folder: a set already there isn't copied again" || bad "off-site, unlistable: idempotent ($out)"
out=$(BACKUP_TEST_UNLISTABLE=1 BACKUP_OFFSITE_DIR=$off2 offsite_status)
printf '%s' "$out" | grep -q "1 set(s), newest capitalos_20261104_030000.dump.verified" &&
  ok "off-site status, unlistable folder: read from the index" || bad "off-site status, unlistable: $out"
rm -f "$off2/.capitalos-index"
out=$( (BACKUP_TEST_UNLISTABLE=1 BACKUP_DIR=$local_dir BACKUP_OFFSITE_DIR=$off2 offsite_sync) 2>&1) && rc=0 || rc=$?
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q "can't list $off2" && printf '%s' "$out" | grep -q "Off-site: 0 set(s) copied" &&
  grep -qx capitalos_20261104_030000.dump "$off2/.capitalos-index"; then
  ok "off-site, unlistable folder, no index: says so, finds sets by the local names, rebuilds the index"
else bad "off-site, no index, unlistable (exit $rc): $out"; fi
# prune keeps the same retention off-site.
b3=$tmp/b3; o3=$tmp/o3; mkdir -p "$b3" "$o3"
for d in 20250101 20261103; do
  for ext in .dump.age .dump.counts.age .dump.verified .data.tar.gz.age; do touch "$b3/capitalos_${d}_030000$ext" "$o3/capitalos_${d}_030000$ext"; done
done
printf '%s\n' capitalos_20250101_030000.dump capitalos_20261103_030000.dump >"$o3/.capitalos-offsite-index"
BACKUP_TEST_UNLISTABLE=1 BACKUP_DIR=$b3 BACKUP_OFFSITE_DIR=$o3 BACKUP_TODAY=20261104 "$src/scripts/db-backup.sh" prune >/dev/null
if [ "$(ls "$o3" | sed 's/_030000.*//' | sort -u | tr '\n' ' ')" = "capitalos_20261103 " ] && [ "$(ls "$b3" | sed 's/_030000.*//' | sort -u | tr '\n' ' ')" = "capitalos_20261103 " ] &&
  [ "$(cat "$o3/.capitalos-index")" = capitalos_20261103_030000.dump ]; then
  ok "off-site: prune applies the same retention off-site, by the index (no listing), and rewrites it"
else bad "off-site: prune off-site (local: $(ls "$b3" | tr '\n' ' '); off-site: $(ls "$o3" | tr '\n' ' '); index: $(cat "$o3/.capitalos-index"))"; fi

# #383: one backup folder in iCloud Drive, which the 03:00 job may not list. BACKUP_DIR itself is
# then driven by its index (.capitalos-index, or the pre-#383 off-site one, adopted).
b4=$tmp/b4; mkdir -p "$b4"
mkset() { local ext; for ext in .dump.age .dump.counts.age .dump.verified .data.tar.gz.age; do touch "$1/capitalos_${2}_030000$ext"; done; }
mkset "$b4" 20250101; mkset "$b4" 20261103
printf '%s\n' capitalos_20250101_030000.dump capitalos_20261103_030000.dump >"$b4/.capitalos-offsite-index"
out=$(BACKUP_TEST_UNLISTABLE=local BACKUP_DIR=$b4 backup_newest_verified)
[ "$out" = "$b4/capitalos_20261103_030000.dump" ] &&
  ok "backup folder, unlistable: the newest set comes from the adopted pre-#383 index (deploy, status, test instance)" || bad "newest from index: $out"
out=$(BACKUP_TEST_UNLISTABLE=local BACKUP_DIR=$b4 verified_sets | tr '\n' ' ')
[ "$out" = "$b4/capitalos_20250101_030000.dump $b4/capitalos_20261103_030000.dump " ] &&
  ok "backup folder, unlistable: verified sets from the index" || bad "verified sets from index: $out"
mkset "$b4" 20261104
(BACKUP_TEST_UNLISTABLE=local BACKUP_DIR=$b4 index_add "$b4" capitalos_20261104_030000.dump)
[ "$(tr '\n' ' ' <"$b4/.capitalos-index")" = "capitalos_20250101_030000.dump capitalos_20261103_030000.dump capitalos_20261104_030000.dump " ] &&
  ok "backup folder, unlistable: a new set is recorded in .capitalos-index (create)" || bad "index_add: $(cat "$b4/.capitalos-index" 2>&1)"
out=$( (BACKUP_TEST_UNLISTABLE=local BACKUP_DIR=$b4 status) 2>&1)
printf '%s' "$out" | grep -q "Newest verified backup: $b4/capitalos_20261104_030000.dump (encrypted)" &&
  printf '%s' "$out" | grep -q "Verified backups kept: 3, 3 encrypted" &&
  ok "backup folder, unlistable: status reads the index" || bad "status from index: $out"
BACKUP_TEST_UNLISTABLE=local BACKUP_DIR=$b4 BACKUP_TODAY=20261104 "$src/scripts/db-backup.sh" prune >/dev/null 2>&1
if [ ! -e "$b4/capitalos_20250101_030000.dump.age" ] && [ -e "$b4/capitalos_20261103_030000.dump.age" ] &&
  [ "$(tr '\n' ' ' <"$b4/.capitalos-index")" = "capitalos_20261103_030000.dump capitalos_20261104_030000.dump " ]; then
  ok "backup folder, unlistable: prune works by the index and rewrites it"
else bad "prune by index: $(ls "$b4" | tr '\n' ' '); index: $(cat "$b4/.capitalos-index")"; fi
b5=$tmp/b5; mkdir -p "$b5"; mkset "$b5" 20261104
out=$( (BACKUP_TEST_UNLISTABLE=local BACKUP_DIR=$b5 verified_sets) 2>&1)
printf '%s' "$out" | grep -q "can't list $b5 .*no .capitalos-index yet" &&
  ok "backup folder, unlistable, no index: says so (and names the fix)" || bad "no index warning: $out"
(BACKUP_TEST_UNLISTABLE=local BACKUP_DIR=$b5 BACKUP_TODAY=20261104 "$src/scripts/db-backup.sh" prune) >/dev/null 2>&1 || true
[ ! -e "$b5/.capitalos-index" ] && [ -e "$b5/capitalos_20261104_030000.dump.age" ] &&
  ok "backup folder, unlistable, no index: prune removes nothing and writes no empty index" || bad "prune without index: $(ls -A "$b5" | tr '\n' ' ')"
(BACKUP_DIR=$b5 verified_sets >/dev/null)
[ "$(cat "$b5/.capitalos-index" 2>/dev/null)" = capitalos_20261104_030000.dump ] &&
  ok "backup folder: a listing (Terminal) rebuilds the index" || bad "index rebuild from listing: $(cat "$b5/.capitalos-index" 2>&1)"

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
