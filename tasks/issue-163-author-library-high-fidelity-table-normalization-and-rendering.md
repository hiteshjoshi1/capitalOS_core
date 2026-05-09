# Issue 163: Author Library high-fidelity table normalization and rendering

## Objective
- Fix the remaining table-fidelity problems in Author Library for complex source documents such as Warren Buffett annual letters.
- Preserve richer table structure during ingestion so row groups, multi-row headers, footnotes, and merged-cell semantics are not flattened into lossy `string[][]` rows.
- Render complex financial tables in the reader as trustworthy structured artifacts rather than degraded approximations.

## Problem Statement

### What is still wrong after Issue 162

Issue 162 made the reader materially better, but complex tables still look poor in real corpus documents.

Current limitations:

1. Table extraction is still too lossy.
   - The parser currently reduces tables to text rows with `table_rows: string[][]`.
   - This discards `rowspan`, `colspan`, multi-row headers, captions, subheaders, and footnotes.

2. The current reader table model is too naive.
   - The frontend assumes the first row is the header.
   - That works for simple tables, but fails for annual-letter and report-style tables with grouped headings.

3. Markdown fallback is still too weak for complex tables.
   - Pipe-table markdown is acceptable for auditability, but not sufficient as the main source of truth for rich table rendering.

4. Existing stored documents are already degraded.
   - Even with a better reader, old persisted `content_blocks_json` payloads will not improve unless the parser and persistence model improve and affected documents are re-ingested.

### Why this matters

1. Users cannot reliably inspect financial tables in source documents.
2. Degraded tables weaken trust in the Author Library as a research surface.
3. AI Sage evidence is less useful if the underlying source tables are visually unreliable.
4. The current representation limits future citation/deep-link work because table sections do not retain enough stable structural identity.

## Architecture Decisions
- Decision 1: `table_rows: string[][]` is not sufficient as the primary structured representation for complex tables.
- Decision 2: The system must preserve richer per-cell structure including text, row span, column span, and header/body role when available.
- Decision 3: Raw `table_markdown` may remain for auditability and retrieval lineage, but it must not be the only fallback for rich tables.
- Decision 4: Original parse-time table HTML should be preserved in a sanitized/storable form when available, so normalization can be retried or rendered more faithfully.
- Decision 5: The reader must distinguish `caption`, `header_rows`, `body_rows`, and optional `footer_rows` instead of inferring table semantics from the first row.
- Decision 6: Re-ingestion is an expected part of this issue for documents whose stored table payloads were already flattened.
- Decision 7: This issue is about deterministic structure preservation and rendering, not LLM summarization or rewriting.

## Current State Summary
- `api/app/rag/ingestion/parser.py` currently extracts:
  - `table_markdown`
  - `table_rows: list[list[str]]`
- `api/app/rag/ingestion/structured_content.py` persists those values into `content_blocks_json`.
- `web/src/routes/AuthorLibrary.tsx` renders tables by:
  - treating the first row as the header when there is more than one row
  - rendering the remainder as body rows
- This works for simple HTML tables but breaks down for real Buffett-style annual-letter tables and similar documents.

## Proposed Technical Design

### 1. Introduce a richer persisted table model

Extend table blocks in `content_blocks_json` so they can preserve a richer structure such as:

```json
{
  "block_id": "blk-0007",
  "type": "table",
  "order": 7,
  "text": null,
  "table_markdown": "| ... |",
  "table_html": "<table>...</table>",
  "table": {
    "caption": "Insurance underwriting results",
    "header_rows": [
      [
        { "text": "Year", "colspan": 1, "rowspan": 2, "is_header": true },
        { "text": "Premiums", "colspan": 2, "rowspan": 1, "is_header": true }
      ],
      [
        { "text": "Gross", "colspan": 1, "rowspan": 1, "is_header": true },
        { "text": "Net", "colspan": 1, "rowspan": 1, "is_header": true }
      ]
    ],
    "body_rows": [
      [
        { "text": "1991", "colspan": 1, "rowspan": 1, "is_header": false },
        { "text": "123", "colspan": 1, "rowspan": 1, "is_header": false },
        { "text": "110", "colspan": 1, "rowspan": 1, "is_header": false }
      ]
    ],
    "footer_rows": [],
    "notes": ["Amounts in millions"]
  },
  "metadata": {}
}
```

Minimum preserved cell fields:
- `text`
- `rowspan`
- `colspan`
- `is_header`

### 2. Preserve original table HTML when available

When the parser has access to table HTML:
- persist a sanitized `table_html` representation
- use it as a recovery/fallback source for future normalization improvements
- do not rely solely on markdown reconstruction

This is especially important for:
- `unstructured` PDF table HTML
- HTML source documents with complex `<thead>` / `<tbody>` structures

### 3. Improve parser normalization

Upgrade table extraction helpers in `api/app/rag/ingestion/parser.py` to:
- preserve `<thead>`, `<tbody>`, and `<tfoot>` when available
- preserve `rowspan` and `colspan`
- capture captions and nearby notes where feasible
- retain section ordering relative to surrounding prose

Required behavior:
- simple tables still normalize cleanly
- complex tables degrade gracefully rather than collapsing into misleading rows

### 4. Update persisted structured-content builder

Update `api/app/rag/ingestion/structured_content.py` so table blocks store:
- audit/retrieval payload:
  - `table_markdown`
- recovery payload:
  - `table_html`
- display payload:
  - normalized rich table object with header/body/footer rows

### 5. Render rich tables in Author Library

Update `web/src/routes/AuthorLibrary.tsx` so the reader:
- renders explicit `header_rows`
- renders `body_rows` without guessing header structure
- supports multi-row headers
- respects `rowspan` / `colspan`
- renders captions and notes where present
- keeps horizontal overflow handling for wide financial tables

Fallback order should be:
1. rich structured table object
2. sanitized table HTML when safe and normalization is incomplete
3. markdown/text fallback

### 6. Re-ingestion and backfill

This issue should include a documented operator workflow for re-ingesting affected authors/documents, starting with Warren Buffett.

Required outcomes:
- newly ingested documents use the improved table model
- existing documents can be re-ingested to populate the richer structure
- fallback remains available for old documents not yet re-ingested

## Proposed API Surface Changes
- Extend `LibraryContentBlockOut` for table blocks to include richer optional fields such as:
  - `table_html`
  - `table`
  - `caption`
  - `notes`
- Keep existing `table_markdown` and `table_rows` fields if needed for backward compatibility.
- Do not remove `clean_text` or existing structured reader fields without an explicit migration plan.

## Proposed Data Model Changes
- Evolve `rag_documents.content_blocks_json` table-block payloads to support rich table structure.
- Preserve enough fidelity to rebuild the rendered table without inferring semantics from flattened rows alone.
- Keep deterministic ordering and stable block IDs.

## Acceptance Criteria
- [ ] Complex Author Library tables no longer rely only on flattened `string[][]` rows for display.
- [ ] Table blocks persist a richer representation that can preserve header/body structure plus row/column spans when available.
- [ ] Original parse-time table HTML is preserved in a sanitized/storable form when available.
- [ ] The reader renders multi-row headers correctly when the source structure exists.
- [ ] The reader respects `rowspan` and `colspan` where captured.
- [ ] Captions and table notes render when present.
- [ ] Wide tables remain horizontally scrollable without destroying column alignment.
- [ ] Markdown/text fallback remains available for tables that still cannot be normalized cleanly.
- [ ] Re-ingesting an affected Warren Buffett document materially improves its table rendering.
- [ ] Tests cover simple tables, grouped-header tables, and degraded/fallback cases.
- [ ] Documentation explains the richer table model, fallback order, and re-ingestion workflow.
- [ ] The change is verifiable through Makefile commands and curl-verifiable APIs.

## Out Of Scope
- LLM-generated table summaries.
- OCR-specific remediation for scanned PDFs that fail before table extraction.
- General prose reader changes already shipped in Issue 162.
- AI Sage citation deep-link/highlight behavior outside table structure improvements.

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
- Last Updated: `2026-05-08`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `skip` — `Issue definition only; no product code changes made.`
- `typecheck`: `skip` — `Issue definition only; no product code changes made.`
- `tests`: `skip` — `Issue definition only; no product code changes made.`
- `e2e`: `skip` — `Issue definition only; no product code changes made.`
- `api-smoke`: `skip` — `Issue definition only; no product code changes made.`
- `policy-checks`: `pass` — `Task defines explicit scope for high-fidelity table preservation and rendering.`

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- `tasks/issue-163-author-library-high-fidelity-table-normalization-and-rendering.md` — reason: created follow-up implementation issue for complex table preservation and rendering.

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `<concrete reason>`
- Attempted mitigations:
  - `<mitigation 1>`
  - `<mitigation 2>`
- Suggested human action: `<next action>`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: `Review the issue and approve it for implementation if the scope matches the intended table-fidelity work.`
- Open questions:
  - `None`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._
