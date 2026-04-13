# Issue 137: AI Sage Intent Routing and Query Understanding

## Objective
- Improve retrieval and answer quality by understanding the user's query before retrieval.
- Prevent obvious semantic-intent failures such as Buffett-only questions expanding into multi-author answers.
- Use a cheap, fast model for routing/planning rather than the main synthesis model.

## Why This Issue Exists
- Current AI Sage concept mode does one broad semantic retrieval pass over the raw query.
- It does not reliably detect:
  - explicit author constraints
  - source constraints like `letters`
  - date constraints like `2020 to 2025`
  - answer-shape intent like `aphorisms`, `life advice`, `investment advice`
- As a result, retrieval quality is weak on focused corpus questions, and author selection can drift into unrelated authors.

## Central Product Idea
- Before retrieval, AI Sage should run a lightweight intent-routing step that converts the user query into a structured retrieval plan.
- This step does not need a frontier model.
- It should be cheap, fast, and configurable independently from the main answer-generation model.

## In Scope
- Add a pre-retrieval intent-routing step for AI Sage.
- Extract structured constraints from the user query:
  - explicit author mentions
  - source/doc-type constraints
  - date/time constraints
  - output-shape intent
  - whether this is single-author, multi-author comparison, or open-ended
- Support query decomposition when one natural-language query contains multiple focused asks.
- Use the structured plan to drive author selection and retrieval instead of broad topic-only matching.
- Make the lightweight routing model configurable independently from the main synthesis model.

## Out Of Scope
- Research memory / save-retrieve flows
- Live external company research
- Critic/memo/calibration layers beyond what is necessary to improve first-pass retrieval quality
- UI redesign beyond minimal evidence that the behavior improved

## Acceptance Criteria
- [ ] A Buffett-only question defaults to Buffett-only retrieval unless the user explicitly asks for comparison.
- [ ] A query with date constraints can narrow retrieval to the requested period when metadata exists.
- [ ] A query with source constraints like `letters` can prefer or restrict to those source types when metadata exists.
- [ ] Multi-part questions can be decomposed into a small structured retrieval plan instead of one blunt vector search.
- [ ] The routing/planning model is configurable independently from `INFERENCE_LLM_MODEL`.
- [ ] Tests cover author-intent extraction, date/source constraint extraction, and single-author enforcement.

## Product Guardrails
- Do not use the lightweight routing model for final answer prose.
- Do not introduce a heavyweight model call just to classify simple queries.
- Do not override explicit user constraints in the name of “helpfulness.”
- If the parser is uncertain, preserve the user’s explicit wording rather than broadening scope.

## Suggested Areas To Inspect
- `api/app/routers/ai_sage.py`
- `api/app/rag/concept_mode.py`
- `api/app/rag/author_selection.py`
- `api/app/rag/retrieval.py`
- `api/app/rag/inference.py`
- `api/tests/test_ai_sage_concept.py`
- `api/tests/test_rag.py`

## Verification Plan
- `make api-rebuild`
- `make test-backend`
- `make api-smoke`
- Manual checks:
  - Buffett-only letter query stays Buffett-only
  - dated Buffett query prefers the requested period
  - comparison query can intentionally include multiple authors

## Human Notes
- This issue is the shortest path to better retrieval quality.
- It should be treated as a query-understanding issue, not a generic “better prompts” issue.
- The model for this step should be cheap and fast by default, for example Qwen or Gemini Flash through OpenRouter.

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

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `agent_run`
**Workflow Status**: `blocked`

## Workflow Snapshot
- latest_outcome: agent_run reported changed_files that do not match the actual git diff. reported=['api/app/rag/concept_mode.py', 'api/app/rag/inference.py', 'api/app/rag/intent_router.py', 'api/app/rag/retrieval.py', 'api/app/routers/ai_sage.py', 'api/tests/test_intent_router.py'] actual=['<none>']
- next_action: Inspect blockers and rerun the appropriate stage after adding new context.
- pipeline_version: `v3`
- retry_gate_pending: `no`
- blocked_reason: agent_run reported changed_files that do not match the actual git diff. reported=['api/app/rag/concept_mode.py', 'api/app/rag/inference.py', 'api/app/rag/intent_router.py', 'api/app/rag/retrieval.py', 'api/app/routers/ai_sage.py', 'api/tests/test_intent_router.py'] actual=['<none>']

## Active Requirements
- No active requirements recorded yet.

## Prepare
Checked out `feature/issue-137-ai-sage-intent-routing-and-query-understanding` from `main` and ensured task file exists.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Blockers
- agent_run reported changed_files that do not match the actual git diff. reported=['api/app/rag/concept_mode.py', 'api/app/rag/inference.py', 'api/app/rag/intent_router.py', 'api/app/rag/retrieval.py', 'api/app/routers/ai_sage.py', 'api/tests/test_intent_router.py'] actual=['<none>']

## Permanently Failed / Gave Up
- Stop reason: agent_run reported changed_files that do not match the actual git diff. reported=['api/app/rag/concept_mode.py', 'api/app/rag/inference.py', 'api/app/rag/intent_router.py', 'api/app/rag/retrieval.py', 'api/app/routers/ai_sage.py', 'api/tests/test_intent_router.py'] actual=['<none>']
- Attempted mitigations:
- mitigation: No automated mitigation was recorded.
- Suggested human action: Fix the cited blocker and rerun the workflow on the same thread.
<!-- MACHINE_RENDERED_END -->
