#!/bin/sh
# Full-stack smoke and screenshot diffs (#73). Used by `make e2e-smoke` / `make e2e-smoke-update`
# and CI (.github/workflows/pr-validate.yml, job "smoke").
#
#   check    1. start a throwaway stack: Postgres + API + the production web container (its own
#               compose project, containers and volume; nothing published on the host, the
#               checkout's .env never read),
#            2. migrate it with `make db-migrate`, enable the demo login, load the demo seed,
#            3. run web/playwright.smoke.config.ts inside the pinned Playwright image
#               (tools/Dockerfile), sharing the web container's network: tests/smoke opens every
#               page on live demo data, compares screenshots with the committed baselines, and
#               checks the navigation against the route list,
#            4. remove the stack (KEEP=1 leaves it running; `drop` removes it).
#   update   the same, rewriting the screenshot baselines (web/tests/smoke/__screenshots__).
#   record   re-record the demo API fixture the mocked specs and the screenshots use
#            (web/tests/e2e/fixtures/demo-api.json) from this stack; then run `update`.
#   drop     remove a stack left by KEEP=1.
# Extra arguments go to `playwright test` (e.g. a project: --project=screens).
# Results: web/test-results/smoke (diffs, traces), web/playwright-report/smoke (HTML report).
set -eu
cd "$(dirname "$0")/.."

mode=${1:-check}
[ $# -gt 0 ] && shift
name=${SMOKE_NAME:-capitalos-smoke}
case "$name" in
  capitalos|capitalos-oss-*|capitalos-test|capitalos-postgres) echo "Refusing: '$name' is not a throwaway name." >&2; exit 2 ;;
esac
case "$mode" in check|update|record|drop) ;; *) echo "usage: $0 check|update|record|drop [playwright args]" >&2; exit 2 ;; esac

# The isolated override reads ISO_*; docker-compose.smoke.yml publishes no ports at all.
export ISO_NAME="$name" ISO_PG_PORT=0 ISO_API_PORT=0 ISO_GRAFANA_PORT=0 ISO_LOKI_PORT=0
export POSTGRES_USER=capitalos POSTGRES_PASSWORD=capitalos POSTGRES_DB=capitalos
unset DATABASE_URL
work=$(mktemp -d "${TMPDIR:-/tmp}/capitalos-smoke.XXXXXX")
: > "$work/empty.env"
compose() {
  # --env-file: interpolate from nothing, not the checkout's .env.
  COMPOSE_PROJECT_NAME='' COMPOSE_FILE='' docker compose -p "$name" --env-file "$work/empty.env" \
    -f docker-compose.yml -f docker-compose.isolated.yml -f docker-compose.smoke.yml "$@"
}

if [ "$mode" = drop ]; then
  compose down -v --remove-orphans
  rm -rf "$work"
  exit 0
fi

image=$(scripts/tool-image.sh playwright)
image_version=$(echo "$image" | sed -n 's/.*:v\([0-9.]*\)-.*/\1/p')
npm_version=$(node -e 'process.stdout.write(require("./web/package-lock.json").packages["node_modules/@playwright/test"].version)')
if [ "$image_version" != "$npm_version" ]; then
  echo "Playwright image $image_version != @playwright/test $npm_version: bump tools/Dockerfile and web/package.json together." >&2
  exit 2
fi
[ -x web/node_modules/.bin/playwright ] || { echo "Run make web-deps first." >&2; exit 2; }

cleanup() {
  rc=$?
  if [ "${KEEP:-0}" = 1 ]; then
    echo "KEEP=1: the smoke stack '$name' is still running (scripts/e2e-smoke.sh drop removes it)."
  else
    compose down -v --remove-orphans > /dev/null 2>&1 || true
  fi
  rm -rf "$work"
  exit $rc
}
trap cleanup EXIT INT TERM

echo "== Smoke stack '$name': build and start"
compose up -d --build postgres api web
db="$name-postgres"
# Quiet unless it fails (the migrations and the seed print many NOTICEs).
${MAKE:-make} --no-print-directory db-migrate DB_CONTAINER="$db" > "$work/db.log" 2>&1 &&
  docker exec -i "$db" psql -q -v ON_ERROR_STOP=1 -U capitalos -d capitalos < scripts/demo-enable.sql >> "$work/db.log" 2>&1 &&
  docker exec -i "$db" psql -q -v ON_ERROR_STOP=1 -U capitalos -d capitalos < migrations/seed_dummy.sql >> "$work/db.log" 2>&1 ||
  { tail -40 "$work/db.log" >&2; exit 1; }
echo "Migrated, demo login enabled, demo data loaded."

i=0
until docker exec "$name-web" wget -q -O /dev/null http://127.0.0.1:8080/api/health 2>/dev/null; do
  i=$((i + 1))
  if [ "$i" -ge 60 ]; then
    echo "The web container's /api/health never answered:" >&2
    compose logs --tail 40 api web >&2
    exit 1
  fi
  sleep 1
done

echo "== Playwright ($image_version) in the web container's network"
record_from=""
case "$mode" in
  record) record_from=http://127.0.0.1:8080; set -- --project=record "$@" ;;
  *)
    [ "$mode" = update ] && set -- --update-snapshots "$@"
    # Every project but "record", unless the arguments pick one.
    case " $* " in *" --project"*) ;; *) set -- --project=live --project=screens --project=routes "$@" ;; esac ;;
esac
docker run --rm --init --ipc=host \
  --network "container:$name-web" \
  --user "$(id -u):$(id -g)" -e HOME=/tmp -e CI="${CI:-}" \
  -e E2E_RECORD_FROM="$record_from" \
  -v "$PWD/web:/work" -w /work \
  "$image" \
  node_modules/.bin/playwright test -c playwright.smoke.config.ts "$@"
