# Issue 154: Author corpus reader and document library

## Objective
- Provide a readable, metadata-rich library view of ingested author content so users can browse an author’s corpus directly inside CapitalOS.
- Make the corpus usable as a reading surface, not just a retrieval backend.
- Let users inspect canonical works, metadata, source provenance, and logical-document boundaries without dealing with one giant blob of text.

## Architecture Decisions
- Decision 1: Build an author-centric corpus reader that lists logical documents for a chosen author with metadata and readable content.
- Decision 2: Use the richer logical-document model from issue 152 when available, but degrade gracefully for existing pre-fanout documents.
- Decision 3: Treat this as a read/view surface, not an editing workflow; ingestion authoring remains in the ingestion area.
- Decision 4: The reader must be document-first. It should prefer `rag_documents` and logical-document boundaries over raw-source blobs or source-level fallback rendering.
- Decision 5: Preserve provenance by surfacing source URL, source type, publisher/venue metadata, date/year, collection, canonical status, and related context.
- Decision 6: Parent-child linkage should be used when available so companion/editorial documents can be navigated from the main work.
- Decision 7: The UI should live in a user-facing Intelligence area and use end-user language, not backend jargon.
- Decision 8: The reader should support generic hierarchical grouping so future authors can be browsed by collection, corpus section, work class, year, or similar metadata-derived groupings instead of a single flat list.
- Decision 9: Grouping behavior must be metadata-driven and generic. It must not hardcode special-case UI logic for only the currently ingested authors.
- Decision 10: The first screen should be an author gallery using cards with author photo, name, short biography/about text, and a link into that author’s corpus.
- Decision 11: The second screen should be an author detail/library page with grouped child links rather than a flat metadata table.
- Decision 12: The third screen should be a dedicated reading view for one logical document with a large reading surface, a metadata header, provenance link(s), and a fullscreen option.
- Decision 13: Generic grouping should support patterns like:
- Decision 13a: letters grouped by year
- Decision 13b: talks/speeches grouped by work
- Decision 13c: meeting notes grouped into their own section and then by year
- Decision 13d: interviews/conversations grouped as their own section
- Decision 14: Corpus remediation is out of scope for this issue. If an author is still represented by a bad omnibus or other poor ingestion shape, the library should display the best available document structure honestly while remediation happens in a separate ingestion issue.

## Acceptance Criteria
- [ ] There is a user-facing author gallery UI where a user can see available authors as cards and choose an author to browse.
- [ ] Each author card shows, when available:
- [ ] author photo
- [ ] author name
- [ ] short biography/about text
- [ ] link into the author’s corpus
- [ ] The UI lists logical documents rather than rendering one giant source blob by default.
- [ ] The UI supports generic grouping/segregation of documents using available metadata rather than only a flat per-author list.
- [ ] The reader can organize an author corpus into higher-level sections such as collections, corpus sections, work classes, or similar metadata-derived groupings when those fields are present.
- [ ] The reader supports secondary grouping such as by year/date when that grouping makes sense for a section or collection.
- [ ] Grouping behavior works for current authors and future authors without requiring author-specific code paths.
- [ ] The author detail page exposes grouped child links rather than forcing users through a flat table-like browsing experience.
- [ ] Grouping supports library shapes such as:
- [ ] letters segregated by year
- [ ] talks/speeches segregated as individual works
- [ ] meeting notes segregated into their own section and then by year
- [ ] interviews/conversations segregated into their own section
- [ ] Each listed document shows key metadata when available, including:
- [ ] title
- [ ] author
- [ ] year/date
- [ ] venue
- [ ] collection
- [ ] canonical status
- [ ] source type
- [ ] source URL or provenance link
- [ ] work type
- [ ] The UI allows the user to open and read an individual logical document cleanly.
- [ ] The reading view uses stored logical-document text, not the full raw source blob by default.
- [ ] The reading view occupies most of the page except the main application navigation and supports a fullscreen reading mode.
- [ ] The reading view presents metadata and provenance in a reader-friendly header rather than burying them in a raw JSON-style layout.
- [ ] Parent-child related documents can be surfaced or linked when available.
- [ ] The UI supports mixed-author corpora correctly; author overrides from fanout documents appear under the correct author.
- [ ] Existing non-fanout documents still appear in the library in a reasonable fallback form.
- [ ] Existing poor-ingestion corpora do not force raw source blobs when better logical documents exist; document-first rendering is used wherever document rows are available.
- [ ] The backend exposes any additional read APIs needed to support the reader/library.
- [ ] The reader is compatible with current metadata and with future richer corpus metadata.
- [ ] Tests cover author gallery rendering, document grouping, metadata rendering, document reading, fullscreen mode, and parent-child navigation/fallback behavior.
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
- Current Stage: `verified`
- Workflow Status: `completed`
- Provider/Model: `openai/gpt-5`
- Last Updated: `2026-04-25`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `pass` — `make lint`
- `typecheck`: `pass` — `make typecheck`
- `tests`: `pass` — `make contract-backend && make test-backend && make contract-frontend && make test-frontend && make orch-test`
- `e2e`: `pass` — `make e2e`
- `api-smoke`: `pass` — `make api-smoke`
- `policy-checks`: `pass` — `openapi-compatible router additions with user-scoped read APIs`

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- `tasks/issue-154-author-corpus-reader-and-document-library.md` — reason: updated execution journal and deterministic gate results for this task

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `<concrete reason>`
- Attempted mitigations:
  - `<mitigation 1>`
  - `<mitigation 2>`
- Suggested human action: `<next action>`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: `Review the working tree and ship if acceptable`
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
- latest_outcome: Implemented an end-user Author Library for browsing and reading ingested author corpora, added read-only corpus APIs with metadata-driven grouping and logical-document detail, kept ingestion authoring separate, and covered the flow with backend, frontend, and end-to-end verification.
- next_action: All deterministic gates passed. Review the changes in the working tree, then run `make task-ship TASK=<task_file> THREAD_ID=<thread_id>` to commit, push, and open a PR.
- pipeline_version: `v3`
- provider_model: `copilot/gpt-5.4`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: User-facing Author Library route added under Intelligence with author selection and corpus browsing.
- Acceptance criterion: Library lists logical documents and groups them generically by metadata, with secondary year grouping when available.
- Acceptance criterion: Document list items render key metadata including author, date/year, venue, collection, canonical status, source type, source URL, and work type.
- Acceptance criterion: Reader detail view loads stored logical-document text and provenance, not full raw source blobs by default.
- Acceptance criterion: Parent/child related documents are linked from the reading view.
- Acceptance criterion: Mixed-author fanout documents browse under their effective author, and legacy non-fanout documents still appear via fallback attribution.
- Acceptance criterion: Backend read APIs added for library authors, grouped author corpus listing, and document detail.
- Acceptance criterion: Backend, frontend, Playwright, and Makefile verification all passed.

## Prepare
Checked out `feature/issue-154-author-corpus-reader-and-document-library` from `main` and ensured task file exists.

## Plan Summary
Add user-facing corpus reader APIs and UI, group documents generically from metadata with logical-document detail and provenance, cover mixed-author and fallback behavior in tests, and verify through the full Makefile suite.

### Architecture Decisions
- Added a separate Author Library reader surface in the Intelligence area instead of extending the ingestion authoring page.
- Built library author attribution on the effective author identity `coalesce(rag_documents.author_id, rag_sources.author_id)` so fanout author overrides browse under the correct author.
- Kept grouping metadata-driven and generic by deriving primary groups from standard corpus fields plus scalar document metadata, with year/date as secondary grouping when meaningful.
- Used stored logical-document `clean_text` for the reading view and surfaced provenance from the source record rather than defaulting to raw source blobs.
- Surfaced parent/child document relationships in the detail API and reader without changing the existing ingestion persistence model.

### Acceptance Criteria
- User-facing Author Library route added under Intelligence with author selection and corpus browsing.
- Library lists logical documents and groups them generically by metadata, with secondary year grouping when available.
- Document list items render key metadata including author, date/year, venue, collection, canonical status, source type, source URL, and work type.
- Reader detail view loads stored logical-document text and provenance, not full raw source blobs by default.
- Parent/child related documents are linked from the reading view.
- Mixed-author fanout documents browse under their effective author, and legacy non-fanout documents still appear via fallback attribution.
- Backend read APIs added for library authors, grouped author corpus listing, and document detail.
- Backend, frontend, Playwright, and Makefile verification all passed.

### Planned Paths
- `api/app/routers/rag.py`
- `api/tests`
- `web/src/routes`
- `web/src/lib/api.ts`
- `web/src/components/Sidebar.tsx`
- `web/src/__tests__`
- `web/src/App.css`

## Build Summary
Implemented an end-user Author Library for browsing and reading ingested author corpora, added read-only corpus APIs with metadata-driven grouping and logical-document detail, kept ingestion authoring separate, and covered the flow with backend, frontend, and end-to-end verification.

### Changed Files
- `api/app/routers/rag.py`
- `api/tests/test_rag_document_library.py`
- `tasks/issue-154-author-corpus-reader-and-document-library.md`
- `web/src/App.css`
- `web/src/__tests__/AuthorLibrary.test.tsx`
- `web/src/__tests__/Sidebar.test.tsx`
- `web/src/__tests__/contracts.test.tsx`
- `web/src/components/Sidebar.tsx`
- `web/src/lib/api.ts`
- `web/src/main.tsx`
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
Implemented an end-user Author Library for browsing and reading ingested author corpora, added read-only corpus APIs with metadata-driven grouping and logical-document detail, kept ingestion authoring separate, and covered the flow with backend, frontend, and end-to-end verification.

- semantic_intent_achieved: `True`
- provider_model: `copilot/gpt-5.4`

### Semantic Checks
- `pass` There is a user-facing UI where a user can choose an author and browse that author’s ingested corpus.: Added `web/src/routes/AuthorLibrary.tsx`, routed it in `web/src/main.tsx`, and exposed it in the Intelligence nav via `web/src/components/Sidebar.tsx`; covered by `web/src/__tests__/AuthorLibrary.test.tsx`.
- `pass` The UI lists logical documents rather than rendering one giant source blob by default, and supports generic grouping plus secondary year/date grouping.: Server-side grouping and document summaries were added in `api/app/routers/rag.py`, and the UI renders grouped sections and year buckets in `web/src/routes/AuthorLibrary.tsx`; backend grouping behavior is covered by `api/tests/test_rag_document_library.py`.
- `pass` Each listed document shows key metadata when available including title, author, year/date, venue, collection, canonical status, source type, source URL, and work type.: Document summary payloads include those fields in `api/app/routers/rag.py`, and they are rendered as metadata chips in `web/src/routes/AuthorLibrary.tsx`; verified by `web/src/__tests__/AuthorLibrary.test.tsx`.
- `pass` The UI allows the user to open and read an individual logical document cleanly using stored logical-document text rather than raw source blobs.: The detail endpoint `/rag/library/documents/{document_id}` returns `clean_text`, and the reader panel in `web/src/routes/AuthorLibrary.tsx` renders that field; covered by `api/tests/test_rag_document_library.py` and `web/src/__tests__/AuthorLibrary.test.tsx`.
- `pass` Parent-child related documents can be surfaced or linked when available.: Parent and child document relations are included in the detail response from `api/app/routers/rag.py` and rendered as related-document buttons in `web/src/routes/AuthorLibrary.tsx`; covered by `api/tests/test_rag_document_library.py`.
- `pass` The UI supports mixed-author corpora correctly and existing non-fanout documents still appear in a reasonable fallback form.: Library author and document queries use effective author attribution in `api/app/routers/rag.py`; mixed-author and fallback coverage is in `api/tests/test_rag_document_library.py`.
- `pass` The backend exposes any additional read APIs needed to support the reader/library and remains curl-verifiable.: Added `/rag/library/authors`, `/rag/library/authors/{author_id}`, and `/rag/library/documents/{document_id}` in `api/app/routers/rag.py`; curl verification against the running app returned a non-empty author list from `/rag/library/authors`.
- `pass` Tests cover author listing, document listing, metadata rendering, document reading, and parent-child navigation or fallback behavior.: Added `api/tests/test_rag_document_library.py` and `web/src/__tests__/AuthorLibrary.test.tsx`, plus updated nav contract tests in `web/src/__tests__/Sidebar.test.tsx` and `web/src/__tests__/contracts.test.tsx`.
- `pass` The feature is verifiable via Makefile commands and curl-verifiable APIs.: Completed `make api-rebuild`, `make contract-backend`, `make test-backend`, `make api-smoke`, `make lint`, `make typecheck`, `make contract-frontend`, `make test-frontend`, `make e2e`, and `make orch-test`, and verified `/rag/library/authors` via authenticated curl.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._
<!-- MACHINE_RENDERED_END -->
