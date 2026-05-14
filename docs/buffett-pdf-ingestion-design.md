# Buffett PDF Ingestion Design

## Current Corpus Finding

Warren Buffett's current PDF corpus in CapitalOS is text-bearing and should be treated as digital PDF, not scanned image PDF.

The current live Buffett PDF sources are:

- 2000
- 2002-2024
- 2005

There is no current Buffett PDF source in the database that behaves like a pure scanned image document.

### Evidence

A first-pass classification was run against every Buffett PDF source by fetching the live PDF and extracting text from the first pages with `pdfminer`.

Observed result:

- `digital`: 2019, 2023, 2024
- `likely_digital_low_text`: 2000, 2002-2018, 2020-2022, 2005
- `scan_or_ocr_heavy`: none
- `unreadable`: none

`likely_digital_low_text` here does not mean "scanned". It means text is embedded, but the current extraction is fragmented by layout, narrow line widths, or table geometry. Char counts were still high on the sampled pages, which is the key signal that these PDFs have an embedded text layer.

Conclusion: Buffett PDFs should materially improve with a dedicated digital-PDF table extraction path.

## Problem Statement

The current ingestion stack is correct at the top-level source-type dispatch, but PDF behavior is still weak because the PDF path is text-first rather than layout-first.

Current state in [parser.py](../api/app/rag/ingestion/parser.py):

- HTML and PDF are dispatched separately by `source_type`
- HTML now has DOM-aware recovery logic
- PDF still depends on generic extraction followed by downstream normalization

This is the wrong architecture for high-fidelity financial tables because table structure is frequently lost before normalization runs.

## Non-Negotiable Branching Rule

HTML and PDF must be isolated implementation branches.

Required rule:

- HTML extraction changes must not modify PDF extraction behavior
- PDF extraction changes must not modify HTML extraction behavior
- Shared code should only handle transport-neutral tasks: fetch, source detection, metadata plumbing, persistence contracts, validation contracts
- Source-specific logic must live in source-specific modules

## Proposed Branch Structure

Keep [parser.py](../api/app/rag/ingestion/parser.py) as the thin dispatcher only.

Target structure:

- `api/app/rag/ingestion/parser.py`
  - dispatch only
- `api/app/rag/ingestion/html_parser.py`
  - HTML DOM extraction
  - wrapper-page handling
  - sanitized HTML block preservation
  - HTML table extraction
- `api/app/rag/ingestion/pdf_classifier.py`
  - detect `digital_text`, `ocr_heavy`, `mixed`, `unknown`
- `api/app/rag/ingestion/pdf_digital_parser.py`
  - coordinate-aware text extraction
  - table region detection
  - row/column reconstruction
  - multi-row header reconstruction
  - continuation / note linking
- `api/app/rag/ingestion/pdf_ocr_parser.py`
  - OCR pipeline
  - image/layout reconstruction
  - lower-confidence fallback behavior
- `api/app/rag/ingestion/parser_types.py`
  - shared data contracts only

This split is the main mechanism that prevents HTML fixes from regressing PDF behavior and vice versa.

## Proposed PDF Pipeline

### Step 1: PDF Classification

Input: raw PDF bytes

Output:

- `digital_text`
- `ocr_heavy`
- `mixed`
- `unknown`

Signals:

- embedded text presence per page
- extractable word count per page
- ratio of image area to text area
- glyph coverage consistency
- OCR confidence, if OCR is run

For Buffett, the expected route is overwhelmingly `digital_text`.

### Step 2: Digital PDF Extraction

This is the primary Buffett path.

Recommended implementation shape:

1. Extract words with coordinates
2. Build page-level layout blocks
3. Detect table regions
4. Reconstruct row and column boundaries
5. Detect merged cells
6. Distinguish header rows from body rows
7. Separate notes / footnotes from body rows
8. Link multi-page continuation tables when captions or schemas match
9. Emit:
   - structured table JSON
   - faithful table HTML
   - confidence score

Recommended libraries to evaluate:

- `PyMuPDF` for page geometry and text boxes
- `pdfplumber` for table debugging and layout inspection
- existing `pdfminer.six` only as fallback text extraction, not the main table engine

Avoid treating `camelot` or `tabula` as the primary strategy for Buffett.
They work best on ruled tables and are not enough for many Berkshire-style borderless tables.

### Step 3: OCR / Image PDF Extraction

This is not the primary Buffett need, but should exist as a separate branch.

Pipeline:

1. Rasterize page
2. OCR words with coordinates
3. Detect table region from image and OCR geometry
4. Infer grid / merged cells
5. Emit low-confidence structured table only if quality threshold is met

If confidence is low, do not pretend the table is correct.

Fallback should be source-first or page-image-first, not fake structure.

## Table Reconstruction Rules

Digital PDF parser should operate with explicit invariants:

- A table row is a horizontal alignment band, not just a newline-delimited text segment
- A header row is detected from position, repetition, typography, and semantic content, not from bold alone
- A table note is a footer-like row or adjacent text block with lower width coverage, note markers, or unit labels
- A continuation table should inherit caption and schema only when column structure materially matches

## Confidence Expectations

For the Buffett PDF corpus specifically, expected confidence if the digital path is built properly:

- clean single-page tables: high, about 90%
- multi-row financial headers with note rows: medium-high, about 80-90%
- multi-page, borderless, prose-adjacent tables: medium, about 70-85%

Overall Buffett expectation:

- materially better than the current heuristic path
- likely good enough for most digital tables
- not guaranteed lossless on every page

This is materially better than the current architecture because the current architecture loses geometry too early.

## Why This Was Not Built Earlier

The current ingestion system was initially optimized for broad corpus coverage rather than high-fidelity table reconstruction.

That was a rational first phase because it allowed:

- one ingestion pipeline for HTML, PDF, and manual text
- quick chunking and embedding support
- broad content coverage without document-specific geometry work

What it did not provide was a strong PDF table engine.

A proper PDF path was deferred because it requires:

- coordinate-aware extraction
- separate digital and OCR branches
- confidence scoring
- page-level table validation
- a larger regression corpus

In other words, it was a prioritization tradeoff, not a hidden impossibility.

## Implementation Plan

### Phase 1: Isolate the Branches

1. Move HTML parser logic into `html_parser.py`
2. Move current PDF logic into `pdf_digital_parser.py` and `pdf_classifier.py`
3. Leave `parser.py` as dispatch-only
4. Add branch-specific test files:
   - `test_html_parser.py`
   - `test_pdf_digital_parser.py`
   - `test_pdf_classifier.py`

Acceptance:

- HTML tests do not import PDF parsing internals
- PDF tests do not import HTML parsing internals

### Phase 2: Build the Digital PDF Table Path

1. Add word-box extraction
2. Add table region detector
3. Add row/column reconstruction
4. Add header/footer/note classification
5. Emit structured tables and faithful HTML

Acceptance:

- Buffett 2006, 2007, 2015, 2016, and a later clean year all improve without table-specific repair rules

### Phase 3: Confidence and Fallback

1. Add table confidence scoring
2. Mark low-confidence tables as degraded
3. Prefer source-first / PDF-viewer-first when confidence is below threshold

Acceptance:

- low-confidence tables are not rendered as if they are trustworthy

### Phase 4: OCR Branch

1. Add OCR-specific classification
2. Add OCR table reconstruction
3. Only enable for sources classified `ocr_heavy` or `mixed`

## Validation Plan

### Unit Validation

- parser classification tests for digital vs OCR-heavy PDFs
- structured table reconstruction tests for multi-row headers and note rows
- continuation-table tests across pages

### Corpus Validation

Use Buffett as the first benchmark corpus.

Suggested benchmark years:

- 2006
- 2007
- 2015
- 2016
- 2019
- 2023

### Runtime Validation

After backend changes:

1. `make api-rebuild`
2. `curl http://localhost:8000/health`
3. authenticated `curl http://localhost:8000/dashboard/summary?month=YYYY-MM`
4. reingest benchmark Buffett PDF sources
5. inspect stored table blocks and rendered reader output

## Recommended Next Move

Build only the digital PDF branch first.

Reason:

- Buffett PDFs are text-bearing digital documents
- this is the shortest path to materially improving the corpus
- OCR work adds complexity without addressing the current Buffett bottleneck

If Phase 2 is successful, then the OCR branch can be added later without changing the HTML path or the digital PDF path.