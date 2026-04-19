# Issue 146: AI Sage Inference Architecture And Retrieval Fidelity Hardening

## Objective
- Reduce AI Sage dependence on multiple serial OpenRouter calls.
- Make retrieval substantially more self-sufficient so common grounded questions do not depend on expensive multi-call LLM orchestration.
- Fix the remaining behavior gaps around explicit author/entity/date/source queries, especially the Buffett/Munger/date-range case.
- Fix retrieval first before polishing synthesis behavior.

## Guiding Principles
- Quality should be as high as possible while keeping cost at zero or as low as possible.
- Value delivered must be high; otherwise the system is not worth the complexity or spend.
- Costs may not be zero because users are not running their own LLMs, so the system must make disciplined tradeoffs and deliver value without burning budget.

## Architecture Decisions
- Retrieval should be the primary source of correctness. LLM usage should be minimized and reserved for synthesis, external-data grounding, or broad questions that cannot be answered directly from corpus evidence.
- Jina remains the dedicated reranker. Prevent fallback to LLM reranking unless strictly necessary.
- Prefer deterministic query parsing before LLM routing whenever author/date/source/entity intent is obvious.
- Disable LLM author views for low-evidence cases and for single-author cases where grounded passages already answer the question sufficiently.
- Critique and suggested readings should be opt-in or conditional, not default on every request.
- If author views are still needed, batch them into one inference call rather than one call per author.
- Add an `.env` toggle that disables LLM synthesis entirely for grounded retrieval queries. When enabled, the system should return retrieval results plus deterministic/template summarization only; routing and reranking may still run if needed.
- Add request-level degradation rules for OpenRouter slowness/rate limits:
  - no critique
  - no suggested readings
  - optional no synthesis, only grounded passages plus a template summary
- Add explicit logs and user-visible signals for major upstream failures such as OpenRouter rate limits, Jina rate limits, and critical degradation decisions. Surface these prominently in logs and UI.

## Context And Current Design Choices
- Inference provider is OpenRouter for AI Sage inference queries.
- Dedicated reranker provider is Jina.
- The inference model has been downgraded from Sonnet 4.6 to Qwen 3.6 Plus for cost reasons.
- Routing model is explicitly configured separately via `ROUTING_LLM_MODEL`.
- Current ingested corpus scope is intentionally narrow and should be respected during evaluation.
- This issue should not repeat broad implementation review work that was already done elsewhere.

## Problem Statement

### What is wrong today

The current AI Sage architecture spends too much latency and budget on serial LLM calls inside a single request. This makes OpenRouter key limits and provider slowdowns disproportionately harmful.

At the same time, retrieval fidelity is still not good enough for explicit constrained questions. A representative failure remains:

- Query: `What did Warren Buffett say about Charlie Munger from 2020 to 2025 in letters?`

Observed bad behavior:
- parses `Charlie Munger` as a second corpus author instead of the topic/entity
- relaxes explicit date constraints
- can surface irrelevant older Buffett passages
- can drift into other authors even when the user clearly asked for Buffett
- can return weak/irrelevant passages while still appearing superficially successful

## Required Work

### 1) Reduce serial LLM dependence in AI Sage
- Ensure retrieval is the primary source of correctness for ordinary corpus-grounded questions.
- Larger LLM calls should only be used when:
  - synthesis is actually needed
  - external data is needed
  - the user is asking a broad question that cannot be answered directly from corpus evidence
- A query like:
  - `If Warren Buffett looks at Novo Nordisk what questions would he ask?`
  may justify model search and internet grounding.
- A query like:
  - `What did Warren Buffett say about Charlie Munger from 2020 to 2025?`
  should not depend on a chain of expensive inference calls to get the core retrieval right.
- Tighten the call graph explicitly:
  - remove critique from the default request path
  - remove LLM suggested-readings generation from the default path
  - remove per-author author-view calls from the default response path for grounded single-author queries
  - disable per-author LLM views by default for single-author grounded queries
  - keep LLM rerank fallback effectively off in normal operation when Jina is available
  - use at most one synthesis call for ordinary grounded queries when synthesis is enabled
- If richer output is still needed, combine author views and synthesis into one single post-retrieval LLM call that returns:
  - final answer
  - optional per-author bullets
  - grounded caveats
- Do not combine routing with synthesis:
  - routing is pre-retrieval
  - synthesis is post-retrieval
  - they are different stages and should remain separate
- Add and document an `.env` toggle for no-synthesis mode so operators can force retrieval-first behavior while debugging or controlling cost.
- Target architecture for grounded corpus queries:
  - deterministic intent parse
  - DB retrieval
  - Jina rerank
  - one synthesis call only if needed
- Target call budget after the fix:
  - grounded single-author explicit query: 0 to 1 OpenRouter calls
  - grounded single-author weak-evidence or rate-limited query: 0 OpenRouter calls with passages plus deterministic/template summary
  - grounded multi-author query: 0 to 1 OpenRouter calls
  - ambiguous/broad routed query: 1 to 2 OpenRouter calls
  - external-web/model-search query: 2 to 3 OpenRouter calls maximum
  - critique and suggested readings should not add default calls

### 2) Harden constrained retrieval behavior
- Fix the real user-facing behavior for explicit author/entity/date/source questions.
- If the question is:
  - `What did Warren Buffett say about Charlie Munger from 2020 to 2025?`
  then retrieval should stay in Warren Buffett's corpus and respect the date range by default.
- If the question is:
  - `What do authors say about Charlie Munger?`
  then retrieval may search across all currently ingested author corpora.
- Query interpretation must distinguish:
  - corpus author constraint
  - topic/entity target
  - date/source constraints
  - broad/meta/synthesis intent

### 3) Improve runtime degradation behavior
- If OpenRouter is slow or rate-limited:
  - skip critique
  - skip suggested readings
  - optionally skip synthesis and return grounded passages with a deterministic summary
- If Jina is slow or rate-limited:
  - log it clearly
  - degrade gracefully
  - surface a visible warning in logs/UI

### 4) Improve observability
- Add logs for:
  - OpenRouter rate limits / failures
  - Jina rate limits / failures
  - degradation decisions
  - major retrieval fallback/constraint-relaxation decisions
- Ensure important failures are visible in the UI/log stream and highlighted clearly.

### 5) Fix the retrieval scoring / percentage UI bug
- Fix the current UI behavior where correct passages can show `0% match`.
- The displayed percentage must not be derived blindly from vector cosine similarity when the result came from sparse retrieval, hybrid RRF, or reranking.
- For hybrid results, expose and display the correct notion of score:
  - vector similarity when the result is dense-only
  - reranker score when reranking is authoritative
  - otherwise show a neutral label such as `Matched` instead of a fake percentage
- Do not show misleading percentages that imply irrelevance when the passage is actually a valid keyword/RRF/reranked hit.
- Add tests for the scoring display contract so hybrid keyword matches no longer appear as `0%`.

## Query Test Suite

Run and inspect real end-to-end behavior for at least these queries.

### Constrained author/entity/date/source queries
- `What did Warren Buffett say about Charlie Munger from 2020 to 2025?`
- `What did Warren Buffett say about Charlie Munger from 2020 to 2025 in letters?`

Expected:
- Buffett corpus only
- date constraints respected by default
- no unrelated authors
- if evidence is weak/absent, the system should be honest rather than silently broadening

### Cross-author/entity queries
- `What do authors say about Charlie Munger?`

Expected:
- search all currently ingested authors only
- do not pretend coverage outside the ingested corpus

### Concept queries
- `How should I think about moat durability?`
- `What does Warren Buffett say about moat durability?`

Expected:
- top passages are actually about moats / durable advantage

### Entity/company-specific queries
- `What has Warren Buffett said about GEICO?`
- `How does Buffett describe GEICO's moat?`

Expected:
- strong Buffett-only entity retrieval

### Meta / synthesis-style queries
- `What can a user learn from Buffett's capital allocation in insurance?`
- `What principles emerge from Buffett's writing on insurance float and capital allocation?`

Expected:
- semantic interpretation is strong
- retrieval stays grounded
- synthesis only happens when justified

### Negative / strict queries
- `What did Warren Buffett say about Munger from 2023 to 2025 in letters?`
- `What did Nick Sleep say about GEICO?`

Expected:
- if evidence is absent, the system should say so honestly
- do not fake recall by broadening unless explicitly allowed and surfaced

## Acceptance Criteria
- [ ] AI Sage no longer relies on a chain of unnecessary serial OpenRouter calls for ordinary retrieval requests.
- [ ] Deterministic parsing handles obvious author/date/source/entity queries without spending LLM budget.
- [ ] An `.env` toggle exists to disable LLM synthesis for grounded retrieval flows while still allowing routing/reranking if configured.
- [ ] LLM author views are disabled for low-evidence or clearly single-author grounded cases.
- [ ] Critique and suggested readings are not generated by default on every request.
- [ ] If author views remain enabled, they are batched rather than one-call-per-author.
- [ ] Jina remains the primary reranker and LLM reranking fallback is avoided unless strictly necessary.
- [ ] Explicit author/entity/date/source queries behave correctly on the real query suite above.
- [ ] The AI Sage UI no longer shows misleading `0% match` or fake percentages for hybrid/sparse/reranked results.
- [ ] OpenRouter and Jina failure/rate-limit conditions are logged clearly and surfaced to the UI/log stream.

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
