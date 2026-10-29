#!/bin/sh
# Print the image reference for a stage in tools/Dockerfile, e.g.
#   scripts/tool-image.sh trivy  ->  aquasec/trivy:0.76.0
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
ref=$(sed -n "s/^FROM \([^ ]*\) AS $1\$/\1/p" "$root/tools/Dockerfile")
[ -n "$ref" ] || { echo "tool-image: no stage '$1' in tools/Dockerfile" >&2; exit 1; }
echo "$ref"
