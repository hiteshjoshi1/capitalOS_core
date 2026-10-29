#!/bin/sh
# List (default) or remove (APPLY=1) local images this repo no longer uses:
#   - older versions of repositories we pin (postgres, grafana/*, python, ...)
#   - CapitalOS-built images other than this checkout's current ones
#   - dangling build layers labelled with this compose project
# Never touches an image any container (running or stopped) uses, never the
# currently pinned images, and never other projects' images from repositories
# we don't use. Never runs `docker system prune`.
# Env: COMPOSE_PROJECT (e.g. capitalos-oss-test), APPLY=1 to actually remove.
set -eu
cd "$(dirname "$0")/.."
project=${COMPOSE_PROJECT:-capitalos}

pinned=$( { docker compose -f docker-compose.yml --profile observability config --images 2>/dev/null | grep -v -- '-api' || true
            sed -n 's/^FROM \([^ ]*\) AS .*/\1/p' tools/Dockerfile api/Dockerfile | grep '@sha256:' ; } | sort -u )
repos=$(printf '%s\n' "$pinned" | sed 's/@.*//; s/:[^:/]*$//' | sort -u)
keep_ids=$(for r in $pinned; do docker image inspect -f '{{.Id}}' "$r" 2>/dev/null || true; done)
used_ids=$(docker ps -aq | xargs -r docker inspect -f '{{.Image}}' 2>/dev/null || true)

candidates=$(
  docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' --no-trunc | while read -r image id; do
    repo=${image%:*}
    case "$image" in
      ("$project"-api:*|"$project"-api-dev:*|capitalos-api:security-scan) continue ;;
    esac
    if ! printf '%s\n' "$repos" | grep -qx "$repo"; then
      case "$repo" in (capitalos*) : ;; (*) continue ;; esac
    fi
    if printf '%s\n' "$keep_ids" "$used_ids" | grep -q "$id"; then continue; fi
    echo "$image"
  done
  docker images -q --filter dangling=true --filter "label=com.docker.compose.project=$project"
)

if [ -z "$candidates" ]; then echo "Nothing to prune."; exit 0; fi
if [ "${APPLY:-0}" = "1" ]; then
  printf '%s\n' "$candidates" | xargs docker image rm
else
  echo "Unused images (run with APPLY=1 to remove):"
  printf '  %s\n' $candidates
fi
