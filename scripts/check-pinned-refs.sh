#!/bin/sh
# Fail if any image or GitHub Action is referenced by a mutable tag instead of
# a digest / commit SHA (issue 211). Dependabot keeps the pins current.
#   - docker-compose*.yml `image:` lines and Dockerfile `FROM` lines need @sha256:
#     (`FROM <stage>` lines that name an earlier build stage are allowed).
#   - workflow `uses:` lines need a 40-hex commit SHA (local `./` actions allowed).
set -eu
cd "$(dirname "$0")/.."
bad=$(
  {
    grep -nE '^[[:space:]]*image:' docker-compose*.yml 2>/dev/null | grep -v '@sha256:' || true
    for f in $(git ls-files '*Dockerfile*'); do
      stages=$(sed -n 's/^FROM .* [Aa][Ss] \([^ ]*\)$/\1/p' "$f")
      grep -nE '^FROM ' "$f" | grep -v '@sha256:' | while IFS= read -r line; do
        ref=$(printf '%s\n' "$line" | sed 's/^[0-9]*:FROM \([^ ]*\).*/\1/')
        printf '%s\n' $stages | grep -qx "$ref" || printf '%s:%s\n' "$f" "$line"
      done
    done
    grep -nE '^[[:space:]]*(- )?uses:' .github/workflows/*.yml | grep -vE 'uses: *\./' | grep -vE '@[0-9a-f]{40}( |$)' || true
  }
)
if [ -n "$bad" ]; then
  echo "Unpinned references (pin by @sha256:<digest> / full commit SHA):" >&2
  printf '%s\n' "$bad" >&2
  exit 1
fi
echo "All image and action references are pinned."
