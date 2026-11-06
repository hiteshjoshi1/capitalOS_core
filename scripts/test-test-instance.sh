#!/bin/bash
# Tests for how the test instance names a batch's issues (#219), run by `make lint`: the TEST
# banner (banner_refs) and the test PR's "Closes" / "Part of" lines (batch_issues). A stub `gh`
# on PATH answers for the PRs, so nothing reaches GitHub, Docker or any checkout.
set -euo pipefail

src=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
# shellcheck source=test-instance.sh
. "$src/scripts/test-instance.sh"

pass=0 fail=0
ok() { pass=$((pass + 1)); echo "ok   $1"; }
bad() { fail=$((fail + 1)); echo "FAIL $1"; }
expect() {  # <description> <expected> <actual>
  if [ "$2" = "$3" ]; then ok "$1"; else bad "$1"; printf '     expected: %s\n     got:      %s\n' "$2" "$3"; fi
}
refs() {  # <pr> <title> <closing> <body>: pr_issue_refs on one line
  printf '%s' "$4" | pr_issue_refs "$1" "$2" "$3" | tr '\n' ',' | sed 's/,$//'
}

# --- One PR -------------------------------------------------------------------------------
expect "GitHub's closing references" "close 158" \
  "$(refs 217 'DB guardrails (#158)' '158' 'Guardrails from #130 findings.')"
expect "Closes/Fixes/Resolves in the body, CRLF and a colon, in order, once each" "close 12,close 13,close 14" \
  "$(refs 300 'Something' '' $'Fixes #12\r\nCloses: #13\r\nresolved #14 and closes #12\r\n')"
expect "a closing reference and the same issue in the body count once" "close 211" \
  "$(refs 214 'Spending months (#211)' '211' $'## Summary\nCloses #211')"
expect "a PR that closes an issue isn't also 'part of' one" "close 211" \
  "$(refs 214 'Spending months (#211)' '211' 'Part 2 of the per-user timezone. Part of #202.')"
expect "'Part of #n' in the body" "part 49" \
  "$(refs 215 'Dependabot batch 8' '' $'## Summary\nPart of #49.')"
expect "'Refs #n' in the body" "part 7" \
  "$(refs 301 'Something' '' 'Refs #7')"
expect "the known failure: Dependabot batch titled '... (#49)', no keyword in the body" "part 49" \
  "$(refs 215 'Dependabot batch 7: SQLAlchemy 2.1.5, starlette 1.9.0, eslint 10.13.0 (#49)' '' \
    $'## Summary\nDependabot batch 7 for #49.\n\n**Supersedes:** #111, #110. #89 stays open and this PR does not close it.')"
expect "the body's 'Part of' wins over the title" "part 219" \
  "$(refs 302 'Banner fix (#999)' '' 'Part of #219')"
expect "a '(#n)' not at the end of the title isn't used" "pr 303" \
  "$(refs 303 'Follow-up to (#12) for the banner' '' 'Nothing here.')"
expect "keywords inside words don't count (prefixes, prefers)" "pr 304" \
  "$(refs 304 'Something' '' 'Prefixes #5 and prefers #6 and unclosed #8')"
expect "no issue anywhere: the PR itself" "pr 305" \
  "$(refs 305 'Something' '' '')"

# --- A batch, through a stub gh -----------------------------------------------------------
mkdir -p "$tmp/bin"
cat >"$tmp/bin/gh" <<'EOF'
#!/bin/bash
# Stub: `gh pr view <n> --json closingIssuesReferences,title,body --jq ...` as test-instance.sh calls it.
[ "$1 $2" = "pr view" ] || { echo "stub gh: unexpected call: $*" >&2; exit 2; }
case "$3" in
  216) printf '%s\n' '207' 'Card history (#207)' '## Summary' 'Closes #207' ;;
  214) printf '%s\n' '211' 'Spending months (#211)' 'Part of #202' ;;
  217) printf '%s\n' '158' 'DB guardrails (#158)' 'Closes #158' ;;
  215) printf '%s\n' '' 'Dependabot batch 7: SQLAlchemy 2.1.5 (#49)' 'Dependabot batch 7 for #49.' ;;
  220) printf '%s\n' '' 'Dependabot batch 8 (#49)' 'Part of #49' ;;
  306) printf '%s\n' '' 'A PR with no issue' 'Nothing.' ;;
  *) echo "GraphQL: Could not resolve to a PullRequest with the number of $3." >&2; exit 1 ;;
esac
EOF
chmod +x "$tmp/bin/gh"
PATH="$tmp/bin:$PATH"
STATE=$tmp/state

printf 'branch=test/x\npending=\nmerged= 216 214 217 215 220 306\n' >"$STATE"
expect "banner: closed issues, then 'part of' ones, then a bare PR, in batch order, once each" \
  "207 211 158 49 306" "$(banner_refs | tr '\n' ' ' | sed 's/ $//')"
expect "test PR: Closes only what the batch closes, Part of for the rest (never Closes #49)" \
  "Closes #158,Closes #207,Closes #211,Part of #49" "$(batch_issues | tr '\n' ',' | sed 's/,$//')"

printf 'branch=test/x\npending=\nmerged= 217 999\n' >"$STATE"
expect "banner: a PR gh can't read shows as itself" "158 999" "$(banner_refs | tr '\n' ' ' | sed 's/ $//')"
if out=$(batch_issues 2>&1); then bad "test PR: a PR gh can't read must stop it (got: $out)"
elif printf '%s' "$out" | grep -q '#999'; then ok "test PR: a PR gh can't read stops it, named"
else bad "test PR: failed without naming the PR ($out)"; fi

echo "test-instance issue refs: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
