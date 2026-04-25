# Issue 152: Pre-ingestion document fanout and quality gates

## Objective
- Add the ingestion primitives required to turn one fetched raw source into multiple clean logical documents with strong metadata and reliable post-ingest validation.
- Make compendium/omnibus sources ingestable without polluting retrieval, while preserving the current simple single-document path for ordinary sources.
- Prevent false-positive “successful” ingests where only title/header noise or other unusable thin content was inserted.

## Architecture Decisions
- Decision 1: Introduce an ingestion mode that supports **one raw source fanning out into many logical documents** during a single ingestion run.
- Decision 2: Preserve the existing simple path for ordinary single-writing sources. If the fetched source represents a single work, the pipeline should still create one document as it does today.
- Decision 3: Add a structured document-slice/fanout layer after parsing and before persistence. This layer should be deterministic and based on parsed headings/sections and explicit ingestion configuration, not LLM segmentation.
- Decision 4: Support per-logical-document metadata beyond the current schema, including fields equivalent to `author`, `title`, `year`, `venue`, `collection`, `canonical_work_id`, `canonical_status`, `dedupe_priority`, `source_section`, and related context.
- Decision 5: Support optional parent-child linkage between logical documents, so editorial or auxiliary sections like `Talk X Revisited` can be separate child documents of a parent talk when desired.
- Decision 6: The fanout layer must support author override per logical document so a shared omnibus source can yield documents attributed to different authors when required.
- Decision 7: Post-ingest validation must be **deterministic and non-brittle**. It should use heuristics and thresholds with conservative defaults, not LLM judgment.
- Decision 8: Post-ingest validation should operate at the logical-document level and fail clearly when a produced document is too thin or obviously low quality, while avoiding fragile thresholds that reject valid short documents.
- Decision 9: Quality validation failures should be recorded explicitly and auditable in job/document metadata, with failure categories that distinguish thin-content extraction from no-content-selected and parse/network errors.
- Decision 10: The existing selective-ingestion controls (`start_after`, `stop_before`, `include_headings`, `exclude_sections`) should remain compatible and become inputs to the fanout layer rather than the end-state of ingestion itself.
- Decision 11: Source-level raw text should remain auditable, but logical-document persistence should reflect the selected/sliced content rather than always storing the full fetched source text as each document’s `clean_text`.
- Decision 12: The implementation should be generic for future compendium sources, not hardcoded to Charlie Munger or Stripe.

## Acceptance Criteria
- [ ] The ingestion architecture supports two deterministic modes:
- [ ] `single_work` — one fetched source persists as one logical document
- [ ] `fanout` — one fetched source persists as multiple logical documents
- [ ] The pipeline can take one parsed raw source and create multiple logical documents from explicit section boundaries in a single run.
- [ ] Each logical document persists its own `clean_text` reflecting only its selected content, not the full raw source by default.
- [ ] Raw-source auditability is preserved, either on the source record, source-level parse artifact, or another durable audit path.
- [ ] The data model supports per-document metadata beyond the current minimal `title/published_at/raw_text/clean_text` set.
- [ ] The implementation supports metadata fields equivalent to:
- [ ] `author_id` or author override at the logical-document level
- [ ] `title`
- [ ] `year` or `published_at`
- [ ] `venue`
- [ ] `collection`
- [ ] `canonical_work_id`
- [ ] `canonical_status`
- [ ] `dedupe_priority`
- [ ] `source_section`
- [ ] `note_taker` where applicable
- [ ] `work_type` or equivalent contextual classification
- [ ] Optional parent-child linkage exists for logical documents.
- [ ] Parent-child linkage can represent cases like `Talk X Revisited` as a child/appendix/editorial companion to a parent talk.
- [ ] If parent-child linkage is not available for all document types, the implementation documents the supported scope and fallback behavior clearly.
- [ ] The ingestion layer can attribute different logical documents from the same raw source to different authors when explicit fanout metadata requires it.
- [ ] The existing selective-ingestion controls remain supported and integrate cleanly with the new fanout model.
- [ ] Deterministic post-ingest quality validation runs after each logical document is produced.
- [ ] Quality validation does not rely on LLM/model judgment.
- [ ] Quality validation is not brittle; it must use conservative heuristics that reduce false positives on legitimately short documents.
- [ ] The validation design considers more than one signal, such as:
- [ ] minimum clean text length
- [ ] minimum chunk count
- [ ] title/header-only detection
- [ ] ratio of body text to boilerplate/title text
- [ ] optional section-count expectations when fanout/selection rules are used
- [ ] A low-quality extraction does not silently pass as a successful ingestion.
- [ ] Low-quality extraction results in a clear failure or structured rejected-document outcome, with durable audit metadata explaining why.
- [ ] The system can distinguish at least these ingestion failure classes:
- [ ] `no_content_selected`
- [ ] `empty_text_extraction`
- [ ] `low_quality_extraction`
- [ ] `parse_failed`
- [ ] `network_error`
- [ ] For fanout ingestion, one bad logical document does not necessarily force silent acceptance of all others; the implementation defines and tests whether failure is per-document, per-batch, or both.
- [ ] The ingestion result model exposes enough detail to verify what logical documents were created, rejected, skipped, or failed.
- [ ] Tests cover:
- [ ] single-work path unchanged
- [ ] fanout from one raw source into many logical documents
- [ ] per-document metadata persistence
- [ ] parent-child linkage
- [ ] author override within one raw source
- [ ] low-quality detection for shell/header-only ingestion
- [ ] non-brittle acceptance of a valid but short document
- [ ] Verifiable Makefile/test commands exist for the change.

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
  - `Should fanout metadata live in a new logical-work/document table or as an extension of rag_documents?`
  - `Should per-document quality validation reject only that logical document or fail the entire raw-source ingestion run by default?`
  - `What is the minimum metadata set required for retrieval weighting vs. citation display?`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._
