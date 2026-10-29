# Issue 80: Flaky frontend tests: assertions that don't wait for mocked data

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/80

## Objective
- `make test-instance` / CI never fail on a test that only lost a race with its own mocks.

## Architecture Decisions
- Fix the tests, not the timeouts: wait (`findBy…`) for the first element that depends on mocked data, instead of a heading that renders before the data.
- Found by an experiment, not by eye: a throwaway copy of every test file that mocks `../lib/api`, with every mocked call resolving 50 / 250 / 500 ms late.

## Acceptance Criteria
- [x] At 50 ms delay: before the fix 6 tests failed every run; after, all pass.
- [x] At 250 ms delay: all 122 tests in the 18 API-mocking files pass (two more found and fixed at this level: Dividends, Platforms).
- [x] Normal suite: 275 passed.
- At 500 ms per call, `Platforms › creates a platform and shows success` exceeds the 1 s `findBy` default because several delayed calls chain; that's compounding delay, not this race.

## How To Test
- `cd web && npx vitest run`.

<!-- IMMUTABLE_PLAN_END -->
