# Issue 155: Derived author knowledge layer and wiki pages

## Objective
- Add a derived, wiki-like knowledge layer on top of the ingested corpus so CapitalOS can maintain reusable author, concept, and work-level synthesized pages without replacing the evidence-first corpus.
- Reuse the cleaned logical-document corpus as the source of truth while keeping all derived pages traceable back to underlying evidence.
- Reduce repeated “rediscover from chunks every query” behavior for stable author/corpus knowledge while preserving provenance and author fidelity.

## Architecture Decisions
- Decision 1: This is a **derived layer above ingestion**, not a replacement for ingestion, logical documents, chunks, or retrieval evidence.
- Decision 2: The canonical source of truth remains the ingested corpus (`rag_sources`, `rag_documents`, `rag_chunks`, metadata, and provenance).
- Decision 3: The derived layer should maintain structured pages or records such as:
- Decision 3a: author pages
- Decision 3b: concept/topic pages
- Decision 3c: work pages
- Decision 3d: optionally collection pages
- Decision 4: Derived pages must store provenance/evidence references to source documents/chunks and should never exist as unattributed freeform summaries.
- Decision 5: Derived pages may be generated or refreshed incrementally as corpus ingestion changes, rather than requiring full rebuilds every time.
- Decision 6: The first version should prioritize deterministic page storage, refresh workflows, provenance, and read APIs. Full autonomous agent maintenance can come later.
- Decision 7: The design should borrow the useful parts of LLM-wiki style systems (raw-source vs derived-page separation, maintained compiled pages, navigable concept graph) while preserving CapitalOS’s stricter provenance and author-fidelity requirements.
- Decision 8: Derived pages should be readable in-product and also usable by AI Sage/retrieval as a higher-level context layer when appropriate.

## Acceptance Criteria
- [ ] A new derived knowledge/page layer exists above the ingested corpus.
- [ ] The raw corpus remains the source of truth; derived pages are clearly marked as derived artifacts.
- [ ] The system supports at least these page/entity types:
- [ ] author page
- [ ] concept/topic page
- [ ] work page
- [ ] Each derived page stores provenance references to the underlying corpus documents/chunks used to support it.
- [ ] Derived pages can be regenerated or refreshed after new ingestion.
- [ ] The refresh model supports incremental updates rather than requiring a full corpus rebuild every time.
- [ ] The data model clearly separates:
- [ ] raw source/document storage
- [ ] logical document metadata
- [ ] derived page content
- [ ] provenance/evidence links
- [ ] The first version exposes backend APIs to list and fetch derived pages.
- [ ] The first version exposes a user-facing UI to browse derived pages.
- [ ] Derived author pages summarize an author corpus without losing the ability to inspect underlying evidence.
- [ ] Derived concept pages support cross-document synthesis while keeping citations/provenance attached.
- [ ] Derived work pages can summarize a single logical work and link back to the work text and source metadata.
- [ ] The design is compatible with future graph/backlink navigation.
- [ ] Tests cover storage, provenance linking, refresh/update behavior, and page retrieval/rendering.
- [ ] The feature is verifiable via Makefile commands and curl-verifiable APIs.

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
- Last Updated: `2026-04-25`

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
  - `Should the first version store pages as markdown-like content, structured JSON sections, or both?`
  - `Should derived pages be refreshed on-demand, on ingestion completion, or by scheduled maintenance jobs?`
  - `Which page types should be queryable by AI Sage first: author, concept, or work?`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._
