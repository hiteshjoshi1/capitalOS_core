#!/bin/bash
# The test instance (#45): a batch of PRs served as a separate app with a copy of the real
# data, for Hitesh to test before anything reaches main. Run in the MAIN checkout (Makefile):
#
#   test-instance.sh up <pr> [<pr>...]  main + the PRs merged in order into test/<date> (a
#                                       worktree); a conflict stops, named, for a person.
#                                       Then `make verify`, then the stack restored from the
#                                       newest VERIFIED backup (counts checked), the batch's
#                                       migrations applied to that copy, and the app served
#                                       with a TEST banner on its own ports.
#   test-instance.sh start              after a conflict is resolved by hand in the worktree
#                                       (and committed): the remaining PRs, then the rest of `up`.
#   test-instance.sh pr                 after Hitesh's test: push test/<date> and open ONE PR to
#                                       main that `Closes` every issue the batch closes. Merged on
#                                       his word, as tested, so main's tree is the tested tip.
#   test-instance.sh status             what's in the batch, where it's served.
#   test-instance.sh drop               stop it: web server, containers and volumes, the
#                                       worktree and its local branch.
#
# The instance is isolated like any worktree (#44): its own compose project (capitalos-test),
# containers, ports and database; schedulers off. It never touches the real-data stack.
set -euo pipefail

# The main checkout. TEST_INSTANCE_REPO lets a newer copy of this script (on a branch) drive it.
REPO=${TEST_INSTANCE_REPO:-$(cd "$(dirname "$0")/.." && pwd)}
WORKTREES_DIR=${WORKTREES_DIR:-$(cd "$REPO/.." && pwd)/capitalOS-worktrees}
TW="$WORKTREES_DIR/test-instance"
STATE="$TW/.test-instance.state"
BACKUP_DIR=${BACKUP_DIR:-$REPO/backups}
export ISO_NAME=capitalos-test
export ISO_API_PORT=${TEST_API_PORT:-8021} ISO_PG_PORT=${TEST_PG_PORT:-5434} ISO_WEB_PORT=${TEST_WEB_PORT:-5174}
export ISO_GRAFANA_PORT=${TEST_GRAFANA_PORT:-3001} ISO_LOKI_PORT=${TEST_LOKI_PORT:-3101}
DB_USER=capitalos DB_NAME=capitalos
compose() { (cd "$TW" && COMPOSE_PROJECT_NAME="" COMPOSE_FILE="" docker compose -p "$ISO_NAME" -f docker-compose.yml -f docker-compose.isolated.yml "$@"); }
tmake() { make -C "$TW" -s "$@"; }   # ISO_* are exported, so the worktree's make uses them
say() { printf '\n== %s\n' "$*"; }
die() { printf 'test-instance: %s\n' "$*" >&2; exit 1; }
state_get() { sed -n "s/^$1=//p" "$STATE" 2>/dev/null | tail -1; }
state_set() { { grep -v "^$1=" "$STATE" 2>/dev/null || true; printf '%s=%s\n' "$1" "$2"; } >"$STATE.new" && mv "$STATE.new" "$STATE"; }

require_main_checkout() {
  [ "$(cd "$REPO" && git rev-parse --absolute-git-dir)" = "$(cd "$REPO" && cd "$(git rev-parse --git-common-dir)" && pwd)" ] ||
    die "run this from the main checkout, not a worktree"
}

merge_prs() {  # merge every PR in state "pending" into the test branch, in order
  local pr title
  for pr in $(state_get pending); do
    title=$(gh pr view "$pr" --json title --jq .title)
    say "Merging #$pr: $title"
    git -C "$TW" fetch -q origin "pull/$pr/head"
    if ! git -C "$TW" merge --no-ff --no-edit -m "Test batch: merge #$pr ($title)" FETCH_HEAD; then
      echo "CONFLICT merging #$pr in $TW:"
      git -C "$TW" diff --name-only --diff-filter=U | sed 's/^/  /'
      echo "Resolve and commit there (git -C $TW commit), then: make test-instance-start"
      state_set pending "$(state_get pending | sed "s/^$pr *//")"
      state_set conflict "$pr"
      exit 3
    fi
    state_set merged "$(state_get merged) $pr"
    state_set pending "$(state_get pending | sed "s/^$pr *//")"
  done
  state_set conflict ""
}

newest_verified_backup() {
  ls -1t "$BACKUP_DIR"/capitalos_*.dump.verified 2>/dev/null | head -1 | sed 's/\.verified$//'
}

serve() {
  say "Checks on the batch: make verify (lint, typecheck, backend + frontend tests)"
  if ! tmake verify; then
    echo
    echo "The batch failed its checks, so nothing was served. Find the PR at fault (the output above),"
    echo "then rebuild without it: make test-instance-drop && make test-instance PRS=\"<the others>\""
    exit 4
  fi

  local dump
  dump=$(newest_verified_backup)
  [ -n "$dump" ] || die "no verified backup in $BACKUP_DIR (make db-backup)"
  say "Data: a copy of $dump"
  compose down -v --remove-orphans >/dev/null 2>&1 || true
  compose up -d postgres
  for _ in $(seq 1 60); do docker exec "$ISO_NAME-postgres" pg_isready -q -h 127.0.0.1 -U "$DB_USER" -d "$DB_NAME" && break; sleep 1; done
  docker exec -i "$ISO_NAME-postgres" pg_restore -U "$DB_USER" -d "$DB_NAME" --no-owner --no-acl --exit-on-error <"$dump" \
    2> >(grep -vi collation >&2)
  # The copy must be exact before the batch touches it.
  local sql="SELECT table_name || '|' || (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', table_schema, table_name), false, true, '')))[1]::text FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name;"
  if ! diff <(sort "$dump.counts") <(printf '%s\n' "$sql" | docker exec -i "$ISO_NAME-postgres" psql -X -q -At -U "$DB_USER" -d "$DB_NAME" 2>/dev/null | sort) >/dev/null; then
    die "the restored copy's row counts differ from the backup's"
  fi
  echo "Restored: $(wc -l <"$dump.counts" | tr -d ' ') tables, counts identical to the backup"

  say "The batch's migrations, on the copy"
  tmake db-migrate DB_CONTAINER="$ISO_NAME-postgres"

  say "API"
  compose up -d --build api
  for _ in $(seq 1 90); do curl -sf "http://127.0.0.1:$ISO_API_PORT/health" >/dev/null && break; sleep 2; done
  curl -sf "http://127.0.0.1:$ISO_API_PORT/health" >/dev/null || die "the API didn't become healthy (make -C $TW api-logs)"

  say "Web"
  stop_web
  local label repo_url
  label="TEST $(git -C "$TW" branch --show-current) · PRs$(for p in $(state_get merged); do printf ' #%s' "$p"; done)"
  # The banner links each #N to its PR (#101).
  repo_url=$(cd "$TW" && gh repo view --json url --jq .url 2>/dev/null || true)
  (cd "$TW" && nohup make -s web-up INSTANCE_LABEL="$label" INSTANCE_REPO_URL="$repo_url" >"$TW/.test-instance-web.log" 2>&1 & echo $! >"$TW/.test-instance-web.pid")
  for _ in $(seq 1 90); do curl -sf -o /dev/null "http://127.0.0.1:$ISO_WEB_PORT/" && break; sleep 2; done
  curl -sf "http://127.0.0.1:$ISO_WEB_PORT/api/health" >/dev/null || die "the web app didn't come up (see $TW/.test-instance-web.log)"
  state_set served "$(date '+%F %T')"
  status
}

stop_web() {
  local pid
  if [ -f "$TW/.test-instance-web.pid" ]; then
    pid=$(cat "$TW/.test-instance-web.pid")
    pkill -P "$pid" 2>/dev/null || true
    kill "$pid" 2>/dev/null || true
    rm -f "$TW/.test-instance-web.pid"
  fi
  # Vite runs under npm under make: also stop whatever still serves the test port from this worktree.
  for pid in $(lsof -ti "tcp:$ISO_WEB_PORT" -sTCP:LISTEN 2>/dev/null); do
    if ps -o command= -p "$pid" | grep -q "$TW"; then kill "$pid" 2>/dev/null || true; fi
    if lsof -p "$pid" 2>/dev/null | grep -q "$TW/web"; then kill "$pid" 2>/dev/null || true; fi
  done
}

batch_issues() {  # "Closes #n" lines for every issue the batch's PRs close
  local pr
  for pr in $(state_get merged); do
    gh pr view "$pr" --json closingIssuesReferences --jq '.closingIssuesReferences[].number'
  done | sort -un | sed 's/^/Closes #/'
}

status() {
  [ -d "$TW" ] || { echo "No test instance (make test-instance PRS=\"<n> <n>\")"; return 0; }
  local ts
  ts=$(tailscale ip -4 2>/dev/null | head -1 || true)
  echo "Test instance: $(git -C "$TW" branch --show-current) in $TW"
  echo "  PRs merged:  $(state_get merged)"
  [ -n "$(state_get pending)" ] && echo "  PRs pending: $(state_get pending)"
  [ -n "$(state_get conflict)" ] && echo "  CONFLICT on #$(state_get conflict): resolve in $TW, then make test-instance-start"
  echo "  Served:      $(state_get served)"
  echo "  Web:         http://localhost:$ISO_WEB_PORT${ts:+   (phone: http://$ts:$ISO_WEB_PORT)}"
  echo "  API:         http://127.0.0.1:$ISO_API_PORT   Postgres: 127.0.0.1:$ISO_PG_PORT"
  echo "  After testing: make test-instance-pr (one PR to main), then make test-instance-drop"
}

case "${1:-}" in
  up)
    require_main_checkout
    shift
    [ $# -ge 1 ] || die 'usage: make test-instance PRS="<n> <n>"'
    [ ! -d "$TW" ] || die "a test instance already exists ($TW): make test-instance-drop first"
    for pr in "$@"; do
      [ "$(gh pr view "$pr" --json state --jq .state)" = OPEN ] || die "#$pr is not an open PR"
    done
    git -C "$REPO" fetch -q origin
    branch="test/$(date +%Y%m%d-%H%M)"
    mkdir -p "$WORKTREES_DIR"
    git -C "$REPO" worktree add -q -b "$branch" "$TW" origin/main
    printf 'branch=%s\npending=%s\nmerged=\n' "$branch" "$*" >"$STATE"
    merge_prs
    serve
    ;;
  start)
    require_main_checkout
    [ -d "$TW" ] || die "no test instance to start"
    git -C "$TW" diff --quiet --diff-filter=U || die "unresolved conflicts remain in $TW"
    [ -n "$(state_get conflict)" ] && state_set merged "$(state_get merged) $(state_get conflict)"
    merge_prs
    serve
    ;;
  pr)
    require_main_checkout
    [ -d "$TW" ] || die "no test instance"
    [ -z "$(state_get pending)$(state_get conflict)" ] || die "the batch isn't fully merged yet"
    branch=$(git -C "$TW" branch --show-current)
    git -C "$TW" push -q -u origin "$branch"
    body=$(printf 'The tested batch: main plus%s, merged in order and served on the test instance (%s). Merge only after Hitesh has tested it there (AGENTS.md § Process Rules).\n\nMerging this PR merges the batch PRs as tested.\n\n%s\n' \
      "$(for p in $(state_get merged); do printf ' #%s' "$p"; done)" "$(state_get served)" "$(batch_issues)")
    gh pr create --base main --head "$branch" --title "Test batch $branch:$(for p in $(state_get merged); do printf ' #%s' "$p"; done)" --body "$body"
    ;;
  status) status ;;
  drop)
    require_main_checkout
    [ -d "$TW" ] || { echo "No test instance."; exit 0; }
    branch=$(git -C "$TW" branch --show-current)
    stop_web
    compose --profile observability --profile tools down -v --remove-orphans
    git -C "$REPO" worktree remove --force "$TW"
    git -C "$REPO" branch -D "$branch" >/dev/null 2>&1 || true
    # The pushed test branch, once it's merged (gh's --delete-branch can't while its worktree exists).
    if git -C "$REPO" ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1; then
      git -C "$REPO" fetch -q origin "$branch" main
      if git -C "$REPO" merge-base --is-ancestor FETCH_HEAD origin/main 2>/dev/null; then
        git -C "$REPO" push -q origin --delete "$branch" && echo "Deleted the merged remote branch $branch"
      else
        echo "Kept the remote branch $branch: it isn't merged into main"
      fi
    fi
    docker image ls --format '{{.Repository}}' | grep -x "$ISO_NAME-api\|$ISO_NAME-api-dev" | xargs -r docker image rm >/dev/null 2>&1 || true
    echo "Dropped the test instance ($branch)."
    ;;
  *) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
