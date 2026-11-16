#!/bin/bash
# Tests for scripts/secure-perms.sh (#442): check reports wide modes, apply fixes them, dry run
# changes nothing. Runs against a throwaway repo copy and HOME, never the real files.
set -u
src=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
cleanup() { chmod -R u+rwx "$tmp" 2>/dev/null; find "$tmp" -mindepth 1 -delete 2>/dev/null; rmdir "$tmp" 2>/dev/null; }
trap cleanup EXIT
pass=0; fail=0
ok() { echo "ok   $1"; pass=$((pass+1)); }
bad() { echo "FAIL $1" >&2; fail=$((fail+1)); }
repo=$tmp/repo; home=$tmp/home
mkdir -p "$repo/scripts" "$repo/data/raw" "$repo/state" "$home/.capitalos/backup"
cp "$src/scripts/secure-perms.sh" "$src/scripts/backup-env.sh" "$repo/scripts/"
echo "SECRET=x" >"$repo/.env"; touch "$home/.capitalos/backup/age-identity.txt"
chmod 644 "$repo/.env" "$home/.capitalos/backup/age-identity.txt"
chmod 755 "$repo/data" "$repo/state" "$home/.capitalos" "$home/.capitalos/backup"
mode_of() { stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1"; }  # GNU first: on Linux `stat -f` reports the filesystem
run() { HOME=$home BACKUP_DIR= "$repo/scripts/secure-perms.sh" "$@"; }

out=$(run check); rc=$?
[ "$rc" = 1 ] && printf '%s' "$out" | grep -q "$repo/.env is 644 (wanted 600)" && printf '%s' "$out" | grep -q "$repo/data is 755" &&
  ok "check: wide .env and data/ are reported, exit 1" || bad "check: rc=$rc $out"
DRY_RUN=1 run apply >/dev/null
[ "$(mode_of "$repo/.env")" = 644 ] && ok "dry run changes nothing" || bad "dry run changed .env to $(mode_of "$repo/.env")"
run apply >/dev/null
[ "$(mode_of "$repo/.env")" = 600 ] && [ "$(mode_of "$repo/data")" = 700 ] && [ "$(mode_of "$repo/state")" = 700 ] &&
  [ "$(mode_of "$home/.capitalos")" = 700 ] && [ "$(mode_of "$home/.capitalos/backup/age-identity.txt")" = 600 ] &&
  ok "apply: .env and the key 600, folders 700" || bad "apply: .env $(mode_of "$repo/.env") data $(mode_of "$repo/data") home $(mode_of "$home/.capitalos")"
out=$(run check); rc=$?
[ "$rc" = 0 ] && [ -z "$out" ] && ok "check after apply: quiet, exit 0" || bad "check after apply: rc=$rc $out"
chmod 400 "$repo/.env"
run check >/dev/null && ok "stricter than wanted (400) is fine" || bad "400 reported as wide"
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
