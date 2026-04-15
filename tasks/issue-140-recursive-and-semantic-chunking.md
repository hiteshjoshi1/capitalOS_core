# Issue 140: Recursive and Semantic Chunking

## Problem Statement

### What is wrong today

The current chunker (`api/app/rag/ingestion/chunker.py`) uses the simplest possible strategy:

1. Split on double-newline (`\n{2,}`) into paragraphs.
2. Drop paragraphs < 40 chars.
3. Greedily merge adjacent paragraphs until ~400 tokens (estimated at `words × 1.35`).
4. Overlap: carry the **last paragraph** of the previous chunk into the next chunk.

This is naïve paragraph-boundary splitting with fixed single-paragraph overlap.

### Why it hurts retrieval quality

1. **No sentence-boundary awareness:** A single long paragraph that exceeds 400 tokens is never split. It becomes one oversized chunk. If the paragraph contains multiple distinct ideas, the embedding is an average that retrieves poorly for any specific idea.

2. **No recursive fallback:** When paragraphs are too large, the chunker does not fall back to sentence-level or word-level splitting. It just creates an oversized chunk.

3. **No topic-shift detection:** A passage that transitions from "capital allocation" to "insurance operations" within consecutive paragraphs will be merged into one chunk. The embedding becomes a blend of both topics, diluting retrieval precision for either query.

4. **Fixed overlap is too rigid:** Carrying exactly one paragraph (regardless of its size) means overlap varies wildly — from 20 tokens (short paragraph) to 200+ tokens (long paragraph). A percentage-based overlap (15-20% of target size) would be more consistent.

5. **Approximate token counting:** `words × 1.35` can be off by 10-20% compared to actual token counts, causing inconsistent chunk sizes.

6. **No section-heading awareness:** Even if issue 139 (advanced parsing) provides section structure, the current chunker has no way to use it — it takes flat `clean_text` only.

### Evidence from code

```python
# api/app/rag/ingestion/chunker.py
_TOKENS_PER_WORD = 1.35
CHUNK_TARGET_TOKENS = 400
MIN_PARAGRAPH_CHARS = 40

def _split_paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n{2,}", text)
    return [p.strip() for p in parts if len(p.strip()) >= MIN_PARAGRAPH_CHARS]
```

No sentence splitting. No semantic analysis. No recursive descent.

## Goal

Replace the current chunker with a two-tier strategy:

1. **Recursive character chunking** (always active): Split by paragraphs → sentences → words, with configurable overlap percentage and accurate token counting.
2. **Semantic chunking** (optional, toggleable): Detect topic shifts by comparing sentence embeddings and only split when semantic similarity drops below a threshold.

Both strategies should support section-aware chunking when structured parse results (from issue 139) are available.

## Current State (Code Evidence)

| Component | File | Status |
|-----------|------|--------|
| Chunker | `api/app/rag/ingestion/chunker.py` | Paragraph-only split, greedy merge, single-paragraph overlap |
| Token estimation | `chunker.py:_approx_tokens()` | `words × 1.35` — no tiktoken |
| Pipeline integration | `pipeline.py:_persist_document_and_chunks()` | Calls `chunk_text(parse_result.clean_text)` |
| Chunk model | `api/app/models/rag.py:RagChunk` | Stores `text`, `token_count`, `metadata_json` |

## Proposed Technical Design

### Tier 1: Recursive Character Chunking

This replaces the current chunker as the default strategy.

```
Input: clean_text (or list of DocumentSections from issue 139)
  → Split into sections (if structured input available)
  → For each section:
    → Split into paragraphs (double-newline)
    → If paragraph > target_tokens:
      → Split into sentences (regex or spaCy)
      → If sentence > target_tokens:
        → Split at word boundaries
    → Greedily merge smallest units into chunks up to target_tokens
    → Apply overlap: last N tokens from previous chunk prepended to next
  → Emit chunks with metadata (section_heading, chunk_index, overlap_tokens)
```

**Key parameters:**
- `target_tokens`: 400 (default, configurable)
- `overlap_pct`: 15% (default, configurable; ~60 tokens for 400-token target)
- `min_chunk_tokens`: 50 (don't emit tiny fragments)
- `sentence_splitter`: regex-based (default) or spaCy (optional)

**Sentence splitting regex:**
```python
# Handles abbreviations (Mr., Dr., U.S.), decimal numbers, etc.
_SENTENCE_PATTERN = re.compile(
    r'(?<=[.!?])\s+(?=[A-Z])'  # Simple but effective for English prose
)
```

**Token counting:**
- Use `tiktoken` with `cl100k_base` encoding (GPT-4/voyage compatible) for accurate counts.
- Fall back to `words × 1.35` if tiktoken is not installed.

### Tier 2: Semantic Chunking (Optional)

This is an enhancement layer that runs after recursive splitting to detect and respect topic boundaries.

```
Input: list of sentences from recursive splitting
  → Embed each sentence (using the same embedding model, batch)
  → Compare cosine similarity between adjacent sentence embeddings
  → When similarity drops below threshold (default: 0.75):
    → Mark as topic boundary
    → Force a chunk split at that point
  → Merge non-boundary sentences into chunks up to target_tokens
```

**Key parameters:**
- `semantic_threshold`: 0.75 (similarity below this = topic shift)
- `min_semantic_chunk_tokens`: 100 (don't create very small semantic chunks)
- `enabled`: controlled by `RAG_CHUNKING_SEMANTIC=1` env var (default: off)

**Cost consideration:** Semantic chunking requires embedding every sentence at ingestion time. For a large corpus, this is expensive. It should be:
- Off by default.
- Enabled per-source or per-author if needed.
- Cached — sentence embeddings can be stored temporarily during ingestion.

### Section-Aware Chunking (Integration with Issue 139)

When `StructuredParseResult` provides sections:
- Never merge chunks across section boundaries.
- Preserve `section_heading` in chunk metadata.
- Tables are chunked as single units (one table = one chunk, even if oversized).
- Lists are kept intact when possible.

```python
def chunk_structured(
    sections: list[DocumentSection],
    *,
    base_metadata: dict | None = None,
    target_tokens: int = 400,
    overlap_pct: float = 0.15,
    semantic: bool = False,
) -> list[Chunk]:
    """Section-aware chunking with recursive splitting per section."""
```

### Configuration

```bash
# Chunking strategy
RAG_CHUNKING_TARGET_TOKENS=400
RAG_CHUNKING_OVERLAP_PCT=0.15
RAG_CHUNKING_MIN_TOKENS=50
RAG_CHUNKING_SEMANTIC=0            # 0=off, 1=on
RAG_CHUNKING_SEMANTIC_THRESHOLD=0.75
```

### Backward Compatibility

- `chunk_text()` function signature stays the same.
- New `chunk_recursive()` and `chunk_structured()` functions are added alongside.
- `chunk_text()` internally delegates to `chunk_recursive()` on new code path.
- Existing chunks in the database are not affected — re-ingestion is needed for quality gains.

## Implementation Plan

### Step 1: Add tiktoken dependency
- Add `tiktoken>=0.7.0` to `api/requirements.txt`.
- Create `_count_tokens()` that uses tiktoken with `cl100k_base`, falling back to `words × 1.35`.

### Step 2: Implement sentence splitting
- Add `_split_sentences(text: str) -> list[str]` with regex-based sentence boundary detection.
- Handle common abbreviations and edge cases.

### Step 3: Implement recursive character chunking
- Add `chunk_recursive()` function:
  - Split text → paragraphs → sentences → words (recursive descent)
  - Greedy merge with percentage-based overlap
  - Accurate token counting via tiktoken
- Wire as the new default behind `chunk_text()`.

### Step 4: Implement section-aware chunking
- Add `chunk_structured()` that accepts `list[DocumentSection]`.
- Respects section boundaries.
- Handles tables and lists as atomic units.
- Falls back to `chunk_recursive()` per-section.

### Step 5: Implement semantic chunking (optional layer)
- Add `_detect_topic_boundaries()` that embeds sentences and finds similarity drops.
- Integrate as an optional overlay in `chunk_recursive()` when `RAG_CHUNKING_SEMANTIC=1`.
- Use batch embedding to minimize API calls.

### Step 6: Update pipeline integration
- `_persist_document_and_chunks()` checks for `StructuredParseResult` → calls `chunk_structured()`.
- Falls back to `chunk_recursive()` for flat `clean_text`.
- Config-driven via env vars.

### Step 7: Add token count to existing chunk metadata
- Add accurate `token_count` using tiktoken.
- Add `overlap_tokens` to metadata for debugging.
- Add `section_heading` to metadata when available.

## Acceptance Criteria

- [ ] Long paragraphs (>400 tokens) are split at sentence boundaries, never left as oversized chunks.
- [ ] Overlap between consecutive chunks is approximately 15% of target size (±5%).
- [ ] Token counts in `rag_chunks.token_count` are within 5% of tiktoken ground truth.
- [ ] Section boundaries (when provided by structured parsing) are never crossed by a chunk.
- [ ] Tables are chunked as single units.
- [ ] Semantic chunking (when enabled) produces chunks that align with topic shifts.
- [ ] `chunk_text()` backward compatibility: existing callers produce equivalent or better chunks.
- [ ] All existing chunker tests pass.
- [ ] New tests cover: sentence splitting, recursive descent, section-aware chunking, semantic boundary detection.
- [ ] Configuration via env vars works: target tokens, overlap percentage, semantic toggle.

## Risks / Tradeoffs

| Risk | Mitigation |
|------|-----------|
| tiktoken adds ~2MB dependency | Minimal; it's already used by most LLM tooling |
| Sentence splitting regex fails on edge cases | Test on real corpus; can upgrade to spaCy later if needed |
| Semantic chunking is expensive (embeds every sentence) | Off by default; only enable for high-value sources |
| Re-ingestion needed for existing corpus | Provide `make rag-reingest`; old chunks still work |
| Chunk size distribution changes may affect retrieval tuning | Monitor retrieval quality before/after; configurable target |

## Test / Evaluation Plan

### Unit tests
- Test `_split_sentences()` on 10+ edge cases (abbreviations, numbers, multi-line, etc.).
- Test `chunk_recursive()` on:
  - Short text (< target) → single chunk
  - Long paragraph (> target) → sentence-level split
  - Multiple paragraphs → greedy merge with correct overlap
- Test `chunk_structured()` with mock sections → no cross-section chunks.
- Test semantic boundary detection with synthetic sentence sequences.
- Test tiktoken vs approximate token counts on real corpus passages.

### Integration tests
- Full ingestion pipeline with new chunker → verify chunk quality.
- Verify `rag_chunks.metadata_json` contains `section_heading` and `overlap_tokens`.

### Quality evaluation
- Compare chunk distributions (token count histograms) before and after.
- Manual inspection of 5 representative documents for chunk boundary quality.
- Retrieval A/B test: same queries, old vs new chunks, compare top-5 relevance.

## Files Likely to Change

- `api/app/rag/ingestion/chunker.py` — Major rewrite
- `api/app/rag/ingestion/pipeline.py` — Integration with structured/recursive chunking
- `api/requirements.txt` — tiktoken dependency
- `api/tests/test_rag_chunker.py` — New comprehensive test file
- `api/app/rag/ingestion/parser.py` — Coordinate with issue 139 output format

## Dependencies

- **Soft dependency on Issue 139:** Section-aware chunking requires `StructuredParseResult`. But recursive character chunking works independently of parsing upgrades and should ship first.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved
