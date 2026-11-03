#!/bin/bash
# Remove log lines that carried an IBKR Flex Web Service URL (token in `?t=`) from
# Loki, and report whether the API container's own log still has any (#114).
# Run after the redaction fix is deployed, or new lines just come back.
#   OBSERVABILITY_COMPOSE="docker compose -p ..." API_COMPOSE="docker compose -p ..." scripts/logs-purge-secrets.sh
set -euo pipefail

: "${OBSERVABILITY_COMPOSE:?set by make}"
: "${API_COMPOSE:?set by make}"
MATCH='FlexWebService'
# Only the API calls IBKR. Matching every service also counted Loki's own logs of
# these very queries (thousands of lines, no token in them).
SELECTOR='{service="api"}'
LOKI=http://loki:3100

# Loki isn't published on the host; Grafana shares its network and has curl.
loki() { $OBSERVABILITY_COMPOSE exec -T grafana curl -fsS "$@"; }

count_loki() {
  loki -G "$LOKI/loki/api/v1/query" \
    --data-urlencode "query=sum(count_over_time($SELECTOR |= \"$MATCH\" [30d]))" |
    sed -n 's/.*"value":\[[0-9.]*,"\([0-9]*\)"\].*/\1/p'
}

before=$(count_loki)
echo "API lines in Loki matching $MATCH (last 30 days): ${before:-0}"
if [ "${before:-0}" != "0" ]; then
  loki -X POST -G "$LOKI/loki/api/v1/delete" \
    --data-urlencode "query=$SELECTOR |= \"$MATCH\"" \
    --data-urlencode "start=$(( $(date +%s) - 60 * 86400 ))" \
    --data-urlencode "end=$(date +%s)"
  echo "Delete request accepted. Loki applies it after its cancel period (24h by default);"
  echo "queries hide nothing until then. Pending requests: $LOKI/loki/api/v1/delete"
fi

api_id=$($API_COMPOSE ps -q api)
if [ -z "$api_id" ]; then
  echo "API container not running: no container log to check."
  exit 0
fi
# A recreated container (make deploy with a new image) starts a fresh log.
leaks=$(docker logs "$api_id" 2>&1 | grep -c "$MATCH.*[?&]t=[^[&]" || true)
echo "API container log lines with an unredacted Flex token: $leaks"
if [ "$leaks" != "0" ]; then
  echo "Recreate the API container to drop its log: $API_COMPOSE up -d --force-recreate api"
  exit 1
fi
