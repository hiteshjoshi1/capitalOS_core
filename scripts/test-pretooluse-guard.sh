#!/bin/bash
# Tests for the PreToolUse guard (.claude/hooks/pretooluse-guard.sh, #255), run by `make lint`.
# Each case in scripts/test-pretooluse-guard.cases (or the file given as $1) goes to the hook the
# way Claude Code sends a Bash call (JSON on stdin, the command in .tool_input.command) and must
# be blocked (a "deny" decision) or pass. The hook only reads the command; nothing is run.
# Every case runs under the bash on PATH and, when it differs, /bin/bash (3.2 on macOS).
set -euo pipefail

src=$(cd "$(dirname "$0")/.." && pwd)
hook=$src/.claude/hooks/pretooluse-guard.sh
cases=${1:-$src/scripts/test-pretooluse-guard.cases}
command -v jq >/dev/null || { echo "test-pretooluse-guard: jq is required" >&2; exit 2; }
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

shells=("$(command -v bash)")
if [ -x /bin/bash ] && [ "$(/bin/bash -c 'echo "$BASH_VERSION"')" != "$(bash -c 'echo "$BASH_VERSION"')" ]; then
  shells+=(/bin/bash)
fi

pass=0 fail=0
ok() { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); echo "FAIL $1"; }

decide() {  # <shell> <command>: prints block or pass; fails if the hook fails or writes to stderr
  local out
  out=$(jq -n --arg c "$2" '{tool_name: "Bash", tool_input: {command: $c}}' | "$1" "$hook" 2>"$tmp/err") || return 1
  [ ! -s "$tmp/err" ] || return 1
  if printf '%s' "$out" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1; then
    echo block
  else
    echo pass
  fi
}

run_case() {  # <block|pass> <description> <command>
  local sh got
  while [[ $3 == *$'\n' ]]; do set -- "$1" "$2" "${3%$'\n'}"; done
  for sh in "${shells[@]}"; do
    if ! got=$(decide "$sh" "$3"); then
      bad "$2 [$sh]: the hook failed: $(cat "$tmp/err")"
    elif [ "$got" = "$1" ]; then
      ok
    else
      bad "$2 [$sh]: expected $1, got $got"
      printf '%s\n' "$3" | sed 's/^/     | /'
    fi
  done
}

expect='' desc='' body='' n=0
while IFS= read -r line || [ -n "$line" ]; do
  case $line in
    '=== block: '* | '=== pass: '*)
      if [ -n "$expect" ]; then run_case "$expect" "$desc" "$body"; n=$((n + 1)); fi
      expect=${line#=== }; expect=${expect%%:*}; desc=${line#*: }; body='' ;;
    *)
      if [ -n "$expect" ]; then body=$body$line$'\n'; fi ;;
  esac
done <"$cases"
if [ -n "$expect" ]; then run_case "$expect" "$desc" "$body"; n=$((n + 1)); fi
[ "$n" -gt 0 ] || { echo "test-pretooluse-guard: no cases in $cases" >&2; exit 2; }

# A long PR body (about 30 KB, through $(cat <<'EOF' ...)) passes well inside the hook's 10 s timeout.
big=$(printf 'Line %s: it does not git push -f (or --force); see (#255).\n' $(seq 1 500))
start=$(date +%s)
for sh in "${shells[@]}"; do
  got=$(decide "$sh" "gh pr create --body \"\$(cat <<'EOF'
$big
EOF
)\" && git push") || got=failed
  [ "$got" = pass ] && ok || bad "a 30 KB PR body [$sh]: got $got"
done
elapsed=$(($(date +%s) - start))
[ "$elapsed" -le $((3 * ${#shells[@]})) ] && ok || bad "a 30 KB PR body took ${elapsed}s"

# Without its awk reader (status 2) the hook falls back to the old whole-command check: a
# forced push is still refused, a plain one passes, and the hook itself doesn't fail.
mkdir -p "$tmp/noreader"
cp "$hook" "$tmp/noreader/pretooluse-guard.sh"
hook=$tmp/noreader/pretooluse-guard.sh
for sh in "${shells[@]}"; do
  got=$(decide "$sh" "git push --force origin main") || got=failed
  [ "$got" = block ] && ok || bad "without the reader, a forced push [$sh]: got $got"
  got=$(decide "$sh" "git push origin main") || got=failed
  [ "$got" = pass ] && ok || bad "without the reader, a plain push [$sh]: got $got"
done

echo "pretooluse guard: $n cases x ${#shells[@]} shell(s), $pass passed, $fail failed"
[ "$fail" -eq 0 ]
