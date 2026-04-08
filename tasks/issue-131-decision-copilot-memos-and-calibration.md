# Issue 131: AI Sage Interaction Shell And Runtime Query Orchestration

## Objective
- Build the first real interactive `AI Sage` experience on top of issue 130 retrieval and author wisdom.
- Add the runtime orchestration layer that turns backend retrieval/profile endpoints into a usable product surface.
- Create the session flow that later issues can extend with reasoning, questioning, memos, and reflection.

## Program Position
- Depends on issue 130.
- Serves as the UX/runtime bridge for:
  - issue 132 multi-lens reasoning
  - issue 133 guided investment intake and decision memos
  - issue 135 reflection and personal improvement
- This issue should make `AI Sage` feel like a coherent product surface before the heavier reasoning and memo workflows land.

## Architecture Decisions
- This issue assumes issue 130 already provides:
  - retrieval
  - citations
  - author wisdom profiles
  - author selection
- The main job here is product orchestration, not deeper reasoning logic.
- `AI Sage` should support multiple query modes in one consistent shell, for example:
  - retrieve
  - ask
  - company context
  - author profile view
- Add a runtime query orchestration layer in the backend that routes user requests to the correct retrieval/profile path and normalizes responses for the UI.
- The frontend should preserve context between interactions in a session, but this issue should stop short of full memo persistence and outcome review.
- The UI should show what the system is doing:
  - selected authors
  - selected mode
  - retrieved evidence
  - citations
  - author wisdom cards
- This issue should not yet implement full multi-lens synthesis/critic reasoning. That belongs to issue 132.

## Scope
- `AI Sage` page / route / shell
- Session-oriented query UX
- Backend runtime query orchestration for `AI Sage`
- Unified response model for:
  - retrieval results
  - author wisdom profiles
  - company-context preparation
- Basic product polish for loading states, empty states, errors, and citation display

## Out Of Scope
- Full multi-lens reasoning, synthesis, and critic
- Guided clarification question generation
- Decision memo persistence
- Feedback capture
- Outcome review
- Calibration analytics
- Company-intelligence corpus expansion beyond what already exists

## Acceptance Criteria
- [ ] Add an `Intelligence > AI Sage` product surface that can:
  - accept a query
  - choose a mode
  - optionally choose/filter authors
  - display selected authors
  - display citations and evidence cards
  - display author wisdom profile cards
- [ ] Add a backend orchestration endpoint or equivalent service that normalizes UI query execution for `AI Sage`.
- [ ] `AI Sage` can handle at least these flows:
  - retrieval query
  - author-aware ask query
  - company-context preparation query
  - direct author profile inspection
- [ ] UI has usable:
  - loading states
  - empty states
  - user-friendly error states
  - citation rendering
- [ ] Responses remain source-grounded and curl-testable.
- [ ] Add frontend tests for the `AI Sage` surface and backend tests for orchestration endpoints/services.

## Suggested Implementation Shape
- Add a route/page in the frontend for `AI Sage`.
- Add frontend state for:
  - current mode
  - current query
  - current selected authors
  - latest result payload
  - recent session history if lightweight enough
- Add a backend orchestration endpoint, likely close to:
  - `POST /ai-sage/query`
  - or a normalized extension of existing `/rag/query`
- Keep response shapes stable enough that later issues can add reasoning/memo fields without breaking the shell.

## Verification Plan
- `make api-rebuild`
- `make web-rebuild`
- `make test-backend`
- `make test-frontend`
- `curl -X POST http://localhost:8000/ai-sage/query -H "Content-Type: application/json" -d '{"mode":"retrieve","query":"capital allocation and moat"}'`
- Verify `AI Sage` UI can execute all supported modes and render citations and author wisdom cleanly.

## Human Notes
- This is the first issue where the product should begin to feel like a coherent `AI Sage`, rather than a set of backend endpoints.
- The point is product integration and usability, not yet full reasoning depth.
- If scope becomes too large, prioritize:
  - stable shell
  - mode routing
  - citation rendering
  - author wisdom display

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
