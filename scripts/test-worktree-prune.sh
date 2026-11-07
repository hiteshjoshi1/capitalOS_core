#!/bin/bash
# Tests for scripts/worktree-prune.sh (#269), run by `make lint`: a throwaway repo with merged,
# unmerged, dirty and test-instance worktrees, and a stub docker that records what it was asked.
set -euo pipefail
cd "$(dirname "$0")/.."
SCRIPT=$PWD/scripts/worktree-prune.sh
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
pass=0 fail=0
ok() { echo "ok   $1"; pass=$((pass + 1)); }
no() { echo "FAIL $1" >&2; fail=$((fail + 1)); }
check() { if eval "$2"; then ok "$1"; else no "$1"; fi; }

# Stub docker: logs every call; answers ps/volume/network/images queries for project
# capitalos-wt-issue-1-merged (and the protected capitalos-oss-test) with fake ids.
cat >"$TMP/docker" <<'EOF'
#!/bin/bash
echo "$*" >>"$DOCKER_LOG"
case "$*" in
  *"status=running"*"project=capitalos-wt-issue-5-running"*|*"project=capitalos-wt-issue-5-running"*"status=running"*) echo run5 ;;
  *"status=running"*) ;;
  *"project=capitalos-wt-issue-1-merged"*|*"reference=capitalos-wt-issue-1-merged-*"*) echo id1 ;;
  *"working_dir="*"issue-1-merged"*) echo capitalos-oss-test ;;
esac
exit 0
EOF
chmod +x "$TMP/docker"
export DOCKER="$TMP/docker" DOCKER_LOG="$TMP/docker.log" NO_FETCH=1

R="$TMP/repo" W="$TMP/capitalOS-worktrees"
git init -q -b main "$R"
git -C "$R" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
printf 'node_modules\n' >"$R/.gitignore"
git -C "$R" add .gitignore && git -C "$R" -c user.name=t -c user.email=t@t commit -q -m ignore
mkdir -p "$W"
add() { git -C "$R" worktree add -q -b "$2" "$W/$1" main; }
commitin() { git -C "$W/$1" -c user.name=t -c user.email=t@t commit -q --allow-empty -m "$2"; }
add issue-1-merged feature/issue-1-merged; commitin issue-1-merged work1
mkdir "$W/issue-1-merged/node_modules"; touch "$W/issue-1-merged/node_modules/x"  # ignored: fine
add issue-2-open feature/issue-2-open; commitin issue-2-open work2
add issue-3-dirty feature/issue-3-dirty; commitin issue-3-dirty work3; touch "$W/issue-3-dirty/new.txt"
add test-instance test/20260101-0000
add issue-4-fresh feature/issue-4-fresh                 # no commits yet: work about to start
add issue-5-running feature/issue-5-running; commitin issue-5-running work5
git -C "$R" merge -q --no-ff -m merge1 feature/issue-1-merged
git -C "$R" merge -q --no-ff -m merge3 feature/issue-3-dirty
git -C "$R" merge -q --no-ff -m merge5 feature/issue-5-running
git -C "$R" update-ref refs/remotes/origin/main main

out=$(cd "$R" && "$SCRIPT")
check "dry run lists the merged worktree" 'grep -q "would prune issue-1-merged" <<<"$out"'
check "dry run names its Docker resources" 'grep -q "capitalos-wt-issue-1-merged: 1 containers, 1 volumes, 1 networks" <<<"$out"'
check "an unmerged branch is kept, with the reason" 'grep -q "keep  issue-2-open (feature/issue-2-open): not merged" <<<"$out"'
check "a dirty worktree is kept, even when merged" 'grep -q "keep  issue-3-dirty.*uncommitted or untracked" <<<"$out"'
check "a fresh branch with no commits of its own is kept" 'grep -q "keep  issue-4-fresh.*no commits of its own yet" <<<"$out"'
check "a merged worktree with a running stack is kept" 'grep -q "keep  issue-5-running.*its stack is running" <<<"$out"'
check "the test instance and main checkout are never listed" '! grep -qE "test-instance|repo " <<<"$out"'
check "dry run removes nothing" '[ -d "$W/issue-1-merged" ] && ! grep -qE "^(rm|volume rm|network rm|image rm)" "$DOCKER_LOG"'

: >"$DOCKER_LOG"
out=$(cd "$R" && APPLY=1 "$SCRIPT")
check "apply removes the worktree" '[ ! -d "$W/issue-1-merged" ]'
check "apply deletes the merged branch" '! git -C "$R" show-ref -q refs/heads/feature/issue-1-merged'
check "apply removes containers, volumes, networks and images" 'grep -q "^rm -f id1" "$DOCKER_LOG" && grep -q "^volume rm id1" "$DOCKER_LOG" && grep -q "^network rm id1" "$DOCKER_LOG" && grep -q "^image rm -f id1" "$DOCKER_LOG"'
check "a protected project found by working dir is skipped" 'grep -q "skip project capitalos-oss-test (protected)" <<<"$out" && ! grep -q "project=capitalos-oss-test" <(grep -E "^(rm|volume rm|network rm)" "$DOCKER_LOG")'
check "unmerged, dirty and test-instance worktrees survive" '[ -d "$W/issue-2-open" ] && [ -d "$W/issue-3-dirty" ] && [ -d "$W/issue-4-fresh" ] && [ -d "$W/issue-5-running" ] && [ -d "$W/test-instance" ]'
check "summary counts" 'grep -q "Pruned 1 worktree(s); kept 4." <<<"$out"'

echo "worktree-prune: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
