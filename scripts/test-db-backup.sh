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
