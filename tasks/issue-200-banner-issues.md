# Issue 200: Test instance banner shows the batch's issues, not its PRs

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/200

## Objective
- The owner reviews by issue: the red TEST banner lists the issues the batch closes, each linked to the issue.

## Architecture Decisions
- `banner_refs` in `scripts/test-instance.sh`: the issues each merged PR closes (`closingIssuesReferences`), in batch order, de-duplicated; a PR that closes no issue is listed as itself.
- The banner links `#N` to `<repo>/issues/N`; GitHub redirects that to the PR when N is a PR.

## Acceptance Criteria
- [x] Banner label reads `TEST test/<date> · Issues #a #b …`.
- [x] Each `#N` links to `/issues/N`.

## How To Test
- `cd web && npx vitest run src/__tests__/InstanceBanner.test.tsx`
- `make test-instance PRS="…"`: the banner lists the issues.

<!-- IMMUTABLE_PLAN_END -->

## Deterministic Gate Results
- `make verify`: exit 0.
