# Issue 73: Full-stack Playwright smoke and screenshot diffs for every PR

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/73

## Objective
- Every PR (Dependabot's too) opens every page of the real stack on demo data and fails on breakage.
- A visual change shows as a before/after diff instead of reaching Hitesh unseen.

## Architecture Decisions
- D-91: live smoke on a throwaway stack (production web container) + screenshot diffs on the recorded fixture with a frozen clock, both in the pinned Playwright image.
- `scripts/e2e-smoke.sh check|update|record|drop`; `make e2e-smoke`, `e2e-smoke-update`, `e2e-smoke-record`.
- The routes, fixture helpers and layout measuring are shared with `mobile-no-overflow.spec.ts` (`tests/e2e/helpers/pages.ts`).

## Acceptance Criteria
- [x] `make e2e-smoke` starts the stack, seeds demo, opens every page at 375/1440, fails on page/console errors, API >= 400, "Couldn't load", endless loading, overflow.
- [x] Screenshot baselines committed; a visual change fails with expected/actual/diff images.
- [x] `routes.spec.ts`: every navigation target is in the smoke routes.
- [x] CI job `smoke` runs it on every PR and uploads the report.
- [ ] Item 3 (the same smoke on the test instance's real-data copy): left out, see D-91.

## How To Test
- `make e2e-smoke` (about 3 minutes on a Mac; first run builds the images).
- Change a page's CSS, rerun: the screens project fails with a diff in `web/test-results/smoke`.
- `make e2e-smoke-update` rewrites the baselines; `make e2e-smoke-record` re-records the fixture.
