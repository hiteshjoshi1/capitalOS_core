# Issue 134: Reusable Company Research Corpus

## Objective
- Make company thesis mode reusable instead of one-shot.
- Turn fetched company/web evidence into a reusable company research corpus that improves future answers.
- Support the minimum data buckets needed for v1:
  - author corpus
  - company research corpus
  - saved research notes
  - topics / companies / concepts index

## Program Position
- Depends on issue 132 and issue 133.
- This issue exists only because it directly improves answer quality and reuse for company thesis mode.
- If implementation drifts into monitoring/analytics scaffolding, it should be deferred.

## Central Product Idea
- Live company research should not vanish after one thesis-pressure-test run.
- The best fetched sources, extracted facts, and normalized evidence should be reusable later for the same company or topic.
- This is still part of answer quality, not yet part of monitoring dashboards or analytics.

## Scope
- Persist fetched company research sources
- Normalize/store extracted company evidence
- Link saved research notes to company evidence
- Support retrieval over:
  - thinker corpus
  - company evidence corpus
  - saved research notes
- Improve later company thesis answers by reusing prior fetched evidence

## Out Of Scope
- Portfolio/company monitoring dashboards
- Automated watchlists / alerts
- Outcome review / calibration
- Broad business intelligence platform features

## Acceptance Criteria
- [ ] Fetched company/web sources from thesis mode can be persisted and reused.
- [ ] Extracted company facts/evidence can be retrieved later by company/topic.
- [ ] Retrieval can combine:
  - thinker corpus
  - company research corpus
  - saved research notes
- [ ] `AI Sage` can clearly distinguish these evidence types in responses.
- [ ] Add tests for:
  - saving fetched company sources
  - retrieving company evidence later
  - mixed retrieval across thinker/company/saved-research layers

## Suggested Implementation Shape
- New persisted objects, names subject to judgment:
  - `company_sources`
  - `company_documents`
  - `company_chunks`
  - or reuse existing RAG tables with robust corpus typing and metadata
- Keep the design retrieval-first and reuse-first.

## Verification Plan
- `make api-rebuild`
- `make test-backend`
- Run a thesis-mode company query that fetches live sources
- Save/reuse those sources
- `curl` a later company query and confirm prior fetched evidence is available

## Human Notes
- This is still a v1 value issue because it compounds company research quality across repeated use.
- Do not let this turn into a broad monitoring system.
- If a feature here does not improve later company answers or retrieval reuse, defer it.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `<stage>`
- Workflow Status: `<running|blocked|shipped|failed>`
- Provider/Model: `<provider>/<model>`
- Last Updated: `<timestamp>`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `<pass|fail|skip>` — `<notes/log path>`
- `typecheck`: `<pass|fail|skip>` — `<notes/log path>`
- `tests`: `<pass|fail|skip>` — `<notes/log path>`
- `e2e`: `<pass|fail|skip>` — `<notes/log path>`
- `api-smoke`: `<pass|fail|skip>` — `<notes/log path>`
- `policy-checks`: `<pass|fail>` — `<notes/log path>`

## Extra Files Changed (Codex Mutable)
- `<path>` — reason: `<why this file was required>`

## Permanently Failed / Gave Up (Codex Mutable)
- Stop reason: `<concrete reason>`
- Attempted mitigations:
  - `<mitigation 1>`
  - `<mitigation 2>`
- Suggested human action: `<next action>`

## Human Action Summary (Codex Mutable)
- Next expected action: `<command or decision>`
- Open questions:
  - `<question>`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._
