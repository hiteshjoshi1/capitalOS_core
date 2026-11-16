#!/bin/bash
# Smoke check for the capitalos-postgres MCP (#442): starts scripts/mcp-postgres.sh over stdio,
# sends initialize and one read-only SELECT, and passes when the SELECT answers. Read-only.
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
req() { printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"mcp-check","version":"0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"execute_sql","arguments":{"sql":"select count(*) as accounts from accounts"}}}'; sleep "${MCP_CHECK_WAIT:-8}"; }
out=$(req | perl -e 'alarm 45; exec @ARGV' bash "$ROOT/scripts/mcp-postgres.sh" 2>&1)
if printf '%s' "$out" | grep -q '"id":2,"result"'; then
  echo "MCP ok: $(printf '%s' "$out" | grep -o '\\"accounts\\":[0-9]*' | head -1 | tr -d '\\"')"
else
  echo "MCP FAILED:" >&2; printf '%s\n' "$out" | tail -5 >&2; exit 1
fi
