# Issue 204: Runtime API image without apt

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/204

## Objective
- Clear CVE-2026-109518 (apt 3.0.3, HIGH, fixed 3.0.4) from the runtime API image; no python:3.12-slim with the fix exists yet.

## Architecture Decisions
- Remove apt and libapt-pkg from the runtime stage only (the API never installs packages). Build stages keep apt.

## Acceptance Criteria
- [x] `make security-scan` passes on the runtime image.
- [x] The app imports and runs in the image.

<!-- IMMUTABLE_PLAN_END -->

## Deterministic Gate Results
- `make security-scan`: exit 0. `make verify`: exit 0.
