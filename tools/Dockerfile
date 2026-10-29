# Registry of images used OUTSIDE docker-compose.yml / api/Dockerfile: run by
# scripts, the Makefile and CI `run:` steps. Not meant to be built. Listing them
# as stages lets Dependabot (docker ecosystem, directory /tools) open bump PRs;
# consumers read a reference with `scripts/tool-image.sh <stage-name>`.

# capitalos-postgres MCP server (scripts/mcp-postgres.sh)
FROM us-central1-docker.pkg.dev/database-toolbox/toolbox/toolbox:1.14.0 AS mcp-toolbox

# Image vulnerability scanner (make security-scan, .github/workflows/security-scan.yml)
FROM aquasec/trivy:0.75.0 AS trivy
