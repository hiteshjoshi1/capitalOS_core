# Issue 162: Author Library structured rendering, table fidelity, and spaCy sentence segmentation

## Objective
- Fix the Author Library reading experience so author documents render as readable structured content instead of a flattened text blob.
- Preserve and display tables correctly in the reader while also improving the rendering of normal prose, headings, and lists.
- Replace the current regex-based sentence splitter with a spaCy-based sentence segmentation path so chunking quality improves and semantic chunking can be validated on a stronger foundation.

## Problem Statement

### What is wrong today

The current ingestion and reader pipeline loses too much structure between parse time and display time:

1. Tables may be converted into Markdown-like text during parsing, but the Author Library reader does not render them as tables. It renders one large `clean_text` blob as plain pre-wrapped text.
2. Non-table content also renders poorly because headings, paragraphs, lists, and section boundaries are flattened into a single reader surface instead of a structured document view.
3. Structured parse output exists transiently during ingestion, but the reader API does not expose a structured content model for document rendering.
4. The current regex sentence splitter in `api/app/rag/ingestion/chunker.py` is too brittle for finance prose, transcripts, OCR noise, abbreviations, and PDF line-wrap artifacts.
5. Semantic chunking was disabled because the sentence segmentation base is not reliable enough.

### Why this hurts product quality

1. The Author Library looks low fidelity even when ingestion captured better structure upstream.
2. Tables in important source material become hard to read and hard to trust.
3. The reader is not usable as a serious research surface because even normal prose is displayed as a raw blob.
4. Poor sentence segmentation produces poor semantic chunk boundaries, which hurts retrieval quality when semantic chunking is enabled.
5. The current system is not clearly documented end-to-end for how structured parsing, chunking, persistence, and reader rendering are supposed to work.

## Architecture Decisions
- Decision 1: The reader must stop using `clean_text` as the primary rendering source when structured content is available.
- Decision 2: Structured document content must be persisted as first-party application data, not left only in transient parse-time objects.
- Decision 3: The document detail API must remain backward-compatible by keeping `clean_text`, while adding a new optional structured-content field for reader clients.
- Decision 4: Tables must be represented in a renderable structured format, not only as flattened text. Raw Markdown may still be retained for auditability and retrieval.
- Decision 5: The Author Library frontend must render typed content blocks such as headings, paragraphs, lists, quotes, and tables instead of dumping a single text blob.
- Decision 6: Simple and moderately structured tables should render as real HTML tables in the reader. If a table cannot be normalized cleanly, the fallback must still be more readable than the current raw blob.
- Decision 7: Sentence segmentation for chunking must use spaCy, specifically a deterministic sentencizer-based pipeline rather than the current regex default.
- Decision 8: Regex-based sentence splitting may remain only as a fallback path, but it must no longer be the primary segmentation strategy in normal Dockerized application runs.
- Decision 9: Semantic chunking should remain toggleable, but the underlying sentence segmentation used by recursive and semantic chunking should be upgraded in this issue so semantic chunking can be re-evaluated on real corpus data.
- Decision 10: This issue is deterministic and rendering-focused. No LLM-based table summarization or rewriting should be introduced here.
- Decision 11: The updated ingestion-rendering architecture should be documented explicitly, including an as-is / to-be explanation and a technical diagram.
- Decision 12: The reader payload should preserve enough stable block or passage identity for AI Sage citations to deep-link into the document and highlight the cited location in a follow-up iteration.

## Current State Summary
- Parsing already extracts some table structure:
  - HTML tables are converted to Markdown-like tables.
  - Unstructured PDF table HTML is converted to Markdown-like tables when available.
- Logical document construction may already prefer `table_markdown` over flat table text in some paths.
- The reader API currently returns `clean_text` only as the primary document body payload.
- The Author Library UI currently renders that payload directly as plain pre-wrapped text.
- The sentence splitter in the chunker is regex-based, and semantic chunking depends on that sentence segmentation.

## Proposed Technical Design

### 1. Persist structured content for documents

Add a persisted structured-content representation for logical documents.

The implementation may use either:
- a new JSONB field on `rag_documents`, such as `content_blocks_json`, or
- a normalized companion table such as `rag_document_blocks`

but whichever design is chosen must satisfy all of the following:
- preserve stable ordering
- preserve block types
- preserve section headings and list boundaries
- preserve table structure for rendering
- remain easy to return from the document detail API

Each structured block should support a shape equivalent to:

```json
{
  "type": "paragraph | heading | list | quote | table",
  "order": 12,
  "heading": "Optional heading text",
  "level": 2,
  "text": "Paragraph or quote text",
  "items": ["list item 1", "list item 2"],
  "table_markdown": "| Col A | Col B |",
  "table_rows": [["Col A", "Col B"], ["1", "2"]],
  "metadata": {}
}
```

### 2. Improve table preservation

The ingestion pipeline should preserve enough table information to render row/column relationships in the reader.

Required behavior:
- continue storing raw table Markdown or equivalent textual representation for auditability and possible retrieval use
- add a normalized row/cell representation for display where possible
- retain table order relative to surrounding prose
- preserve nearby headings/section context so tables do not appear detached from their source context

Known limitations that should be handled honestly:
- complex PDF tables with merged cells may not normalize perfectly
- when full normalization is not possible, the reader should fall back to a readable table-oriented surface rather than a collapsed prose blob

### 3. Render structured content in Author Library

Update the Author Library reader so it renders structured content blocks rather than `clean_text` alone.

Reader requirements:
- headings render as headings
- prose renders as proper paragraphs with readable spacing
- list items render as lists
- block quotes or transcript-style quoted sections render distinctly when available
- tables render as actual table UI with row and column alignment
- long tables remain scrollable horizontally where needed
- the old `clean_text` fallback remains available for legacy documents that have no structured-content payload
- the structured model should leave room for passage anchors or block IDs so AI Sage can later land at a cited passage instead of always opening at the top

The reader should not expose raw pipe-table Markdown by default when a structured table payload is available.

### 4. Fix non-table prose rendering quality

This issue is not only about tables.

The reader should stop flattening all prose into one monolithic text block. It should preserve:
- section boundaries
- paragraph spacing
- list boundaries
- title/heading hierarchy where captured
- readable line length and typography for long-form reading

The API should expose enough structure so the frontend does not need to reconstruct paragraphs heuristically from `clean_text`.

### 5. Replace regex sentence splitting with spaCy

Replace the current regex-based sentence splitting path in `api/app/rag/ingestion/chunker.py` with a spaCy-based segmentation path.

Implementation guidance:
- use a deterministic spaCy pipeline appropriate for sentence segmentation, such as `spacy.blank("en")` with `sentencizer`, unless a stronger pipeline is clearly necessary
- keep dependency and runtime overhead reasonable
- ensure Docker images install and run the chosen spaCy setup deterministically
- retain a guarded regex fallback only for environments where spaCy is unavailable, but do not treat that as the primary supported path

Expected gains:
- better handling of abbreviations
- better handling of initials and decimal numbers
- fewer broken boundaries in transcript/Q&A material
- better sentence boundaries before semantic boundary detection

### 6. Re-evaluate semantic chunking on top of spaCy

This issue does not require globally enabling semantic chunking by default, but it must make semantic chunking re-testable on a stronger sentence-boundary base.

Required outcomes:
- recursive chunking uses spaCy sentence boundaries when sentence-level splitting is needed
- semantic chunking, when enabled, also uses spaCy sentence boundaries
- regression tests cover known bad cases from the corpus
- docs clearly state whether semantic chunking remains opt-in or becomes safe to enable by default

### 7. Document the architecture

Add or update technical documentation covering:
- as-is behavior
- target behavior after this issue
- parser -> normalization -> logical document -> chunking -> persistence -> reader rendering flow
- how tables are represented for retrieval vs display
- how sentence segmentation works after the spaCy migration
- any reingestion expectations for existing documents

Include a simple architecture diagram.

## Proposed API Surface Changes
- Extend `GET /rag/library/documents/{document_id}` with optional structured reader payload fields, while preserving existing `clean_text`.
- If needed, add typed response models for:
  - `content_blocks`
  - structured table rows/cells
  - block metadata such as `heading`, `level`, `type`, and `order`
- Do not remove `clean_text` from existing responses.

## Proposed Data Model Changes
- Persist structured reader content at the logical-document level.
- Preserve block ordering deterministically.
- Preserve table payloads in both:
  - retrieval-friendly text form
  - display-friendly structured form
- If a migration is required, it must be explicit and reversible in the normal repo workflow.

## Reingestion And Backfill Expectations
- Newly ingested or re-ingested documents should populate the new structured-content representation.
- Existing documents without structured content should remain readable through fallback rendering.
- If a backfill or re-ingestion is required for best fidelity, the issue should implement the code path and document the expected operator workflow.

## Acceptance Criteria
- [ ] Author Library document rendering no longer relies solely on a single plain `clean_text` blob when structured content is available.
- [ ] The document detail API returns an optional structured-content payload while keeping `clean_text` for backward compatibility.
- [ ] The Author Library reader renders headings, paragraphs, and lists as structured blocks with readable spacing.
- [ ] The Author Library reader renders supported tables as actual table UI, not raw pipe-table Markdown or collapsed plain text.
- [ ] Long tables remain usable with overflow handling where needed.
- [ ] Documents that lack structured content still render through a clear fallback path.
- [ ] Structured parse output is persisted in application data rather than discarded after ingestion.
- [ ] Table content is preserved in both a text-oriented representation for retrieval/auditability and a display-oriented representation for the reader.
- [ ] The default sentence segmentation path for chunking uses spaCy rather than the current regex splitter.
- [ ] Regex sentence splitting is no longer the primary supported segmentation strategy in the normal application environment.
- [ ] Recursive chunking and semantic chunking both use the new sentence segmentation path when sentence boundaries are needed.
- [ ] Tests cover sentence segmentation edge cases such as abbreviations, decimals, transcript Q&A, and wrapped prose.
- [ ] Tests cover structured-content persistence and document detail API serialization.
- [ ] Tests cover reader rendering for prose sections, lists, and tables.
- [ ] Documentation is added or updated with an architecture explanation and diagram for structured parsing, persistence, chunking, and reader rendering.
- [ ] The structured reader model leaves a clear path for passage-anchor deep links and highlight rendering from AI Sage evidence citations.
- [ ] The implementation is verifiable through Makefile commands and curl-verifiable APIs.

## Out Of Scope
- LLM-generated table summaries.
- LLM-based rewriting of source prose for display.
- Full OCR remediation of broken PDFs.
- Internet search or tool-calling changes in AI Sage.
- Changing the retrieval ranking stack beyond the sentence-segmentation dependency needed for chunking quality.

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
- Workflow Status: `blocked`
- Provider/Model: `openai/gpt-5`
- Last Updated: `2026-05-07`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `skip` — `Issue definition only; no product code changes made.`
- `typecheck`: `skip` — `Issue definition only; no product code changes made.`
- `tests`: `skip` — `Issue definition only; no product code changes made.`
- `e2e`: `skip` — `Issue definition only; no product code changes made.`
- `api-smoke`: `skip` — `Issue definition only; no product code changes made.`
- `policy-checks`: `pass` — `Task defines explicit scope, architecture decisions, and acceptance criteria before implementation.`

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- `tasks/issue-162-author-library-structured-rendering-and-spacy-segmentation.md` — reason: created new implementation issue for reader fidelity, table rendering, and sentence segmentation work.

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `<concrete reason>`
- Attempted mitigations:
  - `<mitigation 1>`
  - `<mitigation 2>`
- Suggested human action: `<next action>`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: `Review the issue and approve it for implementation if the scope matches the intended fix.`
- Open questions:
  - `None`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `deterministic_gates`
**Workflow Status**: `waiting_for_human`

## Workflow Snapshot
- latest_outcome: Implemented persisted structured Author Library content blocks, typed reader rendering, and spaCy-first sentence segmentation. The document detail API now returns optional structured reader blocks without dropping `clean_text`, tables are preserved for both retrieval and display, and the full required Makefile verification suite passed.
- next_action: All deterministic gates passed. Review the changes in the working tree, then run `make task-ship TASK=<task_file> THREAD_ID=<thread_id>` to commit, push, and open a PR.
- pipeline_version: `v3`
- provider_model: `copilot/gpt-5.4`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: Persist structured document content and expose it in the document detail API without removing `clean_text`.
- Acceptance criterion: Render Author Library documents from typed content blocks when available, including headings, prose, lists, quotes, and tables.
- Acceptance criterion: Preserve tables in both retrieval/audit form and display form, with horizontal overflow handling for wide tables.
- Acceptance criterion: Use spaCy as the default sentence segmentation path for recursive and semantic chunking, leaving regex only as a fallback.
- Acceptance criterion: Cover sentence segmentation, structured-content persistence/API serialization, and reader rendering with tests.
- Acceptance criterion: Document the updated parser-to-reader architecture, including diagram, re-ingestion expectations, and verification flow.

## Prepare
Checked out `feature/issue-162-author-library-structured-rendering-and-spacy-segmentation` from `main` and ensured task file exists.

## Plan Summary
Persist ordered reader blocks on `rag_documents`, expose them through the library document detail API, render typed blocks in the Author Library with a legacy `clean_text` fallback, and replace regex-first chunk sentence splitting with a deterministic spaCy sentencizer plus regression coverage.

### Architecture Decisions
- Persist structured reader content on `rag_documents.content_blocks_json` while retaining `clean_text` for backward compatibility.
- Normalize parsed sections into ordered content blocks with stable `block_id` values so later citation deep-links can target specific passages.
- Store tables in dual form: `table_markdown` for audit/retrieval fidelity and `table_rows` for display fidelity.
- Use spaCy `blank("en")` with `sentencizer` as the default sentence segmentation path, keeping regex only as a guarded fallback.
- Model headings as explicit blocks with headingless descendant body blocks so fanout/selective ingestion can preserve section bodies under chosen headings.

### Acceptance Criteria
- Persist structured document content and expose it in the document detail API without removing `clean_text`.
- Render Author Library documents from typed content blocks when available, including headings, prose, lists, quotes, and tables.
- Preserve tables in both retrieval/audit form and display form, with horizontal overflow handling for wide tables.
- Use spaCy as the default sentence segmentation path for recursive and semantic chunking, leaving regex only as a fallback.
- Cover sentence segmentation, structured-content persistence/API serialization, and reader rendering with tests.
- Document the updated parser-to-reader architecture, including diagram, re-ingestion expectations, and verification flow.

### Planned Paths
- `api/app`
- `api/tests`
- `api/requirements.txt`
- `web/src`
- `docs`
- `migrations`

## Build Summary
Implemented persisted structured Author Library content blocks, typed reader rendering, and spaCy-first sentence segmentation. The document detail API now returns optional structured reader blocks without dropping `clean_text`, tables are preserved for both retrieval and display, and the full required Makefile verification suite passed.

### Changed Files
- `api/app/models/rag.py`
- `api/app/rag/ingestion/chunker.py`
- `api/app/rag/ingestion/normalization.py`
- `api/app/rag/ingestion/parser.py`
- `api/app/rag/ingestion/pipeline.py`
- `api/app/rag/ingestion/selector.py`
- `api/app/rag/ingestion/structured_content.py`
- `api/app/routers/rag.py`
- `api/requirements.txt`
- `api/tests/test_rag.py`
- `api/tests/test_rag_chunker.py`
- `api/tests/test_rag_discovery.py`
- `api/tests/test_rag_document_library.py`
- `api/tests/test_rag_fanout.py`
- `api/tests/test_rag_parser.py`
- `api/tests/test_selective_ingestion.py`
- `docs/rag-structured-reader-architecture.md`
- `migrations/049_rag_document_content_blocks.sql`
- `tasks/issue-162-author-library-structured-rendering-and-spacy-segmentation.md`
- `web/src/App.css`
- `web/src/__tests__/AuthorLibrary.test.tsx`
- `web/src/lib/api.ts`
- `web/src/routes/AuthorLibrary.tsx`

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
Implemented persisted structured Author Library content blocks, typed reader rendering, and spaCy-first sentence segmentation. The document detail API now returns optional structured reader blocks without dropping `clean_text`, tables are preserved for both retrieval and display, and the full required Makefile verification suite passed.

- semantic_intent_achieved: `True`
- provider_model: `copilot/gpt-5.4`

### Semantic Checks
- `pass` Author Library document rendering no longer relies solely on a single plain `clean_text` blob when structured content is available.: `web/src/routes/AuthorLibrary.tsx` now renders `StructuredDocumentRenderer` when `content_blocks` exist, and `web/src/__tests__/AuthorLibrary.test.tsx` asserts structured rendering on the main document while preserving fallback on the legacy note document.
- `pass` The document detail API returns an optional structured-content payload while keeping `clean_text` for backward compatibility.: `api/app/routers/rag.py` adds `content_blocks` to `LibraryDocumentDetailOut` while still returning `clean_text`; `api/tests/test_rag_document_library.py` asserts both are serialized.
- `pass` The Author Library reader renders headings, paragraphs, and lists as structured blocks with readable spacing.: Typed block rendering and supporting styles were added in `web/src/routes/AuthorLibrary.tsx` and `web/src/App.css`, with list and prose assertions in `web/src/__tests__/AuthorLibrary.test.tsx`.
- `pass` The Author Library reader renders supported tables as actual table UI, not raw pipe-table Markdown or collapsed plain text, and long tables remain usable with overflow handling.: Table blocks now render as HTML tables inside `.authorLibraryTableScroller`; the reader test asserts table cells render, and CSS adds horizontal overflow handling.
- `pass` Documents that lack structured content still render through a clear fallback path.: `AuthorLibrary.tsx` keeps the old `author-library-reader-text` path when `content_blocks` is empty/null; the notes document test exercises that fallback.
- `pass` Structured parse output is persisted in application data rather than discarded after ingestion.: `api/app/models/rag.py` adds `content_blocks_json`, `api/app/rag/ingestion/pipeline.py` persists normalized blocks, and `api/tests/test_rag_fanout.py` asserts persisted `content_blocks_json` values on ingested documents.
- `pass` Table content is preserved in both a text-oriented representation for retrieval/auditability and a display-oriented representation for the reader.: `api/app/rag/ingestion/parser.py` now stores both `table_markdown` and `table_rows`; `api/app/rag/ingestion/structured_content.py` carries both into persisted reader blocks, and API tests assert `table_rows` output.
- `pass` The default sentence segmentation path for chunking uses spaCy rather than the current regex splitter, and recursive plus semantic chunking both use that path when sentence boundaries are needed.: `api/app/rag/ingestion/chunker.py` now builds a spaCy sentencizer and uses it in `_split_sentences()`, which is called by `_recursive_split()` and semantic chunking in `chunk_recursive()`.
- `pass` Tests cover sentence segmentation edge cases such as abbreviations, decimals, transcript Q&A, and wrapped prose.: `api/tests/test_rag_chunker.py` now covers abbreviations, decimals, multiline/wrapped prose, transcript Q&A, and regex fallback behavior.
- `pass` Tests cover structured-content persistence, document detail API serialization, and reader rendering for prose sections, lists, and tables.: Persistence/API assertions were added in `api/tests/test_rag_fanout.py` and `api/tests/test_rag_document_library.py`; reader rendering coverage was added in `web/src/__tests__/AuthorLibrary.test.tsx`.
- `pass` Documentation is added or updated with an architecture explanation and diagram for structured parsing, persistence, chunking, and reader rendering, including re-ingestion expectations.: Added `docs/rag-structured-reader-architecture.md` with as-is/to-be explanation, Mermaid flow diagram, table representation details, spaCy migration notes, verification commands, and re-ingestion guidance.
- `pass` The structured reader model leaves a clear path for passage-anchor deep links and highlight rendering from AI Sage evidence citations, and the implementation is verifiable through Makefile commands and curl-verifiable APIs.: Persisted blocks now include stable `block_id` values and heading-context metadata; verification was completed with `make api-rebuild`, `make contract-backend`, `make test-backend`, `make api-smoke`, `make lint`, `make typecheck`, `make contract-frontend`, `make test-frontend`, `make e2e`, `make orch-test`, and `make web-rebuild`.

### Risk Flags
- legacy-documents-need-reingestion
- complex-pdf-table-normalization-may-fallback

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._
<!-- MACHINE_RENDERED_END -->
