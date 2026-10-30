# Issue 90: CRITICAL/HIGH fixes skip the 14-day wait; weekly scan flags available fixes

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/90

## Objective
- A release that fixes a HIGH/CRITICAL affecting us goes in at once, and we notice it exists.

## Architecture Decisions
- D-18 widens D-1's exception from "exploited issue" to any CRITICAL/HIGH a release clears.
- `scripts/image-fixes.py` (stdlib; Trivy as its pinned image): per pinned image, the newest tag in the same major line (or, for a floating tag like python:3.12-slim, where it points now), both scanned; reports cleared/added findings, exits 3 when something would be cleared. `make image-fixes`; CI job `image-fixes` (weekly/on demand, not PRs) writes the step summary and opens or comments on one issue.

## Acceptance Criteria
- [x] First run (2026-10-30): cosign v3.1.3 → v3.1.4 clears 20 HIGH; trivy 0.76.0 → 0.76.1 clears 2 HIGH (incl. CVE-2026-111943); toolbox 1.15.0 clears nothing; others have no newer release in line.
- [x] check-pinned-refs passes; workflow YAML valid.
- [ ] cosign 3.1.4 and trivy 0.76.1 taken in the dependency batch (#49) under D-18.

## How To Test
- `make image-fixes`

<!-- IMMUTABLE_PLAN_END -->
