#!/bin/bash
# Tests for the migration lint (scripts/check-migrations.py, #158), run by `make lint`.
# Synthetic migration files in a throwaway directory only.
set -euo pipefail

src=$(cd "$(dirname "$0")/.." && pwd)
lint="${PYTHON:-python3} $src/scripts/check-migrations.py"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

pass=0 fail=0
ok() { pass=$((pass + 1)); echo "ok   $1"; }
bad() { fail=$((fail + 1)); echo "FAIL $1"; }

# case <name> <expect: pass|fail> <file>=<content> ...
case_dir() {
  local name=$1 expect=$2 dir="$tmp/$1"
  shift 2
  mkdir -p "$dir"
  for spec in "$@"; do printf '%b' "${spec#*=}" >"$dir/${spec%%=*}"; done
  if $lint "$dir" >"$dir.out" 2>&1; then got=pass; else got=fail; fi
  if [ "$got" = "$expect" ]; then ok "$name"; else bad "$name (expected $expect, got $got)"; sed 's/^/     /' "$dir.out"; fi
}

case_dir clean pass \
  '001_init.sql=CREATE TABLE t (id int);\n' \
  '002_more.sql=ALTER TABLE t ADD COLUMN x text;\n'
case_dir plpgsql_blocks_are_fine pass \
  '001_do.sql=DO $$\nBEGIN\n  IF true THEN\n    RAISE NOTICE '"'"'x'"'"';\n  END IF;\nEND;\n$$;\n' \
  '002_fn.sql=CREATE FUNCTION f() RETURNS trigger AS $body$\nBEGIN\n  RETURN NEW;\nEND;\n$body$ LANGUAGE plpgsql;\n' \
  '003_case.sql=SELECT CASE WHEN true THEN 1\n  ELSE 0\nEND;\n'
case_dir comments_and_strings_are_ignored pass \
  '001_c.sql=-- BEGIN;\n/* COMMIT; */\nSELECT '"'"'COMMIT;'"'"';\n'
case_dir begin_rejected fail '001_b.sql=BEGIN;\nCREATE TABLE t (id int);\n'
case_dir commit_rejected fail '001_c.sql=CREATE TABLE t (id int);\nCOMMIT;\n'
case_dir start_transaction_rejected fail '001_s.sql=START TRANSACTION;\nSELECT 1;\n'
case_dir rollback_rejected fail '001_r.sql=SELECT 1; ROLLBACK;\n'
case_dir duplicate_prefix_rejected fail '005_a.sql=SELECT 1;\n' '005_b.sql=SELECT 2;\n'
case_dir bad_name_rejected fail '007_Bad-Name.sql=SELECT 1;\n'
case_dir allow_listed_028_passes pass \
  '028_crypto_base_asset.sql=BEGIN;\nSELECT 1;\nCOMMIT;\n' \
  '028_fix_dbs_salary_type.sql=SELECT 1;\n'
case_dir third_028_rejected fail \
  '028_crypto_base_asset.sql=SELECT 1;\n' '028_fix_dbs_salary_type.sql=SELECT 1;\n' '028_new.sql=SELECT 1;\n'
case_dir non_migration_files_ignored pass \
  '001_init.sql=SELECT 1;\n' 'seed_dummy.sql=BEGIN;\nSELECT 1;\nCOMMIT;\n' 'README.md=# x\n'

# The real migrations pass.
if $lint "$src/migrations" >/dev/null 2>&1; then ok "repo migrations"; else bad "repo migrations"; $lint "$src/migrations" || true; fi

echo "check-migrations tests: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
