#!/bin/bash
# Remove merged worktrees and everything their isolated stacks left in Docker (#269).
#   worktree-prune.sh            list what would go (dry run, the default)
#   APPLY=1 worktree-prune.sh    remove it
#
# A worktree is pruned when its branch was merged into origin/main and its tree is clean (no tracked
# changes, no untracked files; ignored files like node_modules don't count). "Merged" means the tip is
# an ancestor of origin/main that came in through a merge: a fresh branch with no commits of its own
# sits on main's first-parent line, so it is kept (work about to start). A worktree whose stack has a
# running container is kept too.
# For each one: the compose project's containers, volumes, networks and built images (found by
# compose labels: the project name the Makefile derives from the directory, plus any project whose
# containers ran from that directory), then `git worktree remove` and `git branch -d`.
# Never touched: the main checkout, the test instance (make test-instance-drop), a worktree whose
# branch isn't merged, has no commits yet, is dirty or has a running stack (each listed with the
# reason), and the real-data, default and test-instance projects.
# DOCKER (default: docker) and BASE (default: origin/main) can be overridden, e.g. by the test.
set -euo pipefail

DOCKER=${DOCKER:-docker}
BASE=${BASE:-origin/main}
APPLY=${APPLY:-0}
MAIN=$(cd "$(git rev-parse --git-common-dir)/.." && pwd -P)
PROTECTED_PROJECTS="capitalos capitalos-oss-test capitalos-test"

[ "${NO_FETCH:-0}" = 1 ] || git -C "$MAIN" fetch -q origin 2>/dev/null || echo "worktree-prune: fetch failed; using the last fetched $BASE" >&2
git -C "$MAIN" worktree prune  # forget worktrees whose directory is already gone

# The compose project name the Makefile gives a worktree (ISO_NAME): capitalos-wt-<dir, sanitised>.
iso_name() { printf 'capitalos-wt-%s\n' "$(basename "$1" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9\n' '-' | sed 's/-*$//')"; }

projects_for() {  # projects_for DIR: the derived name, plus projects whose containers ran from DIR
  {
    iso_name "$1"
    $DOCKER ps -a --filter "label=com.docker.compose.project.working_dir=$1" \
      --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null || true
  } | sed '/^$/d' | sort -u
}

drop_project() {  # drop_project NAME: containers, volumes, networks, images labelled with it
  local p=$1 ids
  case " $PROTECTED_PROJECTS " in (*" $p "*) echo "  skip project $p (protected)"; return 0 ;; esac
  ids=$($DOCKER ps -aq --filter "label=com.docker.compose.project=$p" 2>/dev/null || true)
  [ -n "$ids" ] && $DOCKER rm -f $ids >/dev/null
  ids=$($DOCKER volume ls -q --filter "label=com.docker.compose.project=$p" 2>/dev/null || true)
  [ -n "$ids" ] && $DOCKER volume rm $ids >/dev/null
  ids=$($DOCKER network ls -q --filter "label=com.docker.compose.project=$p" 2>/dev/null || true)
  [ -n "$ids" ] && $DOCKER network rm $ids >/dev/null
  ids=$($DOCKER images -q --filter "reference=$p-*" 2>/dev/null | sort -u || true)
  [ -n "$ids" ] && { $DOCKER image rm -f $ids >/dev/null 2>&1 || true; }
  return 0
}

count() {  # count KIND PROJECT
  local p=$2
  case $1 in
    containers) $DOCKER ps -aq --filter "label=com.docker.compose.project=$p" 2>/dev/null | wc -l ;;
    volumes) $DOCKER volume ls -q --filter "label=com.docker.compose.project=$p" 2>/dev/null | wc -l ;;
    networks) $DOCKER network ls -q --filter "label=com.docker.compose.project=$p" 2>/dev/null | wc -l ;;
  esac | tr -d ' '
}

# main's own commits: a branch tip here has no work of its own (a fresh worktree), never "merged".
FIRST_PARENT=$(git -C "$MAIN" rev-list --first-parent "$BASE")

pruned=0 kept=0
while IFS= read -r line; do
  case $line in
    "worktree "*) dir=${line#worktree }; branch="" ;;
    "branch "*) branch=${line#branch refs/heads/} ;;
    "") [ -n "${dir:-}" ] || continue
        d=$dir; b=$branch; dir=""
        [ "$(cd "$d" 2>/dev/null && pwd -P)" = "$MAIN" ] && continue
        [ "$(basename "$d")" = test-instance ] && continue
        reason=""
        if [ -z "$b" ]; then reason="detached HEAD"
        elif ! git -C "$MAIN" merge-base --is-ancestor "refs/heads/$b" "$BASE" 2>/dev/null; then reason="not merged into $BASE"
        elif grep -qx "$(git -C "$MAIN" rev-parse "refs/heads/$b")" <<<"$FIRST_PARENT"; then reason="no commits of its own yet"
        elif [ -n "$(git -C "$d" status --porcelain 2>/dev/null)" ]; then reason="uncommitted or untracked changes"
        else
          for p in $(projects_for "$d"); do
            [ -n "$($DOCKER ps -q --filter "label=com.docker.compose.project=$p" --filter status=running 2>/dev/null)" ] && reason="its stack is running ($p): make down there first"
          done
        fi
        if [ -n "$reason" ]; then
          echo "keep  $(basename "$d") ($b): $reason"; kept=$((kept + 1)); continue
        fi
        projects=$(projects_for "$d")
        summary=$(for p in $projects; do printf '%s: %s containers, %s volumes, %s networks; ' "$p" "$(count containers "$p")" "$(count volumes "$p")" "$(count networks "$p")"; done)
        if [ "$APPLY" = 1 ]; then
          echo "prune $(basename "$d") ($b): ${summary%; }"
          for p in $projects; do drop_project "$p"; done
          git -C "$MAIN" worktree remove "$d"
          git -C "$MAIN" branch -d "$b" >/dev/null
        else
          echo "would prune $(basename "$d") ($b): ${summary%; }"
        fi
        pruned=$((pruned + 1))
        ;;
  esac
done < <(git -C "$MAIN" worktree list --porcelain; echo)

if [ "$APPLY" = 1 ]; then
  echo "Pruned $pruned worktree(s); kept $kept."
else
  echo "$pruned merged worktree(s) to prune, $kept kept. Run with APPLY=1 to remove them."
fi
