# Issue 94: Lock age check exempts held-back pins

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/94

## Objective
- A Dependabot (or hand) bump of a held-back transitive package can't bring in a release under 14 days old unnoticed.

## Architecture Decisions
- `check-lock-age.py` exempts only pins above the `# Held back` marker (reviewed direct pins). Held-back pins are checked like any transitive package.
- A held-back pin can be exempted only explicitly: `D-1 exception` on its line or the comment line right above (today: certifi 2026.10.18, GHSA-6q48-6c7w-9gw2, in api and orchestration).

## Acceptance Criteria
- [x] Current locks pass (api, api-dev, orchestration).
- [x] Replay of Dependabot #87 (uuid-utils 0.19.0, 3 days old): fails with the new check, passed with the old one.
- [ ] Close #87; it can return once 0.19.0 is 14 days old.

## How To Test
- `scripts/check-lock-age.py orchestration/requirements.txt orchestration/requirements.in`

<!-- IMMUTABLE_PLAN_END -->
