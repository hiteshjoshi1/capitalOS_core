#!/bin/bash
# Tests for the checkout guard (#44), run by `make lint`. They only use dry runs and
# parse-time checks (no containers), in a throwaway clone with its own worktree, so they
# never touch this checkout's stack.
set -euo pipefail
# Run as `make lint` inside a worktree, the outer make exports that worktree's ISO_* (and
# MAKEFLAGS); the throwaway checkouts must derive their own.
unset ISO_NAME ISO_API_PORT ISO_PG_PORT ISO_GRAFANA_PORT ISO_LOKI_PORT ISO_WEB_PORT MAKEFLAGS MAKELEVEL MFLAGS

src=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
cleanup() {
  git -C "$tmp/main" worktree remove --force "$tmp/wt" >/dev/null 2>&1 || true
  rm -f "$tmp/main/docker-compose.oss-test.yml"
  rm -fr "$tmp/main" "$tmp/wt"
  rmdir "$tmp" 2>/dev/null || true
}
trap cleanup EXIT

git clone -q --local --no-hardlinks "$src" "$tmp/main"
# The current, possibly uncommitted Makefile and override, so the test checks what's in the tree.
cp "$src/Makefile" "$src/docker-compose.isolated.yml" "$tmp/main/"
# Simulate the real-data machine: the git-ignored override exists in the main checkout.
printf 'services: {}\n' >"$tmp/main/docker-compose.oss-test.yml"
git -C "$tmp/main" checkout -q -B main
git -C "$tmp/main" worktree add -q -b feature/issue-0-guard-test "$tmp/wt" main
cp "$src/Makefile" "$src/docker-compose.isolated.yml" "$tmp/wt/"

pass=0 fail=0
ok() { pass=$((pass + 1)); echo "ok   $1"; }
bad() { fail=$((fail + 1)); echo "FAIL $1"; }
expect_refused() {   # <description> <dir> <make args...>
  local d=$1 dir=$2; shift 2
  if out=$(make -s -n -C "$dir" "$@" 2>&1); then bad "$d (was allowed: $out)"
  elif printf '%s' "$out" | grep -q 'Refusing'; then ok "$d"
  else bad "$d (failed without the guard's message: $out)"; fi
}
expect_command() {   # <description> <dir> <grep pattern> <make args...>
  local d=$1 dir=$2 pattern=$3; shift 3
  if out=$(make -s -n -C "$dir" "$@" 2>&1) && printf '%s' "$out" | grep -qE -- "$pattern"; then ok "$d"
  else bad "$d (got: $out)"; fi
}

M=$tmp/main W=$tmp/wt
expect_command "main on main: up drives the real-data project" "$M" '-p capitalos-oss-test .*up -d' up
expect_refused "main on a feature branch: up refused" "$M" up CURRENT_BRANCH=feature/x
expect_refused "main on a feature branch: db-migrate refused" "$M" db-migrate CURRENT_BRANCH=feature/x
expect_refused "main on a feature branch: api-rebuild refused" "$M" api-rebuild CURRENT_BRANCH=feature/x
expect_command "main on a feature branch with ALLOW_BRANCH=1: allowed" "$M" '-p capitalos-oss-test' up CURRENT_BRANCH=feature/x ALLOW_BRANCH=1
expect_command "main on a feature branch: read-only targets allowed" "$M" 'REAL DATA' where CURRENT_BRANCH=feature/x
expect_command "worktree: up drives its own project via the isolated file" "$W" '-p capitalos-wt-wt -f docker-compose.yml -f docker-compose.isolated.yml up' up
expect_command "worktree: a copied .env's COMPOSE_* are neutralised" "$W" '^COMPOSE_PROJECT_NAME= COMPOSE_FILE= docker compose' up
expect_refused "worktree forced onto the real project: refused" "$W" up ISO_NAME=capitalos-oss-test
expect_refused "worktree onto the real API port: refused" "$W" up ISO_API_PORT=8011
expect_refused "worktree onto the real Postgres port: refused" "$W" up ISO_PG_PORT=5433
expect_command "worktree: test tooling never starts Postgres (--no-deps)" "$W" 'run --rm --build --no-deps api-dev pytest' test-backend
if make -s -C "$M" instance-drop >/dev/null 2>&1; then bad "main: instance-drop refused"; else ok "main: instance-drop refused"; fi
# #65: an isolated instance has its own login cookie (parse-time `compose config`, no daemon).
d="worktree: the API uses its own refresh cookie, not the real app's"
if out=$(cd "$W" && ISO_NAME=capitalos-wt-wt ISO_API_PORT=1 ISO_PG_PORT=2 ISO_LOKI_PORT=3 ISO_GRAFANA_PORT=4 \
  COMPOSE_PROJECT_NAME="" COMPOSE_FILE="" docker compose -p capitalos-wt-wt -f docker-compose.yml \
  -f docker-compose.isolated.yml config api 2>&1) &&
  printf '%s' "$out" | grep -q 'AUTH_REFRESH_COOKIE_NAME: capitalos_refresh_capitalos-wt-wt$'; then ok "$d"
else bad "$d"; fi

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
