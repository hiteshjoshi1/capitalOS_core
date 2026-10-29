# Issue 49: Triage the Dependabot PR backlog

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/49

## Objective
- Clear the Dependabot backlog in reviewable batches, each through the test instance.
- Keep the release-age rule (D-1) without holding releases back by hand.

## Architecture Decisions
- Batches by how much testing they need from Hitesh, majors one at a time (or a tightly coupled group).
- D-14: Dependabot `cooldown` of 14 days; `eth-*` grouped; SQLAlchemy series reviewed on its own.

## Acceptance Criteria
- [x] Batch 1: npm + pip minor/patch (#61, replaces #19 and most of #13) and #29. Merged via #62, deployed 584b2e3.
- [ ] Batch 2: pandas 3.0.6 (in place of #18's 3.1.0), pytest-cov 7.1.0 (#30), Dependabot config (D-14). Closes #63; #8 and #9 already landed with #29.
- [ ] Batch 3: recharts 3 (#24).
- [ ] Batch 4: argon2-cffi 25 (#16) and the eth group (#14, #15, eth-account 0.14, eth-keys 0.8).
- [ ] Batch 5: dev tooling majors (TypeScript 7, eslint 10 + config packages, mypy 2, jsdom 30, plugin-react 6, @types/node 26, @types/bs58 5) with #60.
- [ ] After their two weeks: Trivy 0.76.1 (#36), MCP Toolbox 1.15.0 (#35), codeql-action (#39).

## How To Test
- Batch 2: `make verify`, `make orch-test`, `make security-scan`; on the test instance import an XLS statement (UOB account / UOB card / DBS Vickers / Sharekhan): pandas reads only those (and the format detector), CSV imports don't use it.

<!-- IMMUTABLE_PLAN_END -->

## Execution Journal
- Batch 1 shipped 2026-10-29 (#62).
- Batch 2 in progress on `feature/issue-49-batch-2`.
