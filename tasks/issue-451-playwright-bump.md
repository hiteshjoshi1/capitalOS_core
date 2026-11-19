# Issue 451: Bump @playwright/test only together with the pinned Playwright image (R7 from #431)

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/451

## Objective
- A Dependabot npm bump of `@playwright/test` alone fails CI (`scripts/e2e-smoke.sh` refuses a version
  different from the Playwright image in `tools/Dockerfile`). Stop Dependabot opening that lone PR.

## Architecture Decisions
- Ignore `@playwright/test` in the `/web` npm block; the `/tools` docker block keeps bumping the image, and the
  npm bump is added to that PR by hand (comments in `dependabot.yml` and `tools/Dockerfile` say how).
- Rejected: Dependabot `multi-ecosystem-groups` (one PR across npm + docker). It needs a separate npm entry
  for the same directory with `patterns`, which overlaps the existing `/web` block; not worth the config risk
  for a bump that comes every few weeks.

## Acceptance Criteria
- [x] `@playwright/test` is ignored by the npm block.
- [x] The image block and `tools/Dockerfile` say to bump `@playwright/test` on the image PR.

## How To Test
- `python3 -c 'import yaml;yaml.safe_load(open(".github/dependabot.yml"))'` parses; GitHub validates the file on push
  (Insights → Dependency graph → Dependabot shows no config error).

<!-- IMMUTABLE_PLAN_END -->
