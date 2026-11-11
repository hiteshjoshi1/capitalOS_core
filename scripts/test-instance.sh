#!/bin/bash
# The test instance (#45): a batch of PRs served as a separate app with a copy of the real
# data, for Hitesh to test before anything reaches main. Run in the MAIN checkout (Makefile):
#
#   test-instance.sh up <pr> [<pr>...]  main + the PRs merged in order into test/<date> (a
#                                       worktree); a conflict stops, named, for a person.
#                                       Then `make verify`, then a FRESH verified backup of the
#                                       real app (#287; SKIP_BACKUP=1 reuses the newest one), the
#                                       stack restored from it (counts checked), the batch's
#                                       migrations applied to that copy, the demo login enabled
#                                       on it, and the app served
#                                       with a TEST banner on its own ports.
#   test-instance.sh start              after a conflict is resolved by hand in the worktree
#                                       (and committed): the remaining PRs, then the rest of `up`.
#   test-instance.sh pr                 after Hitesh's test: push test/<date> and open ONE PR to
#                                       main that `Closes` every issue the batch closes (and
#                                       names the ones it is only "Part of"). Merged on
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
# The real app's backup folder (#356: .env's BACKUP_DIR, else backups/), see backup-env.sh.
# shellcheck source=backup-env.sh
. "$(cd "$(dirname "$0")" && pwd)/backup-env.sh"
backup_env "$REPO"
# The batch's checks (make verify in the test worktree) inherit this environment: no off-site folder.
BACKUP_OFFSITE_DIR=""
export ISO_NAME=capitalos-test
export ISO_API_PORT=${TEST_API_PORT:-8021} ISO_PG_PORT=${TEST_PG_PORT:-5434} ISO_WEB_PORT=${TEST_WEB_PORT:-5174}
export ISO_GRAFANA_PORT=${TEST_GRAFANA_PORT:-3001} ISO_LOKI_PORT=${TEST_LOKI_PORT:-3101}
# Google sign-in on the copy (#373): Google only sends you back to https (or localhost), so the
# test web is also served over the tailnet's HTTPS on this port by `tailscale serve` (tailnet
# only, never funnel). The real app has :8443 and InvestOS :443; those are never touched.
TEST_TAILNET_PORT=${TEST_TAILNET_PORT:-8444}
TAILSCALE_BIN=${TAILSCALE_BIN:-$(command -v tailscale 2>/dev/null || ls /Applications/Tailscale.app/Contents/MacOS/Tailscale 2>/dev/null || true)}
DB_USER=capitalos DB_NAME=capitalos
# The real-data stack's database (read-only queries: the newest import, for "has it changed since
# the copy"), and how a fresh backup is taken (#287). Both can be overridden, e.g. by the test.
REAL_DB_CONTAINER=${REAL_DB_CONTAINER:-capitalos-oss-postgres}
BACKUP_CMD=${BACKUP_CMD:-make -C "$REPO" -s db-backup}
compose() { (cd "$TW" && COMPOSE_PROJECT_NAME="" COMPOSE_FILE="" docker compose -p "$ISO_NAME" -f docker-compose.yml -f docker-compose.isolated.yml "$@"); }
tmake() { make -C "$TW" -s "$@"; }   # ISO_* are exported, so the worktree's make uses them
# The main checkout's .env (API keys, IBKR Flex) so a batch's refreshes can be tested (#120).
# Safe: compose() passes -p/-f explicitly (a COMPOSE_* line can't redirect it),
# docker-compose.isolated.yml forces every scheduler off, and a DATABASE_URL in .env,
# which could point the copy at the real database, is refused.
link_env() {
  [ -f "$REPO/.env" ] || { echo "No $REPO/.env: IBKR and market-data refreshes won't work on the test instance."; return 0; }
  ! grep -qE '^[[:space:]]*(export[[:space:]]+)?DATABASE_URL=' "$REPO/.env" ||
    die "$REPO/.env sets DATABASE_URL, which could point the test copy at the real database; remove it first"
  [ -e "$TW/.env" ] || ln -s "$REPO/.env" "$TW/.env"
}
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

newest_verified_backup() {  # #383: listing or the folder's index (backup-env.sh)
  backup_newest_verified
}

# The dump to serve (#287): a fresh verified backup of the real app, so the copy has everything
# uploaded up to now; with SKIP_BACKUP=1 the newest verified one already there. Prints its path.
fresh_dump() {
  if [ "${SKIP_BACKUP:-0}" != 1 ]; then
    echo "Data: taking a fresh verified backup of the real app (SKIP_BACKUP=1 reuses the newest)" >&2
    $BACKUP_CMD >&2 || die "the fresh backup failed, so nothing was served (SKIP_BACKUP=1 to use the newest verified one)"
  fi
  newest_verified_backup
}

# "15:10 today", "14:02 on 6 Nov": when a backup was taken, from its name (capitalos_YYYYMMDD_HHMMSS.dump).
backup_time_label() {
  local name ymd hm today=${2:-$(date +%Y%m%d)}
  name=$(basename "$1")
  [[ $name =~ capitalos_([0-9]{8})_([0-9]{2})([0-9]{2})[0-9]{2}\.dump ]] || { echo "unknown time"; return 0; }
  ymd=${BASH_REMATCH[1]} hm="${BASH_REMATCH[2]}:${BASH_REMATCH[3]}"
  if [ "$ymd" = "$today" ]; then echo "$hm today"; return 0; fi
  local months=(Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec)
  echo "$hm on $((10#${ymd:6:2})) ${months[$((10#${ymd:4:2} - 1))]}"
}

# This machine's time zone (e.g. Asia/Singapore), so import times read like the banner's.
HOST_TZ=${HOST_TZ:-$(readlink /etc/localtime 2>/dev/null | sed -n 's#.*/zoneinfo/##p')}
newest_import() {  # newest_import <db container>: the newest import job's time (HOST_TZ), or nothing
  docker exec "$1" psql -X -q -At -U "$DB_USER" -d "$DB_NAME" \
    -c "SELECT to_char(max(created_at) AT TIME ZONE '${HOST_TZ:-UTC}', 'YYYY-MM-DD HH24:MI') FROM import_jobs" 2>/dev/null | grep -v -i collation | head -1 || true
}

# One line when the real app has imports the copy lacks (#287), else nothing.
data_drift() {  # data_drift <real newest> <copy newest>
  [ -n "$1" ] || return 0
  if [ -z "$2" ] || [[ "$1" > "$2" ]]; then
    echo "  Data drift:  the real app has newer imports (newest $1) than the copy (${2:-none}): rebuild to test them"
  fi
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
  say "Data"
  dump=$(fresh_dump)
  [ -n "$dump" ] || die "no verified backup in $BACKUP_DIR (make db-backup)"
  state_set data_from "$dump"
  say "Data: a copy of $dump ($(backup_time_label "$dump"))"
  link_env
  compose down -v --remove-orphans >/dev/null 2>&1 || true
  compose up -d postgres
  for _ in $(seq 1 60); do docker exec "$ISO_NAME-postgres" pg_isready -q -h 127.0.0.1 -U "$DB_USER" -d "$DB_NAME" && break; sleep 1; done
  # #356: an encrypted set is decrypted into a private temp dir (a plain set is copied there), the
  # copy restored from it, and the dir wiped on exit (PLAIN_SET_DIR, cleaned by the EXIT trap).
  local plain
  plain=$("$(cd "$(dirname "$0")" && pwd)/db-backup.sh" open "$dump") ||
    die "could not open the backup $dump (encrypted: is the private key at $BACKUP_AGE_IDENTITY?)"
  PLAIN_SET_DIR=$(dirname "$plain")
  case "$(basename "$PLAIN_SET_DIR")" in tmp.*) ;; *) die "db-backup.sh open returned an unexpected path: $plain" ;; esac
  trap 'rm -rf "${PLAIN_SET_DIR:-/nonexistent}"' EXIT
  docker exec -i "$ISO_NAME-postgres" pg_restore -U "$DB_USER" -d "$DB_NAME" --no-owner --no-acl --exit-on-error <"$plain" \
    2> >(grep -vi collation >&2)
  # The copy must be exact before the batch touches it.
  local sql="SELECT table_name || '|' || (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', table_schema, table_name), false, true, '')))[1]::text FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name;"
  if ! diff <(sort "$plain.counts") <(printf '%s\n' "$sql" | docker exec -i "$ISO_NAME-postgres" psql -X -q -At -U "$DB_USER" -d "$DB_NAME" 2>/dev/null | sort) >/dev/null; then
    die "the restored copy's row counts differ from the backup's"
  fi
  echo "Restored: $(wc -l <"$plain.counts" | tr -d ' ') tables, counts identical to the backup"
  # The raw files of the same backup set (#155), so rebuilds from raw statements work on the copy.
  local archive="${plain%.dump}.data.tar.gz"
  if [ -f "$archive" ]; then
    mkdir -p "$TW/data"
    tar -xzf "$archive" -C "$TW/data"
    DB_CONTAINER="$ISO_NAME-postgres" DB_USER=$DB_USER DB_NAME=$DB_NAME BACKUP_DATA_DIR="$TW/data" \
      "$(cd "$(dirname "$0")" && pwd)/db-backup.sh" check-data | tail -1 ||
      die "the copy's data/ lacks or differs from files its database records"
    echo "Data: $(basename "$archive") unpacked into $TW/data"
  else
    echo "Data: no data archive with this backup (made before #155); $TW/data has no raw files"
  fi

  say "The batch's migrations, on the copy"
  tmake db-migrate DB_CONTAINER="$ISO_NAME-postgres"
  # The demo login is off on the real data (#152); turn it on in this copy only, for checks
  # on the demo data (demo / Test@1234). Older batches without the target skip it.
  if grep -q '^demo-enable:' "$TW/Makefile"; then
    tmake demo-enable DB_CONTAINER="$ISO_NAME-postgres"
  fi

  say "API"
  # Its own Google redirect list (#373): docker-compose.isolated.yml passes it as the API's
  # GOOGLE_OAUTH_REDIRECT_URL, so the main .env's (the real app's) never applies here.
  ISO_GOOGLE_OAUTH_REDIRECT_URL=$(test_google_redirects)
  export ISO_GOOGLE_OAUTH_REDIRECT_URL
  compose up -d --build api
  for _ in $(seq 1 90); do curl -sf "http://127.0.0.1:$ISO_API_PORT/health" >/dev/null && break; sleep 2; done
  curl -sf "http://127.0.0.1:$ISO_API_PORT/health" >/dev/null || die "the API didn't become healthy (make -C $TW api-logs)"

  say "Web"
  stop_web
  local label repo_url
  label="TEST $(git -C "$TW" branch --show-current) · data $(backup_time_label "$(state_get data_from)") · Issues$(for n in $(banner_refs); do printf ' #%s' "$n"; done)"
  # The banner lists the batch's issues and links each #N to it (#200, #219: the issues a PR
  # closes, else the one it's "Part of"; GitHub sends /issues/N on to the PR when N is a PR,
  # used for a PR that names no issue at all).
  repo_url=$(cd "$TW" && gh repo view --json url --jq .url 2>/dev/null || true)
  (cd "$TW" && nohup make -s web-up INSTANCE_LABEL="$label" INSTANCE_REPO_URL="$repo_url" >"$TW/.test-instance-web.log" 2>&1 & echo $! >"$TW/.test-instance-web.pid")
  for _ in $(seq 1 90); do curl -sf -o /dev/null "http://127.0.0.1:$ISO_WEB_PORT/" && break; sleep 2; done
  curl -sf "http://127.0.0.1:$ISO_WEB_PORT/api/health" >/dev/null || die "the web app didn't come up (see $TW/.test-instance-web.log)"
  tailnet_serve_on
  state_set served "$(date '+%F %T')"
  status
}

# The Mac's tailnet name (hiteshs-macbook-pro.tailb99000.ts.net), or nothing without Tailscale.
tailnet_name() {
  [ -n "$TAILSCALE_BIN" ] || return 0
  "$TAILSCALE_BIN" status --json 2>/dev/null |
    python3 -c 'import json, sys; print((json.load(sys.stdin).get("Self") or {}).get("DNSName", "").rstrip("."))' 2>/dev/null || true
}

# The copy's own Google redirect URLs (#373), never the real app's: the tailnet HTTPS port and
# localhost. Registered once in Google Cloud next to the real app's two.
test_google_redirects() {  # [<tailnet name>]
  local name=${1-$(tailnet_name)} local_url="http://localhost:$ISO_WEB_PORT/api/auth/google/callback"
  if [ -n "$name" ]; then echo "https://$name:$TEST_TAILNET_PORT/api/auth/google/callback,$local_url"; else echo "$local_url"; fi
}

guard_tailnet_port() {  # the real app's and InvestOS's ports are never the copy's
  case "$TEST_TAILNET_PORT" in
    443|8443) die "TEST_TAILNET_PORT=$TEST_TAILNET_PORT belongs to InvestOS / the real app; pick another" ;;
  esac
}

tailnet_serve_on() {
  guard_tailnet_port
  [ -n "$TAILSCALE_BIN" ] || { echo "  (no tailscale CLI: Google sign-in only at localhost:$ISO_WEB_PORT)"; return 0; }
  "$TAILSCALE_BIN" serve --bg --https="$TEST_TAILNET_PORT" "http://127.0.0.1:$ISO_WEB_PORT" >/dev/null ||
    echo "  WARNING: tailscale serve on :$TEST_TAILNET_PORT failed; Google sign-in only at localhost:$ISO_WEB_PORT" >&2
}

tailnet_serve_off() {
  guard_tailnet_port
  [ -n "$TAILSCALE_BIN" ] || return 0
  "$TAILSCALE_BIN" serve --https="$TEST_TAILNET_PORT" off >/dev/null 2>&1 || true
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

# The issues a batch PR belongs to (#219). Args: PR number, title, the issue numbers GitHub
# says it closes (closingIssuesReferences); its body on stdin. Prints one "<kind> <n>" line each:
#   close <n>  an issue it closes: GitHub's closing references plus Closes/Fixes/Resolves #n
#              in the body;
#   part <n>   when it closes none: "Part of #n" / "Refs #n" in the body, else the "(#n)" that
#              ends its title (a Dependabot batch titled "... (#49)");
#   pr <n>     when it names none of those: the PR itself.
pr_issue_refs() {
  local pr=$1 title=$2 closing=$3 body found
  body=$(cat)
  found=$( { printf '%s\n' $closing
             printf '%s\n' "$body" | grep -oiE '(^|[^[:alnum:]_])(close[sd]?|fix(e[sd])?|resolve[sd]?):?[[:space:]]+#[0-9]+' | grep -oE '[0-9]+$' || true
           } | awk 'NF && !seen[$0]++')
  if [ -n "$found" ]; then printf 'close %s\n' $found; return 0; fi
  found=$(printf '%s\n' "$body" | grep -oiE '(^|[^[:alnum:]_])(part[[:space:]]+of|refs?):?[[:space:]]+#[0-9]+' | grep -oE '[0-9]+$' | awk '!seen[$0]++' || true)
  if [ -z "$found" ] && [[ $title =~ \(#([0-9]+)\)[[:space:]]*$ ]]; then found=${BASH_REMATCH[1]}; fi
  if [ -n "$found" ]; then printf 'part %s\n' $found; else printf 'pr %s\n' "$pr"; fi
}

batch_refs() {  # pr_issue_refs for every merged PR, in batch order; "error <pr>" if gh can't read one
  local pr info
  for pr in $(state_get merged); do
    # One call: the closing numbers on line 1, the title on line 2, the body after.
    if ! info=$(gh pr view "$pr" --json closingIssuesReferences,title,body \
      --jq '([.closingIssuesReferences[].number | tostring] | join(" ")), .title, .body' 2>/dev/null); then
      printf 'error %s\n' "$pr"; continue
    fi
    printf '%s\n' "$info" | { read -r closing || true; read -r title || true; pr_issue_refs "$pr" "$title" "$closing"; }
  done
}

banner_refs() {  # the batch's issues (closed or "part of"), else the PR, in batch order, once each
  batch_refs | awk '!seen[$2]++ { print $2 }'   # a PR gh can't read shows as itself
}

# The test PR's issue lines: "Closes #n" for every issue the batch closes, then "Part of #n" for
# the issues the banner shows that the batch only works on (never closed by merging it).
batch_issues() {
  local refs
  refs=$(batch_refs)
  if printf '%s\n' "$refs" | grep -q '^error '; then
    echo "can't read PR(s)$(printf '%s\n' "$refs" | sed -n 's/^error / #/p' | tr -d '\n') from GitHub" >&2; return 1
  fi
  printf '%s\n' "$refs" | awk '$1 == "close" { print $2 }' | sort -un | sed 's/^/Closes #/'
  printf '%s\n' "$refs" | awk '$1 == "close" { c[$2] = 1 } $1 == "part" { p[$2] = 1 }
    END { for (n in p) if (!(n in c)) print n }' | sort -un | sed 's/^/Part of #/'
}

status() {
  [ -d "$TW" ] || { echo "No test instance (make test-instance PRS=\"<n> <n>\")"; return 0; }
  local ts name
  ts=$(tailscale ip -4 2>/dev/null | head -1 || true)
  echo "Test instance: $(git -C "$TW" branch --show-current) in $TW"
  echo "  PRs merged:  $(state_get merged)"
  [ -n "$(state_get pending)" ] && echo "  PRs pending: $(state_get pending)"
  [ -n "$(state_get conflict)" ] && echo "  CONFLICT on #$(state_get conflict): resolve in $TW, then make test-instance-start"
  echo "  Served:      $(state_get served)"
  if [ -n "$(state_get data_from)" ]; then
    echo "  Data:        copy of $(basename "$(state_get data_from)") ($(backup_time_label "$(state_get data_from)"))"
    data_drift "$(newest_import "$REAL_DB_CONTAINER")" "$(newest_import "$ISO_NAME-postgres")"
  fi
  echo "  Web:         http://localhost:$ISO_WEB_PORT${ts:+   (phone: http://$ts:$ISO_WEB_PORT)}"
  name=$(tailnet_name)
  [ -n "$name" ] && echo "  HTTPS:       https://$name:$TEST_TAILNET_PORT   (tailnet only; Sign in with Google works here and at localhost:$ISO_WEB_PORT)"
  echo "  API:         http://127.0.0.1:$ISO_API_PORT   Postgres: 127.0.0.1:$ISO_PG_PORT"
  echo "  After testing: make test-instance-pr (one PR to main), then make test-instance-drop"
}

# Sourced (by scripts/test-test-instance.sh): the functions only.
[ "${BASH_SOURCE[0]}" = "$0" ] || return 0

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
    issues=$(batch_issues) || die "the batch's issues are unknown, so nothing was pushed or opened"
    git -C "$TW" push -q -u origin "$branch"
    body=$(printf 'The tested batch: main plus%s, merged in order and served on the test instance (%s). Merge only after Hitesh has tested it there (AGENTS.md § Process Rules).\n\nMerging this PR merges the batch PRs as tested.\n\n%s\n' \
      "$(for p in $(state_get merged); do printf ' #%s' "$p"; done)" "$(state_get served)" "$issues")
    gh pr create --base main --head "$branch" --title "Test batch $branch:$(for p in $(state_get merged); do printf ' #%s' "$p"; done)" --body "$body"
    ;;
  status) status ;;
  drop)
    require_main_checkout
    [ -d "$TW" ] || { echo "No test instance."; exit 0; }
    branch=$(git -C "$TW" branch --show-current)
    stop_web
    tailnet_serve_off
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
  *) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
