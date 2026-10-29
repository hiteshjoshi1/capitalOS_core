# Issue 211: Pin images and actions by digest (planned)

## Objective
- Make every image and CI action reference immutable, so a re-pointed tag (upstream mistake or a
  compromised registry account) can't silently change what we run.
- Keep it zero-maintenance: Dependabot updates the digests.

## Architecture Decisions
- `docker-compose.yml` and `api/Dockerfile`: `image: postgres:16.15@sha256:<index digest>`. Use the
  multi-arch **index** digest (`docker buildx imagetools inspect <ref>`), so arm64 (Mac) and amd64 (CI)
  both resolve. The Dependabot `docker` and `docker-compose` ecosystems update tag+digest together.
- **Images Dependabot can't see** (in `run:` steps, the Makefile and `scripts/mcp-postgres.sh`):
  collect them in `tools/images.Dockerfile`, one `FROM <image>:<tag>@sha256:… AS <name>` line each
  (Trivy, the MCP image, actionlint). Add a Dependabot `docker` entry for `/tools`. The Makefile,
  workflow and script read the reference from that file with a one-line `sed`, so there's one source of truth.
- GitHub Actions: pin `uses:` to full commit SHAs with a `# vX.Y.Z` comment. Dependabot
  `github-actions` updates SHAs and comments.
- Free: all of this is Dependabot plus file edits.

## Acceptance Criteria
- [ ] No `image:`/`FROM`/`uses:` reference without a digest or SHA (a CI grep check enforces this).
- [ ] `make up`, `make observability-up`, `make security-scan`, CI all green with pinned refs.
- [ ] One Dependabot digest-bump PR observed and merged.

## How To Test
- `docker compose --profile observability config --images` → every entry has `@sha256:`.
- `make up && make observability-smoke`.

<!-- IMMUTABLE_PLAN_END -->
