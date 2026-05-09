# Issue 166: Ingestion figure preservation, modality metadata, and content-aware chunking

## Objective
- Improve ingestion fidelity beyond tables without touching OCR yet.
- Preserve figures/images/charts as first-class document blocks instead of collapsing them into incidental text.
- Make chunking content-type-aware and preserve section lineage so downstream retrieval has better structural inputs.

## Problem
- Figures and charts are still largely lost as structured artifacts.
- The system does not yet persist enough modality metadata to distinguish prose, figure, table, list, quote, or layout-heavy blocks in a durable way.
- Chunking is materially better than before, but still not driven strongly enough by document structure and block type.

## Architecture Decisions
- OCR is explicitly out of scope for this issue.
- Figure/chart/image preservation should be deterministic, not LLM-generated.
- Content-type-aware chunking should be built on parser output and block metadata, not string heuristics alone.
- No ingestion-path change may ship if representative retrieval quality degrades on the affected corpus.

## Scope
1. Preserve figure/image/chart blocks as structured content with:
   - caption
   - nearby explanatory text when available
   - stable source reference
2. Persist per-block modality metadata such as:
   - prose
   - table
   - figure
   - list
   - quote
   - layout-sensitive
3. Preserve section-path / heading lineage for chunk metadata.
4. Make chunking content-type-aware:
   - prose recursive/semantic
   - tables atomic
   - lists mostly atomic
   - figures coupled with captions / local explanation
5. If multimodal ingestion is included, keep it targeted and opt-in for layout-sensitive documents only.

## Out Of Scope
- OCR
- retrieval reranker changes
- query audit trail

## Acceptance Criteria
- [ ] Figure/image/chart-bearing documents preserve structured figure blocks.
- [ ] Block-level modality metadata is persisted and exposed for downstream use.
- [ ] Chunks carry stable section-path metadata where the source structure exists.
- [ ] Chunking behavior differs appropriately by content type.
- [ ] If multimodal ingestion is adopted in scope, the routing rules are explicit and deterministic.
- [ ] Representative retrieval checks are run before and after the ingestion changes.
- [ ] The ingestion changes do not ship unless retrieval quality is at least as good as the current baseline on affected queries.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

