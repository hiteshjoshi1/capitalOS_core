#!/bin/sh
# Write a CycloneDX SBOM per image into sbom/ (git-ignored), so "are we affected
# by CVE-X in package Y?" is a lookup (`make sbom-find PKG=Y`) instead of a rescan.
# Uses local images when present (no registry pulls). Args: image refs.
set -eu
cd "$(dirname "$0")/.."
trivy=$(scripts/tool-image.sh trivy)
mkdir -p sbom
for ref in "$@"; do
  file=$(printf '%s' "${ref%@*}" | tr '/:' '__').cdx.json
  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v capitalos-trivy-cache:/root/.cache \
    -v "$PWD/sbom:/out" "$trivy" image --quiet --skip-version-check --format cyclonedx \
    --output "/out/$file" "$ref"
  echo "sbom/$file"
done
