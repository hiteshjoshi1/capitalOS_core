# Issue 214: SBOMs, provenance checks, and image pruning (planned)

## Objective
- When a new CVE is announced, answer "are we affected?" with a lookup instead of a rescan.
- Check that image upgrades come from the real publisher before adopting them.
- Stop old images from piling up locally (they keep stale, vulnerable layers around).

## Architecture Decisions
- **SBOM:** `make sbom` writes CycloneDX SBOMs with Trivy (`--format cyclonedx`) for the runtime API
  image and each compose image into `sbom/` (git-ignored). The weekly CI run uploads the same files
  as a workflow artifact (free for public repos; 90-day retention). Optional: also submit them to the
  dependency graph.
- **Provenance/signatures (manual step in the upgrade checklist, scripted as `make verify-image IMAGE=`):**
  - Docker Official Images (postgres, python): check the attestations with
    `docker buildx imagetools inspect <ref> --format '{{json .Provenance}}'`.
  - Images whose publisher signs with cosign: `cosign verify` using the publisher's documented
    identity (run cosign as its container image, so nothing to install).
  - Unsigned images: rely on digest pinning (issue 211) plus the Trivy gate.
- **Prune:** `make docker-prune` removes dangling layers and `capitalos*` images not used by any
  container. It never runs `docker system prune -a`, because other projects (investOS) share the daemon.
  Mention it in the monthly maintenance notes.
- Free: Trivy, cosign, buildx, GitHub artifacts.

## Acceptance Criteria
- [ ] `make sbom` produces one CycloneDX file per image; weekly CI artifact present.
- [ ] `make verify-image IMAGE=postgres:16.15` prints the provenance and fails on mismatch.
- [ ] `make docker-prune` leaves running and other-project images untouched.

## How To Test
- `make sbom && ls sbom/`; `make verify-image IMAGE=python:3.12-slim`; `make docker-prune` then `docker ps`.

<!-- IMMUTABLE_PLAN_END -->
