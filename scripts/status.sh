#!/bin/bash
# Where things stand (#47): `make status`, and the Claude Code SessionStart hook.
# Read-only and fast. Each part degrades to a one-line note when GitHub, Docker or the
# network is unavailable, and the script always exits 0, so it never blocks a session.
set -u

REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO"
MAIN=$(cd "$(git rev-parse --git-common-dir)/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -f "$tmp"/board "$tmp"/prs; rmdir "$tmp" 2>/dev/null' EXIT

# GitHub, in parallel (each is ~1s).
( gh project item-list 2 --owner hiteshjoshi1 --format json --limit 500 >"$tmp/board" 2>/dev/null || : >"$tmp/board" ) &
( gh pr list --state open --json number,title,isDraft,author,statusCheckRollup >"$tmp/prs" 2>/dev/null || : >"$tmp/prs" ) &

echo "CapitalOS status ($(date '+%F %H:%M'))"
make -s where 2>/dev/null | sed 's/^/  /'

# The real-data stack: health of what runs, and how far main's checkout is from origin/main.
if docker info >/dev/null 2>&1; then
  running=$(docker ps --filter name=capitalos-oss --filter name=capitalos-loki --filter name=capitalos-grafana \
    --filter name=capitalos-alloy --filter name=capitalos-docker-socket-proxy --format '{{.Names}}' | wc -l | tr -d ' ')
  api=$(curl -s -m 2 http://127.0.0.1:8011/health 2>/dev/null | grep -q '"ok"' && echo ok || echo DOWN)
  echo "Real stack: API $api, $running/6 containers up"
else
  echo "Real stack: Docker not running"
fi
behind=$(git -C "$MAIN" rev-list --count HEAD..origin/main 2>/dev/null || echo "?")
echo "Deployed:   $(git -C "$MAIN" rev-parse --short HEAD 2>/dev/null) on $(git -C "$MAIN" branch --show-current 2>/dev/null), $behind behind origin/main (as of last fetch)$([ "$behind" != 0 ] && [ "$behind" != "?" ] && echo ' -> make deploy-plan')"

# Backups: the newest verified one, and a warning when it's over a day old.
newest=$(ls -1t "$MAIN"/backups/capitalos_*.dump.verified 2>/dev/null | head -1)
if [ -n "$newest" ]; then
  age_h=$(( ($(date +%s) - $(stat -f %m "$newest" 2>/dev/null || stat -c %Y "$newest")) / 3600 ))
  echo "Backup:     newest verified ${age_h}h ago$([ "$age_h" -gt 26 ] && echo '  <- OLDER THAN A DAY: make backup-status')"
else
  echo "Backup:     NO verified backup (make db-backup)"
fi

# Worktrees and the test instance.
wts=$(git worktree list --porcelain | sed -n 's#^worktree ##p' | grep -v -x "$MAIN" | sed "s#.*/##" | tr '\n' ' ')
[ -n "$wts" ] && echo "Worktrees:  $wts"
[ -d "$(dirname "$MAIN")/capitalOS-worktrees/test-instance" ] && "$MAIN/scripts/test-instance.sh" status 2>/dev/null | head -3 | sed 's/^/  /'

wait
echo
if [ -s "$tmp/board" ]; then
  python3 - "$tmp/board" <<'EOF'
import json, sys
items = json.load(open(sys.argv[1])).get("items", [])
for status in ("In progress", "Waiting on Hitesh", "Fixed-To Review", "Next up"):
    rows = [i for i in items if i.get("status") == status]
    if not rows:
        continue
    print(f"Board: {status} ({len(rows)})")
    for i in rows[:6]:
        c = i.get("content", {})
        print(f"  #{c.get('number')}  {c.get('title', '')[:80]}")
    if len(rows) > 6:
        print(f"  ... {len(rows) - 6} more")
EOF
else
  echo "Board: unavailable (gh offline or not logged in)"
fi
if [ -s "$tmp/prs" ]; then
  python3 - "$tmp/prs" <<'EOF'
import json, sys
prs = json.load(open(sys.argv[1]))
def ci(p):
    runs = [r.get("conclusion") or r.get("state") or r.get("status") for r in p.get("statusCheckRollup") or []]
    if not runs: return "no CI"
    if any(r in ("FAILURE", "ERROR", "TIMED_OUT", "CANCELLED") for r in runs): return "CI failing"
    if any(r in ("IN_PROGRESS", "QUEUED", "PENDING", "EXPECTED", None) for r in runs): return "CI running"
    return "CI green"
mine = [p for p in prs if not p["author"]["login"].startswith(("app/dependabot", "dependabot"))]
bots = len(prs) - len(mine)
print(f"Open PRs: {len(mine)}" + (f" (+{bots} Dependabot, see #49)" if bots else ""))
for p in mine[:8]:
    print(f"  #{p['number']}  {'[draft] ' if p['isDraft'] else ''}{ci(p)}  {p['title'][:70]}")
EOF
else
  echo "Open PRs: unavailable (gh offline or not logged in)"
fi
exit 0
