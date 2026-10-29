# Issue 214: SBOMs, provenance checks, and image pruning

## Objective
- When a new CVE is announced, answer "are we affected?" with a lookup instead of a rescan.
- Check that image upgrades come from the real publisher before adopting them.
- Stop old images piling up locally (they keep stale, vulnerable layers around).

## Architecture Decisions
- **SBOMs:** `make sbom` writes one CycloneDX file per image into `sbom/` (git-ignored) with Trivy,
  using **local** images, so there are no registry pulls. It covers the runtime API image plus every
  pinned compose and tool image. `make sbom-find PKG=<name>` lists every image, package and version
  that matches.
- **Provenance:** `scripts/verify-image.sh <ref>` (`make verify-image IMAGE=…`, `make verify-images`)
  applies the strongest evidence each publisher actually ships (surveyed 2026-10-29):

  | Policy | Images | Check |
  |---|---|---|
  | signature | `aquasec/trivy` | cosign keyless, identity `github.com/aquasecurity/trivy` GitHub Actions |
  | signature | `sigstore/cosign` | cosign keyless, identity `keyless@projectsigstore.iam.gserviceaccount.com` |
  | provenance | `postgres`, `python` | SLSA provenance naming `github.com/docker-library/<repo>` |
  | attested | alloy, docker-socket-proxy, MCP Toolbox | SLSA provenance attestation present |
  | pin-only | loki, grafana | publisher ships neither; digest pin + Trivy gate |

  Unpinned refs fail, and **a repo with no policy fails**, so a new image forces a trust decision.
  Cosign runs as its digest-pinned image from `tools/Dockerfile`.
- **CI:** the weekly/on-demand `sbom-and-provenance` job in `security-scan.yml` runs `make verify-images`
  and `make sbom` and uploads the SBOMs as a 90-day artifact (free for public repos). It doesn't run
  on PRs, to stay under Docker Hub's anonymous rate limit (100 manifest requests/hour/IP), which this
  issue's own testing hit. For a Dependabot bump, run `make verify-image IMAGE=<new ref>` before merging.
- **Prune:** `make docker-prune` lists unused images: old versions of repos we pin, stale
  `capitalos*` builds, and this project's dangling build layers. `APPLY=1` removes them. It never
  touches an image any container uses (e.g. investOS's `postgres:17`), never the current pins, and
  never runs `docker system prune`.

## Acceptance Criteria
- [x] `make sbom` produces 10 CycloneDX files; `make sbom-find PKG=libssl` lists 8 images with versions.
- [x] `verify-image`: cosign (signature) and Toolbox (provenance) → OK; unpinned ref → FAIL; unknown
      repo → FAIL; cosign checked against the wrong signer identity → rejected.
- [x] `make verify-images` all OK on a dispatched CI run (40807272268): 7 OK (2 signatures, 2
      docker-library provenance, 3 attestations) + 2 INFO (loki, grafana); SBOM artifact uploaded.
- [x] `make docker-prune` dry run lists only unused images (sandbox build, `postgres:16-alpine`,
      old trivy) and excludes in-use and pinned images.
- [x] actionlint and `check-pinned-refs.sh` pass.

## How To Test
- `make sbom && make sbom-find PKG=openssl`
- `make verify-images`
- `make docker-prune` (dry run), then `make docker-prune APPLY=1`

<!-- IMMUTABLE_PLAN_END -->
