# Issue 164: PDF parser policy — Unstructured-first and regression gates

## Objective
- Make the production PDF parsing policy explicit: use Unstructured first for PDFs in normal operation.
- Keep `pdfminer` only as a defensive fallback, not as the intended steady-state parser for corpus ingestion.
- Add parser-path observability and retrieval regression gates so parser changes cannot silently degrade corpus quality.

## Current State
- The code already prefers Unstructured for PDFs when it is installed and `RAG_PARSER_BACKEND != pdfminer`.
- The API image already includes `unstructured[pdf]`.
- The parser can still be forced to `pdfminer` via env, and Unstructured failures silently fall through to `pdfminer`.

## Problem
- The effective parser policy is implicit, not operationally clear.
- Silent fallback makes it hard to know when the corpus was ingested with the intended parser versus a degraded parser.
- A parser-path change can improve rendering while making retrieval worse if not measured on representative queries.

## Architecture Decisions
- In production, PDF ingestion should be Unstructured-first by default.
- `pdfminer` remains an explicit fallback for resilience, not the preferred parser.
- Every parser-path change must be measured by retrieval quality on affected documents before rollout.

## Scope
1. Make the production parser policy explicit in config and docs.
2. Add ingestion-time/parser-path logging so each ingested document records whether Unstructured or `pdfminer` was used.
3. Make fallback visible in logs and document metadata instead of silent-only behavior.
4. Add a regression gate for representative retrieval queries on affected PDF documents.

## Out Of Scope
- OCR
- table-model redesign
- multimodal embedding rollout

## Acceptance Criteria
- [ ] Unstructured is the explicit default parser path for PDFs in normal operation.
- [ ] `pdfminer` remains available only as an explicit fallback or emergency override.
- [ ] Ingested documents record which parser path was used.
- [ ] Fallback from Unstructured to `pdfminer` is visible in logs and traceable.
- [ ] A representative PDF retrieval suite is run before and after the change.
- [ ] The new parser policy does not ship unless retrieval quality is at least as good as baseline on the affected queries.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

