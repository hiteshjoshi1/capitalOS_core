#!/bin/bash
# Stdio launcher for the capitalos-postgres MCP server: Google MCP Toolbox
# (`--prebuilt postgres`) in Docker, connecting as the read-only role from
# `make db-create-mcp-role`. The image reference lives in tools/Dockerfile.
#
# Killing the `docker run` client does not stop the container, so launching it
# directly can leak one running container per Claude session. This wrapper names
# and labels the container, removes it when this script or the owning Claude
# process goes away, and reaps leftovers whose owner is no longer running.
#
# Env: MCP_PG_NETWORK (docker network of the target Postgres), MCP_PG_HOST,
# MCP_PG_DATABASE, MCP_PG_USER, MCP_DB_PASSWORD (default: read from the repo .env).
set -u

ROOT=$(cd "$(dirname "$0")/.." && pwd)
IMAGE=$("$ROOT/scripts/tool-image.sh" mcp-toolbox) || exit 1
NETWORK=${MCP_PG_NETWORK:-capitalos_default}
if [ -z "${MCP_DB_PASSWORD:-}" ] && [ -f "$ROOT/.env" ]; then
  MCP_DB_PASSWORD=$(sed -n 's/^MCP_DB_PASSWORD=//p' "$ROOT/.env" | tail -1)
fi
if [ -z "${MCP_DB_PASSWORD:-}" ]; then
  echo "mcp-postgres: MCP_DB_PASSWORD not set; run 'make db-create-mcp-role' first" >&2
  exit 1
fi
export POSTGRES_HOST=${MCP_PG_HOST:-postgres}
export POSTGRES_PORT=5432
export POSTGRES_DATABASE=${MCP_PG_DATABASE:-capitalos}
export POSTGRES_USER=${MCP_PG_USER:-capitalos_mcp_ro}
export POSTGRES_PASSWORD=$MCP_DB_PASSWORD
LABEL=capitalos.mcp-postgres
OWNER=$PPID
NAME="capitalos-mcp-pg-$$"

for id in $(docker ps -aq --filter "label=$LABEL"); do
  pid=$(docker inspect -f "{{index .Config.Labels \"$LABEL.owner\"}}" "$id" 2>/dev/null)
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    docker rm -f "$id" >/dev/null 2>&1
  fi
done

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1; }
trap 'cleanup; exit 143' INT TERM HUP
trap cleanup EXIT

# Watchdog: also covers a SIGKILL of this script or the owner exiting without
# signalling us.
(
  trap '' INT TERM HUP
  while kill -0 $$ 2>/dev/null && kill -0 "$OWNER" 2>/dev/null; do sleep 5; done
  docker rm -f "$NAME" >/dev/null 2>&1
) </dev/null >/dev/null 2>&1 &

# Backgrounded + `wait` so a TERM is handled immediately instead of after the
# (never-ending) foreground child; `<&0` keeps stdin attached to the MCP stream.
# Same runtime hardening as the compose services (see docker-compose.yml).
docker run -i --rm --name "$NAME" \
  --label "$LABEL=1" --label "$LABEL.owner=$OWNER" \
  --read-only --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 128 \
  --network "$NETWORK" \
  -e POSTGRES_HOST -e POSTGRES_PORT -e POSTGRES_DATABASE -e POSTGRES_USER -e POSTGRES_PASSWORD \
  "$IMAGE" --prebuilt postgres --stdio "$@" <&0 &
wait $!
