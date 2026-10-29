# Issue 210: Continuous image scanning, fresh-base rebuilds, hardened API image

## Objective
- Catch new CVEs in images automatically, including images that haven't changed (items 1 + 2 of the
  image-security list from issue 206's follow-ups).
- Shrink and de-privilege what actually runs: the API container (item 4).

## Architecture Decisions
- **Scanning = Trivy, run as its Docker image (`aquasec/trivy:0.75.0`)**, not a third-party GitHub
  Action, so CI uses no extra action code. 0.75.0 is the newest release at least two weeks old.
- **`.github/workflows/security-scan.yml`** runs on PRs, every Monday 06:00 UTC, and on demand:
  - `api-image` builds the runtime image with `--pull` and **fails** on fixable HIGH/CRITICAL.
  - `compose-images` scans the third-party images from `docker-compose.yml`, read from
    `docker compose config` so the list never drifts. These are **report only**, since we can't patch them.
  - Results are uploaded as SARIF to the Security tab, which is free for public repos.
- **`make security-scan`** is the local twin, with the same flags and the same pass/fail rule.
- **`make api-rebuild` builds with `--pull`**, so every rebuild picks up base-image security patches.
- **Dockerfile: shared base + two targets.** `runtime` is the default and what `make up` runs: uid
  10001, pip uninstalled, no pytest/ruff/mypy, no `tests/`. `dev` adds the tooling for the new
  compose service `api-dev` (profile `tools`), which `make lint/typecheck/test-backend` now use
  (`run --rm --build`, so the image is never stale).
- Dev tools moved from `requirements.txt` to `requirements-dev.txt` (`-r requirements.txt` + tools).
- `./api/app` is now mounted read-only. `--reload` still works.
- `CAPITALOS_UID`/`CAPITALOS_GID` (in `.env`) let Linux hosts match `./data` ownership.
- `tests/conftest.py` now forces `AUTH_ALLOW_SIGNUP=1`. A deployment `.env` with signup disabled
  used to leak into the test container and fail `test_auth_signup_login_me_logout` locally
  (pre-existing since issue 205; CI uses an empty `.env`).

## Acceptance Criteria
- [x] `make security-scan` passes on the runtime image and exits 1 on an image with fixable HIGH/CRITICAL.
- [x] Runtime container: `id` → uid 10001, no pip, no pytest; `/app/data` writable; `/app/app` read-only.
- [x] `make lint`, `make typecheck`, `make test-backend` (439 passed), `make contract-backend` pass via `api-dev`.
- [x] actionlint passes on both workflows.
- [ ] Security Scan workflow green on this PR; SARIF results visible under Security → Code scanning.

## How To Test
- `make api-rebuild && make test-backend && make security-scan`.
- `docker exec capitalos-oss-test-api id` → `uid=10001(app)`.

<!-- IMMUTABLE_PLAN_END -->

## Follow-ups (planned)
- Item 3, digest pinning: `tasks/issue-211-pin-images-by-digest.md`
- Item 6, MCP image: `tasks/issue-212-mcp-image-and-readonly-role.md`
- Item 5, runtime hardening: `tasks/issue-213-container-runtime-hardening.md`
- Item 7, SBOM/provenance/prune: `tasks/issue-214-sbom-provenance-and-prune.md`
