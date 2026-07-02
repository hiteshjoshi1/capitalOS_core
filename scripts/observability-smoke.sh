#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

ENV_FILE="config/observability.env"
if [ ! -f "$ENV_FILE" ]; then
  ENV_FILE="config/observability.env.example"
fi

set -a
. "$ENV_FILE"
set +a

LOKI_URL=${LOKI_URL:-http://127.0.0.1:3100}
GRAFANA_URL=${GRAFANA_URL:-http://127.0.0.1:3000}
API_URL=${API_URL:-http://127.0.0.1:8000}
OBSERVABILITY_ENV=${OBSERVABILITY_ENV:-local}

echo "Starting API and observability services..."
docker compose --env-file "$ENV_FILE" up -d api loki grafana alloy

echo "Waiting for Loki readiness..."
attempt=1
while [ "$attempt" -le 30 ]; do
  if curl -fsS "$LOKI_URL/ready" >/dev/null 2>&1; then
    break
  fi
  if [ "$attempt" -eq 30 ]; then
    echo "Loki did not become ready." >&2
    exit 1
  fi
  attempt=$((attempt + 1))
  sleep 2
done

echo "Waiting for Grafana health..."
attempt=1
while [ "$attempt" -le 30 ]; do
  if curl -fsS "$GRAFANA_URL/api/health" >/dev/null 2>&1; then
    break
  fi
  if [ "$attempt" -eq 30 ]; then
    echo "Grafana did not become healthy." >&2
    exit 1
  fi
  attempt=$((attempt + 1))
  sleep 2
done

alloy_running=$(docker inspect -f '{{.State.Running}}' capitalos-alloy 2>/dev/null || true)
if [ "$alloy_running" != "true" ]; then
  echo "Alloy container is not running." >&2
  exit 1
fi

echo "Waiting for API health..."
attempt=1
while [ "$attempt" -le 30 ]; do
  if curl -fsS "$API_URL/health" >/dev/null 2>&1; then
    break
  fi
  if [ "$attempt" -eq 30 ]; then
    echo "API did not become healthy." >&2
    exit 1
  fi
  attempt=$((attempt + 1))
  sleep 2
done

SMOKE_ID="observability-smoke-$(date +%s)-$$"
echo "Generating API access log marker: $SMOKE_ID"
curl -fsS "$API_URL/health?observability_smoke=$SMOKE_ID" >/dev/null

query=$(python3 - "$SMOKE_ID" "$OBSERVABILITY_ENV" <<'PY'
import sys
from urllib.parse import quote

smoke_id = sys.argv[1]
environment = sys.argv[2]
logql = f'{{service="api",environment="{environment}"}} |= "{smoke_id}"'
print(quote(logql, safe=""))
PY
)
end_seconds=$(date +%s)
start_seconds=$((end_seconds - 300))
start="${start_seconds}000000000"

echo "Querying Loki for API access log marker..."
attempt=1
while [ "$attempt" -le 30 ]; do
  response=$(curl -fsS "$LOKI_URL/loki/api/v1/query_range?query=$query&start=$start&limit=20" || true)
  count=$(printf '%s' "$response" | python3 -c '
import json
import sys

raw = sys.stdin.read()
try:
    payload = json.loads(raw)
except json.JSONDecodeError:
    print(0)
    raise SystemExit

streams = payload.get("data", {}).get("result", [])
print(sum(len(stream.get("values", [])) for stream in streams))
')
  if [ "$count" -gt 0 ]; then
    echo "Observability smoke passed: found $count Loki log line(s)."
    exit 0
  fi
  attempt=$((attempt + 1))
  sleep 2
done

echo "Observability smoke failed: marker was not found in Loki." >&2
exit 1
