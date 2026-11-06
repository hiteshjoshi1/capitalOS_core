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
cp "$src/Makefile" "$src/docker-compose.yml" "$src/docker-compose.isolated.yml" "$tmp/main/"
# Simulate the real-data machine: the git-ignored override exists in the main checkout.
printf 'services: {}\n' >"$tmp/main/docker-compose.oss-test.yml"
git -C "$tmp/main" checkout -q -B main
git -C "$tmp/main" worktree add -q -b feature/issue-0-guard-test "$tmp/wt" main
cp "$src/Makefile" "$src/docker-compose.yml" "$src/docker-compose.isolated.yml" "$tmp/wt/"

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
# #152, #221: the demo login and the dummy seed (shared DUMMY prices) never go on the real-data
# stack. A stub `docker` on PATH logs every call and succeeds, so these runs (not dry runs) show
# what would have reached the database; none can touch a real container.
mkdir -p "$tmp/bin"
printf '#!/bin/sh\necho "$*" >>"%s"\nexit 0\n' "$tmp/docker.log" >"$tmp/bin/docker"
chmod +x "$tmp/bin/docker"
expect_refused_untouched() {   # <description> <dir> <make args...>: refused, and no docker call at all
  local d=$1 dir=$2; shift 2
  : >"$tmp/docker.log"
  if out=$(PATH="$tmp/bin:$PATH" make -s -C "$dir" "$@" 2>&1); then bad "$d (was allowed: $out)"
  elif ! printf '%s' "$out" | grep -q 'Refusing'; then bad "$d (failed without the guard's message: $out)"
  elif [ -s "$tmp/docker.log" ]; then bad "$d (docker was called first: $(tr '\n' ';' <"$tmp/docker.log"))"
  else ok "$d"; fi
}
for t in demo-enable db-seed-dummy db-seed-demo; do
  expect_refused_untouched "real-data stack on main: $t refused before any docker call" "$M" "$t"
done
expect_refused_untouched "real-data stack: db-seed-dummy refused even with ALLOW_BRANCH=1" "$M" db-seed-dummy ALLOW_BRANCH=1
expect_refused_untouched "real-data container named from a fresh-clone stack: db-seed-dummy refused" "$M" db-seed-dummy \
  COMPOSE_PROJECT=capitalos DB_CONTAINER=capitalos-oss-postgres
# The same guard in the recipe, for a run that reaches db-seed-dummy as a prerequisite (the
# command-line check switched off here to reach it): db-wait's readiness probe runs, psql never.
d="real-data stack: db-seed-dummy's recipe refuses too, before psql"
: >"$tmp/docker.log"
if out=$(PATH="$tmp/bin:$PATH" make -s -C "$M" db-seed-dummy DEMO_ONLY_TARGETS= 2>&1); then bad "$d (was allowed: $out)"
elif printf '%s' "$out" | grep -q "Refusing 'db-seed-dummy'" && ! grep -q psql "$tmp/docker.log"; then ok "$d"
else bad "$d (got: $out; docker: $(tr '\n' ';' <"$tmp/docker.log"))"; fi
expect_command "real-data stack on main: db-clear-dummy (the cleanup) allowed" "$M" 'capitalos-oss-postgres psql .*seed_dummy_cleanup\.sql' db-clear-dummy
expect_command "worktree: db-seed-dummy allowed on its own stack" "$W" 'capitalos-wt-wt-postgres psql .*seed_dummy\.sql' db-seed-dummy
expect_command "worktree: db-seed-demo allowed on its own stack" "$W" 'demo-enable\.sql' db-seed-demo

# #65: an isolated instance has its own login cookie (parse-time `compose config`, no daemon).
d="worktree: the API uses its own refresh cookie, not the real app's"
if out=$(cd "$W" && ISO_NAME=capitalos-wt-wt ISO_API_PORT=1 ISO_PG_PORT=2 ISO_LOKI_PORT=3 ISO_GRAFANA_PORT=4 \
  COMPOSE_PROJECT_NAME="" COMPOSE_FILE="" docker compose -p capitalos-wt-wt -f docker-compose.yml \
  -f docker-compose.isolated.yml config api 2>&1) &&
  printf '%s' "$out" | grep -q 'AUTH_REFRESH_COOKIE_NAME: capitalos_refresh_capitalos-wt-wt$'; then ok "$d"
else bad "$d"; fi

# #155: the real-data API runs its image's code without --reload (a deploy's fast-forward must not
# put code live before build + migrations); worktrees and the test instance mount it and reload.
real_api=$(cd "$M" && COMPOSE_PROJECT_NAME="" COMPOSE_FILE="" docker compose -p capitalos-oss-test -f docker-compose.yml \
  -f docker-compose.oss-test.yml config api 2>&1) || real_api="config failed: $real_api"
d="real-data stack: the API runs without --reload"
if printf '%s' "$real_api" | grep -q -- '- uvicorn' && ! printf '%s' "$real_api" | grep -q -- '--reload'; then ok "$d"; else bad "$d"; fi
d="real-data stack: the code is not bind-mounted"
if printf '%s' "$real_api" | grep -q 'target: /app/data' && ! printf '%s' "$real_api" | grep -q 'target: /app/app$'; then ok "$d"; else bad "$d"; fi
d="real-data stack: migrations are mounted read-only for /health"
if printf '%s' "$real_api" | grep -A2 'target: /app/migrations' | grep -q 'read_only: true'; then ok "$d"; else bad "$d"; fi
wt_api=$(cd "$W" && ISO_NAME=capitalos-wt-wt ISO_API_PORT=1 ISO_PG_PORT=2 ISO_LOKI_PORT=3 ISO_GRAFANA_PORT=4 \
  COMPOSE_PROJECT_NAME="" COMPOSE_FILE="" docker compose -p capitalos-wt-wt -f docker-compose.yml \
  -f docker-compose.isolated.yml config api 2>&1) || wt_api="config failed: $wt_api"
d="worktree: the API mounts the code and reloads"
if printf '%s' "$wt_api" | grep -q -- '--reload' && printf '%s' "$wt_api" | grep -q 'target: /app/app$'; then ok "$d"; else bad "$d"; fi

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
