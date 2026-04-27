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
**Current Stage**: `done`
**Workflow Status**: `shipped`

## Workflow Snapshot
- latest_outcome: Pushed branch `feature/issue-154-author-corpus-reader-and-document-library`.
- next_action: No action required.
- pipeline_version: `v3`
- provider_model: `copilot/gpt-5.4`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: User-facing author gallery cards with photo/name/about/link into each corpus.
- Acceptance criterion: Grouped author detail page that lists logical documents by metadata-derived sections and secondary year groupings.
- Acceptance criterion: Dedicated reader route that uses stored logical-document text with metadata header, provenance link, and fullscreen toggle.
- Acceptance criterion: Parent/child related-document navigation from the reading view.
- Acceptance criterion: Mixed-author and non-fanout fallback behavior preserved through effective-author and document-first backend logic.
- Acceptance criterion: Backend APIs remain curl-verifiable and OpenAPI-compatible via optional response-field additions.
- Acceptance criterion: Frontend and backend tests cover gallery rendering, grouping, metadata rendering, reading, fullscreen, and related-document fallback.
- Acceptance criterion: Feature verified through the required Makefile lifecycle and test commands.

## Prepare
Checked out `feature/issue-154-author-corpus-reader-and-document-library` from `main` and ensured task file exists.

## Plan Summary
Extend the existing RAG library APIs with author-gallery metadata, reshape the frontend into routed gallery/library/reader screens without breaking document-first behavior, update focused backend/frontend tests for the new UX and fallback paths, then run the full Makefile verification suite end-to-end.

### Architecture Decisions
- Kept the backend document-first by continuing to prefer rag_documents and logical-document detail endpoints rather than source blobs.
- Extended author library responses with optional gallery metadata (photo_url, about_text) instead of introducing a new persistence model or breaking existing contracts.
- Used metadata-driven grouping from the existing backend grouping logic so current and future authors share the same grouping behavior.
- Restructured the frontend into three routes: /author-library, /author-library/:authorId, and /author-library/:authorId/documents/:documentId.
- Implemented fullscreen as a reader-surface capability in the dedicated document view while preserving provenance links and parent/child navigation.

### Acceptance Criteria
- User-facing author gallery cards with photo/name/about/link into each corpus.
- Grouped author detail page that lists logical documents by metadata-derived sections and secondary year groupings.
- Dedicated reader route that uses stored logical-document text with metadata header, provenance link, and fullscreen toggle.
- Parent/child related-document navigation from the reading view.
- Mixed-author and non-fanout fallback behavior preserved through effective-author and document-first backend logic.
- Backend APIs remain curl-verifiable and OpenAPI-compatible via optional response-field additions.
- Frontend and backend tests cover gallery rendering, grouping, metadata rendering, reading, fullscreen, and related-document fallback.
- Feature verified through the required Makefile lifecycle and test commands.

### Planned Paths
- `api/app/routers/rag.py`
- `api/tests/test_rag_document_library.py`
- `web/src/routes/AuthorLibrary.tsx`
- `web/src/__tests__/AuthorLibrary.test.tsx`
- `web/src/lib/api.ts`
- `web/src/main.tsx`
- `web/src/App.css`

## Build Summary
Implemented a document-first author corpus reader with a routed three-screen flow: author gallery, grouped author library, and dedicated reading view with fullscreen and related-document navigation. Extended the backend library author payload with reader-friendly gallery metadata and updated backend/frontend tests to cover gallery rendering, grouping, metadata display, document reading, fullscreen mode, and parent/child fallback behavior.

### Changed Files
- `api/app/routers/rag.py`
- `api/tests/test_rag_document_library.py`
- `tasks/issue-154-author-corpus-reader-and-document-library.md`
- `web/src/App.css`
- `web/src/__tests__/AuthorLibrary.test.tsx`
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
Implemented a document-first author corpus reader with a routed three-screen flow: author gallery, grouped author library, and dedicated reading view with fullscreen and related-document navigation. Extended the backend library author payload with reader-friendly gallery metadata and updated backend/frontend tests to cover gallery rendering, grouping, metadata display, document reading, fullscreen mode, and parent/child fallback behavior.

- semantic_intent_achieved: `True`
- provider_model: `copilot/gpt-5.4`

### Semantic Checks
- `pass` Author gallery UI shows metadata-rich cards and links into each corpus.: AuthorLibrary now renders /author-library as a gallery of cards with photo/initials, author name, about text, corpus stats, and browse links; covered by web/src/__tests__/AuthorLibrary.test.tsx gallery assertions.
- `pass` Author detail page exposes grouped child links instead of a flat table and uses metadata-driven grouping.: The /author-library/:authorId route renders grouped sections and secondary publication-year groupings from backend metadata, with document cards linking into the reader; covered by backend grouping assertions and frontend library-page test assertions.
- `pass` Individual logical documents open in a dedicated reading view using stored logical-document text with metadata, provenance, and fullscreen.: The /author-library/:authorId/documents/:documentId route renders clean_text, metadata chips, provenance link, and fullscreen toggle; covered by web/src/__tests__/AuthorLibrary.test.tsx reader/fullscreen assertions.
- `pass` Parent-child related documents are surfaced and navigable, while existing fallback behavior remains intact.: Backend document detail continues to expose parent_document and child_documents; frontend reader links those documents back into the reader route; backend tests still verify mixed-author and legacy single-document fallback behavior.
- `pass` Backend exposes needed read APIs while staying OpenAPI-compatible.: No endpoints were removed; existing /rag/library/authors, /rag/library/authors/{author_id}, and /rag/library/documents/{document_id} remain intact with optional response-field additions only.
- `pass` Feature is verifiable through repository Makefile commands and automated tests.: The full required Makefile suite passed: api-rebuild, contract-backend, test-backend, api-smoke, lint, typecheck, contract-frontend, test-frontend, e2e, and orch-test.

### Risk Flags
- pre-existing-task-file-dirty-worktree

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Ship Result
Pushed branch `feature/issue-154-author-corpus-reader-and-document-library`.
<!-- MACHINE_RENDERED_END -->
