# Issue 211: Pin images and actions by digest

## Objective
- Make every image and CI action reference immutable, so a re-pointed tag (upstream mistake or a
  compromised registry account) can't silently change what we run.
- Keep it zero-maintenance: Dependabot updates the digests.

## Architecture Decisions
- Every image reference is `tag@sha256:<multi-arch index digest>` (from `docker buildx imagetools
  inspect`), so arm64 (Mac) and amd64 (CI) resolve the same image:
  - `docker-compose.yml`: postgres, loki, grafana, alloy, docker-socket-proxy
  - `api/Dockerfile`: python:3.12-slim
  - `tools/Dockerfile`: MCP Toolbox, Trivy
- The pinned digests equal the images already running, so nothing actually changed at runtime.
- Dependabot (`docker`, `docker-compose`, `docker /tools` ecosystems) updates tag + digest together.
  Trade-off: `make api-rebuild --pull` no longer floats the Python base; base patches now arrive as
  weekly Dependabot digest PRs, which CI scans before merge (reproducible, reviewed, still weekly).
- GitHub Actions are pinned to full commit SHAs with a `# vX.Y.Z` comment: checkout v7.0.1,
  setup-node v7.1.0, cache v6.1.0, codeql-action/upload-sarif v4.38.3. v4.39.1 was skipped because it
  is under two weeks old. This supersedes Dependabot PR #10 (checkout/setup-node majors).
- `scripts/check-pinned-refs.sh` runs in `make lint` (so in CI). It fails on any `image:`/`FROM`
  without `@sha256:` (build-stage `FROM` lines excepted) and any `uses:` without a 40-hex SHA.
- SARIF categories drop the digest (`trivy-<image:tag>`), so a digest bump updates the same
  code-scanning analysis instead of orphaning its alerts.
- **Regression fixed (from issue 213):** `make db-backup`/`db-restore` used `docker cp` via the
  Postgres container's `/tmp`, which is now a tmpfs that `docker cp` can't read. Both now stream over
  stdout/stdin. The backup writes `*.part` and renames it only on success, so a failed dump never
  looks like a valid backup.

## Acceptance Criteria
- [x] No unpinned `image:`/`FROM`/`uses:`; `scripts/check-pinned-refs.sh` passes and fails on a
      deliberately unpinned compose image and action.
- [x] Stack recreated on pinned refs: API healthy, Loki ready, MCP over stdio OK; lint, typecheck,
      `make test-backend` (439) pass.
- [x] `make db-backup` works again; the streamed restore into a scratch DB returned identical row counts.
- [ ] One Dependabot digest-bump PR observed and merged.

## How To Test
- `docker compose --profile observability config --images` → every entry has `@sha256:`.
- `make up && make observability-smoke`.

<!-- IMMUTABLE_PLAN_END -->
