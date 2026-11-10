# Issue #89: MCP Toolbox 1.16.0 (CVE fixes), accepted without provenance

## Goal
Take the first Toolbox release that clears the CRITICAL/HIGH CVEs we carried on 1.14.0.

## Findings (2026-11-10)
- Upstream fix (googleapis/mcp-toolbox#4370) shipped in 1.16.0.
- Trivy fixable HIGH/CRITICAL: 1.14.0 = 13 (1 CRITICAL), 1.16.0 = 3 HIGH (zlib1g x2 from the Debian base, golang.org/x/net).
- 1.15.0 and 1.16.0 ship no provenance attestation (1.14.0 did); `make verify-image` failed. Asked upstream: googleapis/mcp-toolbox#4457.

## Change
- `tools/Dockerfile`: pin 1.16.0 by digest (replaces Dependabot #272).
- `scripts/verify-image.sh`: accept exactly that digest without provenance (WARN), D-90. Any other Toolbox digest without provenance still fails.

## Follow-up
- Keep #89 open until Google ships provenance or signatures again; then drop the exception.
