# Issue 130: Intelligence Retrieval And Author Wisdom

## Objective
- Build the first useful retrieval layer for CapitalOS Decision Intelligence on top of the ingested thinker corpus.
- Turn raw ingested writings into reusable author wisdom artifacts so the system understands each author's key maxims, strengths, weaknesses, worldview, and decision style.
- Expose grounded retrieval/query APIs that can support later reasoning, questioning, and decision workflows without hardcoding any one author as the permanent center of the system.

## Program Position
- This is the foundation issue for the Decision Intelligence build plan.
- Downstream dependencies:
  - issue 131 uses this issue's retrieval and author wisdom layer in `AI Sage`
  - issue 132 uses this issue's author selection and evidence packaging for guided questioning
  - issue 133 uses this issue's evidence and author context inside decision memos
  - issue 134 expands the corpus beyond thinker writings into company intelligence
  - issue 135 uses all prior issues for reflection, calibration, and self-improvement

## Architecture Decisions
- This issue is retrieval-first, not full decision-agent scope. It should produce a strong evidence layer and author wisdom layer that later reasoning features can rely on.
- Use the best ideas from `PRD-Module-2-Investment-Intelligence-RAG.md` and `PRD-module-2.1-intelligence-retrieval.md`, but do not implement them mechanically. Preserve the design intent while using engineering judgment.
- Keep the author system config-driven. Authors come from `config/rag_authors.yaml`; no author should be hardcoded in application logic as mandatory.
- Separate three concepts clearly:
  - raw corpus retrieval
  - derived author wisdom profiles
  - later decision memo / calibration workflows
- Retrieval should be hybrid and practical:
  - semantic vector similarity over chunk embeddings
  - author/domain/expertise metadata filters
  - optional recency/source-quality balancing
- Query execution should do author selection dynamically:
  - select authors by domain fit, expertise tags, corpus evidence, and configured weight
  - weight influences ranking but does not force inclusion
- Add a persisted author wisdom artifact generated from the author corpus:
  - worldview
  - core maxims
  - strengths
  - blind spots / weaknesses
  - favored decision variables
  - anti-patterns / things they tend to avoid
  - representative citations back to corpus chunks
- The author wisdom artifact is not a digital twin. It is a compact, auditable representation of what the system currently believes the author stands for, with citations.
- Output must remain auditable and source-grounded. If the system cannot support a statement from retrieved evidence or author wisdom citations, it should not present it as grounded truth.
- This issue should stop before full memo/calibration workflows. Those are split into a follow-up issue.
- Include a thin UI surface under `Intelligence > AI Sage` so retrieval can be validated as a product flow, not only by curl.
- `AI Sage` in this issue is a verification surface, not a full chat product. It should expose backend retrieval/profile functionality clearly, with minimal UX scope.

## Scope
- Query classification for retrieval use cases:
  - corpus search
  - author understanding
  - company analysis preparation
  - lens selection / author selection
- Author wisdom profile generation and refresh
- Retrieval APIs with citations and author-aware context
- Light query-answering path that produces grounded synthesis input, not the full judgment OS
- Minimal `AI Sage` UI for exercising retrieval, author wisdom, and company-context preparation
- Curl-verifiable backend implementation remains mandatory

## Out Of Scope
- Full decision memo persistence
- Outcome reviews
- Confidence calibration analytics
- Full conversational coaching loop
- Autonomous investment recommendation engine
- Personal finance structured data queries unrelated to thinker corpus

## Acceptance Criteria
- [ ] `rag_authors.yaml` remains the source of truth for enabled authors, domains, expertise tags, weights, and discovery seeds.
- [ ] System can generate and persist an author wisdom profile for each enabled author with:
  - worldview
  - key maxims
  - strengths
  - weaknesses / blind spots
  - favored decision variables
  - representative citations
- [ ] Author wisdom generation is grounded in the ingested corpus and stores citation references to supporting chunks.
- [ ] Query flow performs author selection dynamically rather than invoking a fixed author set.
- [ ] Retrieval supports:
  - semantic retrieval
  - author filtering
  - domain / expertise filtering
  - top-k controls
  - citation-ready result payloads
- [ ] Add backend query endpoints for:
  - retrieving evidence
  - retrieving author wisdom
  - asking an author-aware grounded question
- [ ] Add a minimal `Intelligence > AI Sage` UI surface that supports:
  - entering a query
  - optional author filter
  - optional mode selection such as `Retrieve`, `Ask`, or `Company Context`
  - displaying selected authors
  - displaying a short answer or evidence summary
  - displaying cited chunks and author wisdom cards
- [ ] Query responses include:
  - selected authors
  - retrieved evidence chunks
  - citation metadata
  - short grounded answer or evidence summary
  - missing information when evidence is insufficient
- [ ] Company-analysis preparation mode exists:
  - retrieves relevant corpus evidence
  - returns which author lenses are likely relevant
  - returns a structured evidence pack for later reasoning
- [ ] All new features are testable with curl and covered by backend tests.
- [ ] Add or update a Make target or explicit documented command sequence to verify the retrieval flow end to end.

## Suggested Implementation Shape
- Add new persisted objects, names subject to engineering judgment:
  - `rag_author_profiles`
  - `rag_author_profile_citations`
  - optional query/result tables if useful for traceability
- Add services for:
  - author profile synthesis from corpus
  - author selection for query
  - retrieval orchestration
  - evidence packaging
- Add API endpoints, names subject to judgment, but likely close to:
  - `POST /rag/authors/refresh-profiles`
  - `GET /rag/authors/{author_id}/profile`
  - `POST /rag/retrieve`
  - `POST /rag/query`
  - `POST /rag/analyze/company-context`
- Add a thin frontend surface under `Intelligence > AI Sage`, likely including:
  - a query input
  - mode selector
  - author filter selector
  - results panel for answer, citations, and author wisdom cards
- Ensure author profile refresh can be rerun deterministically after new corpus ingestion.

## Verification Plan
- Sync authors and confirm enabled author registry:
  - `curl -X POST http://localhost:8000/rag/authors/sync-config`
- Confirm author profile generation:
  - `curl -X POST http://localhost:8000/rag/authors/refresh-profiles`
  - `curl http://localhost:8000/rag/authors/warren_buffett/profile`
  - `curl http://localhost:8000/rag/authors/nick_sleep/profile`
- Confirm retrieval:
  - `curl -X POST http://localhost:8000/rag/retrieve -H "Content-Type: application/json" -d '{"query":"capital allocation and moat","top_k":5}'`
- Confirm author-aware grounded query:
  - `curl -X POST http://localhost:8000/rag/query -H "Content-Type: application/json" -d '{"query":"What would Buffett care about in a business with strong customer loyalty but weak returns on capital?"}'`
- Confirm company-context preparation:
  - `curl -X POST http://localhost:8000/rag/analyze/company-context -H "Content-Type: application/json" -d '{"company":"ExampleCo","question":"Which author lenses are most relevant here?"}'`
- Backend verification:
  - `make api-rebuild`
  - `make test-backend`
- Frontend verification:
  - `make web-rebuild`
  - open `Intelligence > AI Sage`
  - verify query execution, author selection display, citations, and author wisdom rendering

## Human Notes
- The purpose of this issue is to make the authors' core wisdom sit "next to you" in a grounded way, before building a more interactive coaching system.
- The `AI Sage` UI in this issue is intentionally thin. Its purpose is to validate retrieval and author wisdom UX early, before the richer decision-copilot work in issue 131.
- If implementation becomes too broad, prioritize:
  - author wisdom profiles
  - retrieval quality
  - author selection
  - citation quality
- Do not overfit to Buffett/Munger/Marks-only workflows. The architecture must work equally for operators and future non-investment domains.

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
