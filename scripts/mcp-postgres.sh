#!/bin/bash
# Stdio launcher for the capitalos-postgres MCP server (crystaldba/postgres-mcp in Docker).
#
# postgres-mcp does not exit when its stdin closes, and killing the `docker run`
# client does not stop the container, so launching it directly leaks one running
# container per Claude session. This wrapper names and labels the container,
# removes it when this script or the owning Claude process goes away, and reaps
# leftovers whose owner is no longer running.
#
# Env: MCP_PG_NETWORK (docker network of the target Postgres), DATABASE_URI.
set -u

NETWORK=${MCP_PG_NETWORK:-capitalos_default}
export DATABASE_URI=${DATABASE_URI:-postgresql://capitalos:capitalos@postgres:5432/capitalos}
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
docker run -i --rm --name "$NAME" \
  --label "$LABEL=1" --label "$LABEL.owner=$OWNER" \
  --network "$NETWORK" -e DATABASE_URI \
  crystaldba/postgres-mcp --access-mode=restricted "$@" <&0 &
wait $!
