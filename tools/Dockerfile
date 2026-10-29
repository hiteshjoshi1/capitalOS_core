# Registry of images used OUTSIDE docker-compose.yml / api/Dockerfile: run by
# scripts, the Makefile and CI `run:` steps. Not meant to be built. Listing them
# as stages lets Dependabot (docker ecosystem, directory /tools) open bump PRs;
# consumers read a reference with `scripts/tool-image.sh <stage-name>`.

# capitalos-postgres MCP server (scripts/mcp-postgres.sh)
FROM us-central1-docker.pkg.dev/database-toolbox/toolbox/toolbox:1.14.0@sha256:dab91e25cbe7145d261df2978881c4e23e02238b42da3c72eea2df0a95aea797 AS mcp-toolbox

# Image vulnerability scanner (make security-scan, .github/workflows/security-scan.yml)
FROM aquasec/trivy:0.76.0@sha256:2416d1f74045b57274df1a340eee6b510cacd73c66a6ccb8da092b117eb7d222 AS trivy

# Signature verification (scripts/verify-image.sh)
FROM ghcr.io/sigstore/cosign/cosign:v3.1.3@sha256:9e5c2f2edc34351160407ca3416c61855bdf9403c3c5936e0f0be7fc261611b8 AS cosign
