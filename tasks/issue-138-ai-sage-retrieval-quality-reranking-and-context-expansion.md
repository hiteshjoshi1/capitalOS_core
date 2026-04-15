# Issue 138: AI Sage Retrieval Quality, Reranking, and Context Expansion

## Objective
- Improve AI Sage answer quality by fixing the evidence pipeline, not by polishing prompts.
- Make corpus-backed answers feel materially better than generic ChatGPT by:
  - retrieving broader relevant evidence
  - reranking it against the full semantic intent of the query
  - expanding context around the winning chunks
  - synthesizing and critiquing from that stronger evidence pack

## Why This Issue Exists
- AI Sage currently retrieves a small nearest-neighbor set and then synthesizes directly from it.
- That causes repetitive answers where one motif dominates and other relevant themes never surface.
- Example failure:
  - a Buffett query about Charlie keeps surfacing `correcting mistakes` / `thumb-sucking`
  - but misses other relevant views such as thinking like business owners rather than stock pickers
- This is no longer primarily an author-intent problem.
- It is a retrieval-quality problem:
  - broad recall is weak
  - diversity is weak
  - reranking is absent
  - context expansion is absent

## Program Position
- Depends on issue 137.
- This is still in service of concept mode answer quality.
- It should land before broader research-memory or company-intelligence expansion if the latter would build on weak evidence quality.

## Central Product Idea
- Keep the query-understanding step from issue 137.
- After that, AI Sage should behave like a better research pipeline:
  1. understand the query
  2. retrieve a broad set of potentially relevant corpus instances
  3. use a cheap normal model call to identify what is truly relevant to the query as a whole
  4. fetch more context around the winning chunks
  5. synthesize an overall view from that stronger evidence pack
  6. run critique over the same stronger evidence pack

## User Intent
- The user wants the system to actually find what the author said across the corpus.
- The user does not want:
  - one or two recurring motifs repeated back
  - a few nearest-neighbor snippets treated as the whole answer
  - evidence that feels thin even when the corpus clearly contains richer material
- If the corpus contains multiple relevant instances, the system should surface them.

## Required Retrieval Behavior
- Treat retrieval as a multi-stage evidence pipeline, not one blunt vector search.
- The system should:
  - retrieve broadly first
  - favor multiple relevant instances across the corpus
  - use a normal cheap/fast model call for reranking, not the main frontier synthesis model
  - expand context around winning chunks before synthesis
  - build the final answer and critique from the expanded evidence pack

## Specific Direction
- Keep doing the query-understanding / author-pinning work from issue 137.
- Then:
  1. pick as many potentially relevant instances from the corpus as needed
  2. use a normal model call to decide which of those are truly relevant to the query’s semantic intent
  3. fetch materially more surrounding context for those winning chunks
  4. use that evidence pack to form the overall opinion
  5. run critique against that same stronger evidence pack

## What Good Looks Like
- A Buffett or Nick Sleep answer should feel like someone actually searched their corpus carefully.
- The answer should surface multiple distinct relevant ideas when they exist.
- The evidence set should not collapse into one repeated theme unless the corpus itself is genuinely narrow.
- The synthesis should feel grounded in breadth, not just polished prose over a few snippets.
- The critique should challenge the synthesis based on the stronger evidence pack, not generic skepticism.

## In Scope
- Broader candidate retrieval for AI Sage concept mode
- Reranking of retrieved candidates against full-query semantic intent
- Use of a cheap/fast model for reranking, independent from main synthesis model if needed
- Context expansion around top-ranked chunks
- Stronger evidence-pack construction before synthesis and critique
- Tests that prove retrieval quality improved on real query shapes

## Out Of Scope
- Research memory / save-retrieve workflows
- Live company research
- UI redesign
- Portfolio-level monitoring
- Calibration / outcome review
- Generic prompt-only tweaking that leaves retrieval behavior unchanged

## Example Queries That Must Improve
- Buffett:
  - `What does Buffett say about Charlie Munger?`
  - `What are Buffett's best aphorisms on mistakes, patience, and capital allocation?`
  - `How does Buffett describe thinking like a business owner rather than a stock picker?`
  - `Across Buffett's letters from 2020 to 2025, what life advice and investment advice does he repeat?`
- Nick Sleep:
  - `What does Nick Sleep mean by scale economies shared?`
  - `What does Nick Sleep say about Amazon, Costco, and service to customers?`
  - `What is Nick Sleep's view on long-termism and the behavior required to hold compounders?`
  - `What are Nick Sleep's aphorisms or memorable lines about competition, customer focus, and patience?`

## Acceptance Criteria
- [ ] AI Sage no longer relies on a single small nearest-neighbor set as the whole evidence pack for concept-mode answers.
- [ ] Retrieval first gathers a broader candidate set from the selected author corpus before final evidence selection.
- [ ] A cheap/fast model call is used to rerank or filter candidate evidence against the full semantic intent of the query.
- [ ] Winning chunks are expanded into materially richer surrounding context before synthesis.
- [ ] Synthesis and critique both run over the curated expanded evidence pack, not just the first-pass chunk list.
- [ ] Buffett-focused queries about Charlie can surface more than the recurring `mistakes/thumb-sucking` motif when the corpus contains other relevant material.
- [ ] Nick Sleep queries can surface multiple distinct examples or themes when those exist across his writings.
- [ ] Tests cover retrieval breadth, reranking behavior, context expansion, and answer quality on representative Buffett/Nick query shapes.

## Product Guardrails
- Do not regress explicit author constraints from issue 137.
- Do not solve this with “better wording” alone.
- Do not let the reranking model become the final synthesis model.
- Do not overfit to one or two canned example prompts.
- Do not hardcode Buffett/Nick special cases; the pipeline should improve corpus-backed retrieval generally.
- Keep asking:
  - does this improve answer quality now?
  - does this make the evidence pack meaningfully better?
  - if not, defer it

## Verification Plan
- `make api-rebuild`
- `make test-backend`
- `make api-smoke`
- Manual/live checks against the real corpus for at least:
  - `What does Buffett say about Charlie Munger?`
  - `How does Buffett describe thinking like a business owner rather than a stock picker?`
  - `What does Nick Sleep mean by scale economies shared?`
- For each check, verify:
  - the answer is grounded in multiple relevant ideas when they exist
  - the same one or two snippets do not dominate the whole answer
  - the evidence pack shows broader and more context-rich retrieval

## Human Notes
- Judge this issue by answer quality, not by whether the architecture looks clever.
- If the system still feels like it is repeating one chunk family again and again, the issue is not done.
- The standard is simple:
  - does it feel like the system really searched the author corpus?

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
**Current Stage**: `deterministic_gates`
**Workflow Status**: `blocked`

## Workflow Snapshot
- latest_outcome: Implemented Issue 138 retrieval-quality upgrades for AI Sage concept mode: broad candidate retrieval, cheap-model reranking, diversity-aware winner selection, and context expansion before synthesis/critique. Added targeted backend tests for breadth, reranking, context expansion, and representative Buffett/Nick query shapes.
- next_action: Inspect deterministic gate failures, apply mitigations, then rerun the workflow.
- pipeline_version: `v3`
- provider_model: `codex/gpt-5.3-codex`
- retry_gate_pending: `no`
- blocked_reason: Agent run reported semantic intent not achieved.

## Active Requirements
- Acceptance criterion: AI Sage no longer relies on a single small nearest-neighbor set as the whole evidence pack for concept-mode answers.
- Acceptance criterion: Retrieval first gathers a broader candidate set from the selected author corpus before final evidence selection.
- Acceptance criterion: A cheap/fast model call is used to rerank or filter candidate evidence against the full semantic intent of the query.
- Acceptance criterion: Winning chunks are expanded into materially richer surrounding context before synthesis.
- Acceptance criterion: Synthesis and critique both run over the curated expanded evidence pack, not just the first-pass chunk list.
- Acceptance criterion: Buffett-focused queries about Charlie can surface more than recurring mistakes/thumb-sucking motifs when richer corpus material exists.
- Acceptance criterion: Nick Sleep queries can surface multiple distinct examples/themes when they exist across writings.
- Acceptance criterion: Tests cover retrieval breadth, reranking behavior, context expansion, and representative Buffett/Nick query shapes.

## Prepare
Checked out `feature/issue-138-ai-sage-retrieval-quality-reranking-and-context-expansion` from `main` and ensured task file exists.

## Plan Summary
Kept issue-137 intent routing/author pinning, then inserted a multi-stage evidence pipeline in concept mode: broad retrieval -> rerank with routing model -> expand context around winners -> synthesize/critique from expanded evidence; validated with new unit coverage and full make-based verification attempts.

### Architecture Decisions
- Preserved existing query-understanding and author-constraint behavior (issue 137) as stage 0/1 and changed only evidence-pipeline internals.
- Used the routing model path (`routing_model` + `create_routing_client`) for reranking so reranking remains cheap/fast and separate from main synthesis model.
- Expanded winning chunks by neighboring chunk indices within the same document while keeping final evidence-pack size controlled by `top_k_chunks`.
- Added diversity capping per document during winner selection to reduce motif collapse from a single chunk family/document.
- Maintained fallback behavior: heuristic reranking when routing LLM unavailable and graceful context-expansion fallback on DB/query errors.

### Acceptance Criteria
- AI Sage no longer relies on a single small nearest-neighbor set as the whole evidence pack for concept-mode answers.
- Retrieval first gathers a broader candidate set from the selected author corpus before final evidence selection.
- A cheap/fast model call is used to rerank or filter candidate evidence against the full semantic intent of the query.
- Winning chunks are expanded into materially richer surrounding context before synthesis.
- Synthesis and critique both run over the curated expanded evidence pack, not just the first-pass chunk list.
- Buffett-focused queries about Charlie can surface more than recurring mistakes/thumb-sucking motifs when richer corpus material exists.
- Nick Sleep queries can surface multiple distinct examples/themes when they exist across writings.
- Tests cover retrieval breadth, reranking behavior, context expansion, and representative Buffett/Nick query shapes.

### Planned Paths
- `api/app/rag/concept_mode.py`
- `api/app/rag/retrieval.py`
- `api/tests/test_ai_sage_retrieval_pipeline.py`

## Build Summary
Implemented Issue 138 retrieval-quality upgrades for AI Sage concept mode: broad candidate retrieval, cheap-model reranking, diversity-aware winner selection, and context expansion before synthesis/critique. Added targeted backend tests for breadth, reranking, context expansion, and representative Buffett/Nick query shapes.

### Changed Files
- `api/app/rag/concept_mode.py`
- `api/app/rag/retrieval.py`
- `api/tests/test_ai_sage_retrieval_pipeline.py`
- `tasks/issue-138-ai-sage-retrieval-quality-reranking-and-context-expansion.md`

## Latest Verification
- api-rebuild: PASS (exit 0)
- contract-backend: PASS (exit 0)
- test-backend: PASS (exit 0)
- api-smoke: PASS (exit 0)
- lint: PASS (exit 0)
- typecheck: PASS (exit 0)
- contract-frontend: PASS (exit 0)
- test-frontend: PASS (exit 0)
- e2e: PASS (exit 0)
- orch-test: PASS (exit 0)

## Extra Files Changed
- None

## Agent Run Summary
Implemented Issue 138 retrieval-quality upgrades for AI Sage concept mode: broad candidate retrieval, cheap-model reranking, diversity-aware winner selection, and context expansion before synthesis/critique. Added targeted backend tests for breadth, reranking, context expansion, and representative Buffett/Nick query shapes.

- semantic_intent_achieved: `False`
- provider_model: `codex/gpt-5.3-codex`

### Semantic Checks
- `pass` AI Sage no longer relies on a single small nearest-neighbor set as the whole evidence pack for concept-mode answers.: Concept mode now runs broad candidate retrieval + reranking + context expansion before evidence synthesis.
- `pass` Retrieval first gathers a broader candidate set from the selected author corpus before final evidence selection.: Introduced broad candidate pool sizing (`_BROAD_RETRIEVAL_*`) and `_collect_candidate_chunks` before top-k winner selection.
- `pass` A cheap/fast model call is used to rerank or filter candidate evidence against the full semantic intent of the query.: Added `_llm_rerank_candidate_indices` using routing-model client (`routing_model`/`create_routing_client`) independent of synthesis model.
- `pass` Winning chunks are expanded into materially richer surrounding context before synthesis.: Added `expand_chunks_with_context` in retrieval layer and applied it to winning chunks before enrichment.
- `pass` Synthesis and critique both run over the curated expanded evidence pack, not just the first-pass chunk list.: Author view/synthesis/critique now consume evidence derived from expanded winning chunks.
- `partial` Buffett-focused queries about Charlie can surface more than recurring mistakes/thumb-sucking motif when richer material exists.: Added deterministic unit test (`test_buffett_query_surfaces_multiple_distinct_motifs`) validating multi-theme selection; live corpus smoke verification blocked by `make api-smoke` environment error.
- `partial` Nick Sleep queries can surface multiple distinct examples/themes when those exist across writings.: Added deterministic unit test (`test_nick_sleep_query_surfaces_multiple_distinct_examples`) validating multi-theme retrieval; live corpus smoke verification blocked by `make api-smoke` environment error.
- `pass` Tests cover retrieval breadth, reranking behavior, context expansion, and answer quality on representative Buffett/Nick query shapes.: New test module `api/tests/test_ai_sage_retrieval_pipeline.py` covers all required pipeline dimensions.

### Risk Flags
- verification-blocked-docker-socket
- manual-live-corpus-checks-not-executed
- contract-backend-gate-failed-in-environment

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Blockers
- Agent run reported semantic intent not achieved.

## Permanently Failed / Gave Up
- Stop reason: Agent run reported semantic intent not achieved.
- Attempted mitigations:
- mitigation: No automated mitigation was recorded.
- Suggested human action: Fix the cited blocker and rerun the workflow on the same thread.
<!-- MACHINE_RENDERED_END -->
