#!/usr/bin/env bash
# PreToolUse safety net for Bash commands.
# Denies a small, explicit set of destructive patterns so the project can run
# with a curated allowlist instead of dangerous-skip-permissions mode.
set -euo pipefail

input="$(cat)"
cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // empty')"

if [ -z "$cmd" ]; then
  exit 0
fi

deny() {
  local reason="$1"
  jq -n --arg reason "$reason" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    },
    systemMessage: ("Blocked by safety hook: " + $reason)
  }'
  exit 0
}

lower_cmd="$(printf '%s' "$cmd" | tr '[:upper:]' '[:lower:]')"

# 1. rm -rf (or -fr, -r -f, etc.) outside the /private/tmp scratchpad.
if printf '%s' "$lower_cmd" | grep -qE '\brm[[:space:]]+(-[a-z]*r[a-z]*f[a-z]*|-[a-z]*f[a-z]*r[a-z]*|-r[[:space:]]+-f|-f[[:space:]]+-r)\b'; then
  if ! printf '%s' "$cmd" | grep -q '/private/tmp'; then
    deny "rm -rf outside /private/tmp scratchpad is blocked. Run it manually in a terminal if truly intended."
  fi
fi

# 2. Force push.
if printf '%s' "$lower_cmd" | grep -qE 'git[[:space:]]+push' && printf '%s' "$lower_cmd" | grep -qE '(--force(-with-lease)?\b|[[:space:]]-f\b)'; then
  deny "git push --force (or -f) is blocked. Force-pushing can overwrite remote/collaborator history — run it manually if truly intended."
fi

# 3. Destructive make targets.
if printf '%s' "$lower_cmd" | grep -qE '\bmake[[:space:]]+(db-reset|db-clear-[a-z_]+)\b'; then
  deny "Destructive make target ('$cmd') is blocked. Run it manually in a terminal if you really want to wipe data."
fi

# 4. Raw destructive SQL.
if printf '%s' "$lower_cmd" | grep -qE '\bdrop[[:space:]]+table\b'; then
  deny "Raw SQL DROP TABLE is blocked. Use a numbered migrations/NNN_*.sql file + make db-migrate instead."
fi
if printf '%s' "$lower_cmd" | grep -qE '\btruncate\b'; then
  deny "Raw SQL TRUNCATE is blocked. Use a numbered migrations/NNN_*.sql file + make db-migrate instead."
fi
if printf '%s' "$lower_cmd" | grep -qE '\bdelete[[:space:]]+from\b'; then
  if ! printf '%s' "$lower_cmd" | grep -qE '\bwhere\b'; then
    deny "Raw SQL DELETE FROM without a WHERE clause is blocked (would delete every row). Add a WHERE or run it manually if intended."
  fi
fi

exit 0
