#!/bin/bash
# Install merged main into the real-data stack (#46), from the main checkout:
#   deploy.sh [COMMIT]     fast-forward to COMMIT (default origin/main) and install it
#   deploy.sh --plan [FROM] [TO]
#                          what a deploy from FROM (default HEAD) to TO would do; changes nothing
#   deploy.sh --status     the last deploys, and whether this checkout is behind origin/main
#
# Order (each step must succeed before the next):
#   1. refuse: not the main checkout, not on main, uncommitted tracked changes, not a fast-forward
#   2. a VERIFIED backup (make db-backup) when the update brings new migrations
#   3. fast-forward the code
#   4. build the images (the running API keeps serving the code baked into its image: the real
#      stack has no code bind mount and no --reload, so steps 3-5 change nothing live; #155)
#   5. migrations: each file in one transaction (make db-migrate). On failure the code is reset
#      to the previous commit and the image rebuilt from it, the old API is still running, the
#      migrations of this deploy that did apply are named (D-13), and so is the backup.
#   6. recreate the stack (make up): the new code goes live here, after build and migrations
#   7. health checks: API (/health checks the database and the migration state), then
#      Loki/Grafana if they run
# Each deploy appends a line to deployments.log (git-ignored).
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO"
LOG="$REPO/deployments.log"
say() { printf '\n== %s\n' "$*"; }
die() { printf 'deploy: %s\n' "$*" >&2; exit 1; }
record() { printf '%s from=%s to=%s backup=%s migrations=%s result=%s\n' "$(date '+%F %T')" "$FROM" "$TO" "${BACKUP:-none}" "${NEW_MIGRATIONS:-0}" "$1" >>"$LOG"; }

new_migrations() { git diff --name-only --diff-filter=A "$1" "$2" -- 'migrations/[0-9][0-9][0-9]_*.sql'; }
changed() { git diff --name-only "$1" "$2" -- "${@:3}"; }

plan() {  # plan FROM TO
  local from=$1 to=$2 mig
  mig=$(new_migrations "$from" "$to")
  echo "Deploy $(git rev-parse --short "$from") -> $(git rev-parse --short "$to") ($(git rev-list --count "$from..$to") commits)"
  if [ -n "$mig" ]; then echo "  backup:     yes, verified, before anything changes"; printf '  migration:  %s\n' $mig
  else echo "  backup:     no (no new migrations)"; fi
  [ -n "$(changed "$from" "$to" api/)" ] && echo "  api:        rebuild + restart"
  [ -n "$(changed "$from" "$to" docker-compose.yml)" ] && echo "  compose:    changed: services recreated as needed"
  [ -n "$(changed "$from" "$to" web/package.json web/package-lock.json)" ] &&
    echo "  web deps:   changed: npm ci, then RESTART your 'make web-up' (Vite)"
  [ -n "$(changed "$from" "$to" web/src)" ] && echo "  web:        code changed (a running Vite picks it up)"
  return 0
}

status() {
  git fetch -q origin 2>/dev/null || true
  echo "Deployed: $(git rev-parse --short HEAD) $(git log -1 --format=%s HEAD)"
  local behind
  behind=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo "?")
  echo "Behind origin/main: $behind commit(s)$([ "$behind" != 0 ] && [ "$behind" != "?" ] && echo ' (make deploy)')"
  [ -f "$LOG" ] && { echo "Recent deploys:"; tail -5 "$LOG" | sed 's/^/  /'; }
  return 0
}

case "${1:-}" in
  --status) status; exit 0 ;;
  --plan) git fetch -q origin; plan "${2:-HEAD}" "${3:-origin/main}"; exit 0 ;;
esac

# 1. Preconditions
[ "$(git rev-parse --absolute-git-dir)" = "$(cd "$(git rev-parse --git-common-dir)" && pwd)" ] || die "run from the main checkout, not a worktree"
[ "$(git branch --show-current)" = main ] || die "the main checkout must be on main"
git diff --quiet && git diff --cached --quiet || die "uncommitted changes to tracked files; commit or stash them first"
git fetch -q origin
FROM=$(git rev-parse HEAD)
TO=$(git rev-parse "${1:-origin/main}")
if [ "$FROM" = "$TO" ]; then echo "Already at $(git rev-parse --short "$TO"); nothing to deploy."; status; exit 0; fi
git merge-base --is-ancestor "$FROM" "$TO" || die "$(git rev-parse --short "$TO") is not a fast-forward of the deployed $(git rev-parse --short "$FROM")"
plan "$FROM" "$TO"
NEW_MIGRATIONS=$(new_migrations "$FROM" "$TO" | wc -l | tr -d ' ')
BACKUP=""
trap 'rc=$?; [ $rc -ne 0 ] && record "failed(exit $rc)"; exit $rc' EXIT

# 2. Backup when the schema will change
if [ "$NEW_MIGRATIONS" -gt 0 ]; then
  say "Verified backup before $NEW_MIGRATIONS new migration(s)"
  make -s db-backup || die "backup failed: nothing was changed"
  BACKUP=$(ls -1t backups/capitalos_*.dump.verified | head -1 | sed 's/\.verified$//')
fi

# 3. Code
say "Code: fast-forward to $(git rev-parse --short "$TO")"
git merge -q --ff-only "$TO"

# 4. Images (the running API keeps serving its own image meanwhile; nothing reloads, #155)
say "Build"
make -s api-build

# 5. Migrations
if [ "$NEW_MIGRATIONS" -gt 0 ]; then
  say "Migrations"
  if ! make -s db-migrate; then
    applied_now=$(make -s db-migrations-applied 2>/dev/null || true)
    partial=$(new_migrations "$FROM" "$TO" | xargs -n1 basename | grep -Fxf <(printf '%s\n' "$applied_now") || true)
    git reset -q --hard "$FROM"
    # The image tag now holds the new code; rebuild it from the old, so a later `make up` (or
    # restart) doesn't start code whose migrations didn't run.
    make -s api-build || echo "deploy: WARNING: rebuilding the previous image failed; run make api-build before any make up" >&2
    [ -n "$partial" ] && printf 'deploy: applied before the failure (they stay applied, D-13): %s\n' $partial >&2
    die "a migration failed (rolled back, see above). Code reset to $(git rev-parse --short "$FROM"); the old API is still running. Backup taken first: $BACKUP"
  fi
fi

# 6. Stack
say "Stack"
make -s up
if [ -n "$(changed "$FROM" "$TO" web/package.json web/package-lock.json)" ]; then make -s web-deps; fi
if make -s observability-running; then make -s observability-up; fi

# 7. Health
say "Health"
api=$(make -s api-url)
for _ in $(seq 1 60); do curl -sf "$api/health" >/dev/null && break; sleep 2; done
curl -sf "$api/health" >/dev/null || die "the API is not healthy at $api (make api-logs). Previous commit: $(git rev-parse --short "$FROM")"
health=$(curl -s "$api/health")
echo "API: $health"
# The migration state /health reports (#155); an older API without it says nothing here.
case "$health" in
  *'"current":false'*) echo "deploy: WARNING: the newest applied migration is not the newest file (see above; make db-migrate?)" >&2 ;;
esac
if make -s observability-running; then
  curl -sf http://127.0.0.1:3100/ready >/dev/null && echo "Loki: ready" || echo "Loki: NOT ready"
  curl -sf http://127.0.0.1:3000/api/health >/dev/null && echo "Grafana: ok" || echo "Grafana: NOT ok"
fi
trap - EXIT
record ok
echo
echo "Deployed $(git rev-parse --short "$TO")."
[ -n "$(changed "$FROM" "$TO" web/package.json web/package-lock.json)" ] && echo "Web dependencies changed: restart 'make web-up'."
exit 0
