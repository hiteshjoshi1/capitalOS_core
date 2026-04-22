# Issue 147: RAG ingestion admin UI and background jobs

## Objective
- Replace repetitive curl/token-based RAG source registration and ingestion with a small authenticated admin UI.
- Let an operator add or select an author, register multiple URLs for that author, and kick off ingestion asynchronously.
- Make ingestion operationally usable by surfacing per-source status, job progress, failures, and retry actions in the UI.

## Architecture Decisions
- Decision 1: Build this as an admin/ops workflow on top of the existing RAG ingestion primitives, adding only the backend endpoints needed for UI ergonomics and background orchestration.
- Decision 1: Build this as a user-facing Intelligence workflow on top of the existing RAG ingestion primitives, adding only the backend endpoints needed for UI ergonomics and background orchestration.
- Decision 2: Support author creation from the UI, but keep the required author form minimal: `id`/slug, display `name`, and `enabled`. Put optional author metadata in an advanced section: `domains`, `expertise_tags`, `overall_weight`, `role_type`. Do not require author-card metadata (`focus_areas`, `avoid_patterns`, `biases`, `prompt_adapter`) on the initial UI form.
- Decision 3: URL ingestion must run asynchronously in the background, one URL at a time per submitted author batch, with status persisted and queryable via ingestion job/source status endpoints.
- Decision 4: The UI must expose registered sources for an author and let the operator retry failed sources without resorting to curl or direct DB inspection.
- Decision 5: The UI should be framed in end-user language as `Author Ingestion`, not `RAG Ingestion`, and should live under the Intelligence section rather than a hidden admin-only area.

## Acceptance Criteria
- [ ] A user can open an authenticated Intelligence UI and see an author-ingestion workspace for corpus operations.
- [ ] A user can navigate to the feature from the Intelligence section of the app.
- [ ] The route name, page title, and navigation label use end-user language such as `Author Ingestion`, not backend-facing `RAG Ingestion`.
- [ ] A user can select an existing author from the DB-backed author list.
- [ ] A user can create a new author from the UI with required fields `id`/slug and `name`, plus `enabled`, without editing config files manually.
- [ ] The UI explicitly distinguishes required author fields from optional advanced metadata fields.
- [ ] The advanced author section, if expanded, supports `domains`, `expertise_tags`, `overall_weight`, and `role_type`.
- [ ] The first version of the UI does not require author-card metadata fields such as `focus_areas`, `avoid_patterns`, `biases`, or `prompt_adapter`.
- [ ] A user can add one or more URLs for the selected author in a single submission flow.
- [ ] The URL-entry UI supports a plus-button or equivalent add-row interaction so operators can add multiple URLs before submitting.
- [ ] Submitted URLs are registered as sources for the author and deduplicated or rejected cleanly if already present.
- [ ] Submitting URLs starts ingestion asynchronously rather than blocking the browser request until completion.
- [ ] Background ingestion processes one URL at a time for the submitted batch, and the behavior is explicit in backend logs and job state.
- [ ] The UI shows the registered sources for the selected author, including source URL, source type when known, and current source status.
- [ ] The UI shows ingestion job status in a clearly visible status area or table, including at minimum: queued/running/succeeded/failed, source linkage, started time, finished time, and failure reason where applicable.
- [ ] A failed source can be retried from the UI without re-entering the URL manually.
- [ ] The UI makes it obvious whether a source is only registered, actively ingesting, successfully ingested, or failed.
- [ ] Backend APIs added for this feature remain OpenAPI-compatible and are verifiable via curl.
- [ ] Frontend state stays aligned with backend status after refresh or polling; a user should not lose visibility of in-flight background jobs by refreshing the page.
- [ ] Tests cover author creation/selection flows, multi-URL registration, background ingestion kickoff, job status retrieval, and retry behavior.
- [ ] The feature is verifiable with Makefile commands, including backend tests, frontend tests, rebuild commands, and a curl-verifiable happy path.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `not_started`
- Workflow Status: `running`
- Provider/Model: `openai/gpt-5`
- Last Updated: `2026-04-21`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `<pass|fail|skip>` — `<notes/log path>`
- `typecheck`: `<pass|fail|skip>` — `<notes/log path>`
- `tests`: `<pass|fail|skip>` — `<notes/log path>`
- `e2e`: `<pass|fail|skip>` — `<notes/log path>`
- `api-smoke`: `<pass|fail|skip>` — `<notes/log path>`
- `policy-checks`: `<pass|fail>` — `<notes/log path>`

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- `<path>` — reason: `<why this file was required>`

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `<concrete reason>`
- Attempted mitigations:
  - `<mitigation 1>`
  - `<mitigation 2>`
- Suggested human action: `<next action>`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: `<command or decision>`
- Open questions:
  - `<question>`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `prepare`
**Workflow Status**: `running`

## Workflow Snapshot
- latest_outcome: No workflow outcome recorded yet.
- next_action: Workflow execution is in progress.
- pipeline_version: `v3`
- retry_gate_pending: `no`

## Active Requirements
- No active requirements recorded yet.

## Prepare
Checked out `feature/issue-147-rag-ingestion-admin-ui-and-background-jobs` from `main` and ensured task file exists.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._
<!-- MACHINE_RENDERED_END -->
