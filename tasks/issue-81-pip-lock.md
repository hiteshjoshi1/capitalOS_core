# Issue 81: Lock every Python dependency with hashes (pip lock file)

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/81

## Objective
- Two builds of the same commit install the same Python packages, and none is a release published that day.

## Architecture Decisions
- D-17: pip-tools (`pip-compile --generate-hashes --strip-extras`), run by `make api-lock` in the API's own pinned base image, and by `make orch-lock` on the host Python (the orchestration venv's). `requirements*.in` = direct pins (+ "held back" transitive pins); `requirements*.txt` = generated lock. Image and venv install with `--require-hashes`; pip itself pinned to 26.2.2.
- `scripts/check-lock-age.py` (make targets + CI) fails on a transitive package under 14 days old.

## Acceptance Criteria
- [x] API lock: 76 packages, all hashed; dev lock 89; orchestration lock hashed.
- [x] Age check passes on all three locks; held back: bitarray, curl-cffi, platformdirs, pycparser, python-dateutil (3.0 major → 2.9), soupsieve, starlette (1.10 → 1.8), tzdata, tzlocal, websockets (api) and the langchain/langgraph transitive set (orchestration).
- [x] certifi held back first reintroduced a CRITICAL (GHSA-6q48-6c7w-9gw2); lifted to the fixing 2026.10.18, `make security-scan` passes.
- [x] `make verify` (backend 443, frontend 275), orchestration 201 passed from a `--require-hashes` venv.
- [ ] Test instance: the app runs on the held-back versions (stock prices fetch via yfinance/curl-cffi).

## How To Test
- `make api-lock` / `make orch-lock` (network); `make verify`; `make security-scan`.

<!-- IMMUTABLE_PLAN_END -->
