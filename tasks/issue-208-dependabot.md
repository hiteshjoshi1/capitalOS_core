# Issue 208: Dependabot for continuous supply chain scanning

## Objective
- Detect vulnerable dependencies automatically instead of relying on one-off audits (see issue 206).
- Keep every dependency surface current with low-noise, reviewable PRs.

## Architecture Decisions
- Repository settings (enabled via the GitHub API on 2026-10-29): **Dependabot alerts** and
  **Dependabot security updates** are on, so an advisory affecting any manifest opens a fix PR right away.
- `.github/dependabot.yml` adds weekly (Monday) version updates for: npm (`/web`), pip (`/api`),
  the API base image (`/api/Dockerfile`), compose images (`docker-compose.yml`), and GitHub Actions.
- Minor/patch updates are grouped per ecosystem; majors come as separate PRs.
- Ignored: Postgres majors (the data volume needs pg_upgrade or dump/restore) and Python minor/major
  on the base image (3.12 → 3.13 is a deliberate runtime change).
- Every Dependabot PR runs the existing `PR Validate` workflow (lint, typecheck, backend + frontend tests).

## Acceptance Criteria
- [x] Dependabot alerts and security updates enabled on the repository.
- [x] `.github/dependabot.yml` covers all five ecosystems and parses as valid YAML.

## How To Test
- GitHub → Insights → Dependency graph → Dependabot: all five update jobs are listed and have run.
- GitHub → Security → Dependabot alerts: the page loads (0 open alerts expected after issue 206).

<!-- IMMUTABLE_PLAN_END -->
