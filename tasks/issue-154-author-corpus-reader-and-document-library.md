# Issue 154: Author corpus reader and document library

## Objective
- Provide a readable, metadata-rich library view of ingested author content so users can browse an author’s corpus directly inside CapitalOS.
- Make the corpus usable as a reading surface, not just a retrieval backend.
- Let users inspect canonical works, metadata, source provenance, and logical-document boundaries without dealing with one giant blob of text.

## Architecture Decisions
- Decision 1: Build an author-centric corpus reader that lists logical documents for a chosen author with metadata and readable content.
- Decision 2: Use the richer logical-document model from issue 152 when available, but degrade gracefully for existing pre-fanout documents.
- Decision 3: Treat this as a read/view surface, not an editing workflow; ingestion authoring remains in the ingestion area.
- Decision 4: The reader should prefer logical-document boundaries and metadata over raw-source blobs.
- Decision 5: Preserve provenance by surfacing source URL, source type, publisher/venue metadata, date/year, collection, canonical status, and related context.
- Decision 6: Parent-child linkage should be used when available so companion/editorial documents can be navigated from the main work.
- Decision 7: The UI should live in a user-facing Intelligence area and use end-user language, not backend jargon.

## Acceptance Criteria
- [ ] There is a user-facing UI where a user can choose an author and browse that author’s ingested corpus.
- [ ] The UI lists logical documents rather than rendering one giant source blob by default.
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
- [ ] Parent-child related documents can be surfaced or linked when available.
- [ ] The UI supports mixed-author corpora correctly; author overrides from fanout documents appear under the correct author.
- [ ] Existing non-fanout documents still appear in the library in a reasonable fallback form.
- [ ] The backend exposes any additional read APIs needed to support the reader/library.
- [ ] The reader is compatible with current metadata and with future richer corpus metadata.
- [ ] Tests cover author listing, document listing, metadata rendering, document reading, and parent-child navigation/fallback behavior.
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
  - `Should the first version prioritize a list/detail reader or also include search/filtering within one author corpus?`
  - `Should raw source audit text be visible anywhere in the reader, or remain backend-only?`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._
