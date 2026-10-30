# Issue 101: Test instance banner: link each PR in the batch

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/101

## Objective
- A tester on the test instance (desktop or phone) opens any PR in the batch straight from the TEST banner.

## Architecture Decisions
- `make test-instance` passes the repo URL (`gh repo view`) as `INSTANCE_REPO_URL` → `VITE_INSTANCE_REPO_URL`; the banner turns each `#N` in its label into a link to `<repo>/pull/N`.
- Only an `https://` URL is used; otherwise (DEV worktrees, the real app) the banner is unchanged.
- Links show `#N`, not the full URL, so the banner stays one line on a phone.

## Acceptance Criteria
- [x] TEST banner: each `#N` links to its PR, opening in a new tab.
- [x] No repo URL: plain text, as before.

## How To Test
- `cd web && npx vitest run src/__tests__/InstanceBanner.test.tsx`.
- On the test instance (:5174), tap a PR number in the red banner.

<!-- IMMUTABLE_PLAN_END -->
