# Issue 209: Fix orchestration dependency advisories found by Dependabot

## Objective
- Close the 3 Dependabot alerts raised as soon as issue 208 was enabled. All three were in
  `orchestration/requirements.txt`, a manifest the issue 206 audit missed (it covered `api/` and `web/` only).

## Architecture Decisions
- `langgraph-checkpoint-sqlite` 3.0.3 → 3.1.2: fixes two namespace-isolation advisories in the SQLite store.
- `pytest` 9.0.2 → 9.2.0: fixes the tmpdir handling advisory (same version as `api/`).
- `make orch-bootstrap` upgrades pip in `.venv-orch` before installing (pip < 26.2 has advisories).
- `.github/dependabot.yml` now also watches `/orchestration` (pip, weekly, minor/patch grouped).

## Acceptance Criteria
- [x] `pip-audit` on the resolved orchestration requirements reports no app-dependency advisories.
- [x] `make orch-bootstrap && make orch-test`: 201 passed.
- [ ] After merge, Dependabot alerts #1–#3 auto-close.

## How To Test
- `make orch-bootstrap && make orch-test`.

<!-- IMMUTABLE_PLAN_END -->
