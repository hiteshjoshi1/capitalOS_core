# Registry of images used OUTSIDE docker-compose.yml / api/Dockerfile: run by
# scripts, the Makefile and CI `run:` steps. Not meant to be built. Listing them
# as stages lets Dependabot (docker ecosystem, directory /tools) open bump PRs;
# consumers read a reference with `scripts/tool-image.sh <stage-name>`.

# capitalos-postgres MCP server (scripts/mcp-postgres.sh)
FROM us-central1-docker.pkg.dev/database-toolbox/toolbox/toolbox:1.14.0@sha256:dab91e25cbe7145d261df2978881c4e23e02238b42da3c72eea2df0a95aea797 AS mcp-toolbox

# Image vulnerability scanner (make security-scan, .github/workflows/security-scan.yml)
FROM aquasec/trivy:0.76.1@sha256:790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c AS trivy

# Signature verification (scripts/verify-image.sh)
FROM ghcr.io/sigstore/cosign/cosign:v3.1.4@sha256:0f06154836d2de34f887a5c273506d52ca43edaa1d9e53e6510fa78a48f69c2d AS cosign
