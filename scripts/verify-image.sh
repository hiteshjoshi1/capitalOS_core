#!/bin/sh
# Check that a pinned image comes from its real publisher before adopting it
# (issue 214). Run on the new ref in a Dependabot bump PR, or on all pinned
# images with `make verify-images`.
#
# Trust policy per repository, using the strongest evidence each publisher offers:
#   signature   - cosign keyless signature from the publisher's CI identity
#   provenance  - BuildKit SLSA provenance that names the expected source repo
#   attested    - provenance attestation present (no checkable source field)
#   pin-only    - publisher ships no signature/provenance: digest pin + Trivy gate
# A repository with no policy FAILS, so a new image forces a decision.
set -eu
ref=${1:?usage: verify-image.sh <image:tag@sha256:digest>}
root=$(cd "$(dirname "$0")/.." && pwd)
name=${ref%@*}
repo=${name%:*}

case "$ref" in
  *@sha256:*) ;;
  *) echo "FAIL $name: not pinned by digest" >&2; exit 1 ;;
esac

provenance() {
  docker buildx imagetools inspect "$ref" --format '{{json .Provenance}}'
}

# Succeeds if any string in the provenance JSON contains $1 (layouts differ
# between SLSA v0.2 and v1, so match on content rather than on a path).
provenance_mentions() {
  provenance | python3 -c '
import json, sys
needle = sys.argv[1]
def strings(o):
    if isinstance(o, dict):
        for v in o.values(): yield from strings(v)
    elif isinstance(o, list):
        for v in o: yield from strings(v)
    elif isinstance(o, str):
        yield o
data = json.load(sys.stdin) or {}
sys.exit(0 if any(needle in s for s in strings(data)) else 1)' "$1"
}

provenance_present() {
  provenance | python3 -c 'import json, sys; sys.exit(0 if json.load(sys.stdin) else 1)'
}

# Keyless cosign signature whose certificate matches the publisher's signing identity.
# Args: <identity regexp> <OIDC issuer> <description>
signed_by() {
  cosign=$("$root/scripts/tool-image.sh" cosign)
  if docker run --rm "$cosign" verify "$ref" \
      --certificate-identity-regexp "$1" --certificate-oidc-issuer "$2" >/dev/null 2>&1; then
    echo "OK   $name: cosign signature from $3"
  else
    echo "FAIL $name: cosign signature missing or not from $3" >&2; exit 1
  fi
}
GHA=https://token.actions.githubusercontent.com

case "$repo" in
  aquasec/trivy)
    signed_by '^https://github.com/aquasecurity/trivy/' "$GHA" "aquasecurity/trivy GitHub Actions" ;;
  ghcr.io/sigstore/cosign/cosign)
    signed_by '^keyless@projectsigstore[.]iam[.]gserviceaccount[.]com$' https://accounts.google.com "Sigstore's release service account" ;;
  postgres | python)
    if provenance_mentions "github.com/docker-library/$repo"; then
      echo "OK   $name: SLSA provenance from github.com/docker-library/$repo (Docker Official Image)"
    else
      echo "FAIL $name: provenance missing or not built from docker-library/$repo" >&2; exit 1
    fi ;;
  grafana/alloy | tecnativa/docker-socket-proxy | us-central1-docker.pkg.dev/database-toolbox/toolbox/toolbox)
    if provenance_present; then
      echo "OK   $name: SLSA provenance attestation present"
    else
      echo "FAIL $name: provenance attestation missing (publisher normally ships one)" >&2; exit 1
    fi ;;
  grafana/loki | grafana/grafana)
    echo "INFO $name: publisher ships no signature/provenance; trusted via digest pin + Trivy gate" ;;
  *)
    echo "FAIL $name: no trust policy for '$repo'; add one to scripts/verify-image.sh" >&2; exit 1 ;;
esac
