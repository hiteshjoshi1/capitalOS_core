#!/usr/bin/env bash
# PreToolUse safety net for Bash commands.
# Denies a small, explicit set of destructive patterns so the project can run
# with a curated allowlist instead of dangerous-skip-permissions mode.
# Tests: scripts/test-pretooluse-guard.sh (cases in scripts/test-pretooluse-guard.cases), run by `make lint`.
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

# Rule 2's reader (#255, D-70): pretooluse-force-push.awk splits the command into simple
# commands the way the shell does and exits 0 when one of them is a forced git push (its
# header says what it reads and what it can't see). A command with no `push` in it once
# quotes and backslashes are dropped skips it. If awk fails (status 2: a missing file, an awk
# without split-into-characters), the old whole-command check decides: it fails closed.
force_push_reader="$(cd "$(dirname "$0")" && pwd)/pretooluse-force-push.awk"
command_force_pushes() {
  case $(printf '%s' "$1" | tr -d "'\"\\\\") in *push*) ;; *) return 1 ;; esac
  local rc=0
  printf '%s' "$1" | LC_ALL=C awk -f "$force_push_reader" 2>/dev/null || rc=$?
  case $rc in
    0) return 0 ;;
    1) return 1 ;;
    *) printf '%s' "$lower_cmd" | grep -qE 'git[[:space:]]+push' &&
         printf '%s' "$lower_cmd" | grep -qE '(--force(-with-lease)?\b|[[:space:]]-f\b)' ;;
  esac
}

# 1. rm -rf (or -fr, -r -f, etc.) outside the /private/tmp scratchpad.
if printf '%s' "$lower_cmd" | grep -qE '\brm[[:space:]]+(-[a-z]*r[a-z]*f[a-z]*|-[a-z]*f[a-z]*r[a-z]*|-r[[:space:]]+-f|-f[[:space:]]+-r)\b'; then
  if ! printf '%s' "$cmd" | grep -q '/private/tmp'; then
    deny "rm -rf outside /private/tmp scratchpad is blocked. Run it manually in a terminal if truly intended."
  fi
fi

# 2. Force push: a `git push` (also `git -C dir push`) whose own arguments force it: -f (also
# in -fu), --force, --force-with-lease, --force-if-includes, --mirror or a +refspec. Other
# commands in the same line (git commit -F msg && git push) and quoted text don't count (#255).
if command_force_pushes "$cmd"; then
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
