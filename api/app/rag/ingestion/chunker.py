"""
Text chunker for RAG ingestion.

Two-tier strategy:
1. Recursive character chunking (always active):
   Split by paragraphs → sentences → words with configurable overlap
   percentage and accurate token counting via tiktoken.
2. Semantic chunking (optional, RAG_CHUNKING_SEMANTIC=1):
   Detect topic shifts by comparing adjacent sentence embeddings and only
   split when cosine similarity drops below a threshold.

Both strategies support section-aware chunking when structured parse results
are available via chunk_structured().

Backward-compatible: chunk_text() delegates to chunk_recursive() internally.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

# ── Token counting ─────────────────────────────────────────────────────────────

_TOKENS_PER_WORD = 1.35
CHUNK_TARGET_TOKENS = 400
MIN_PARAGRAPH_CHARS = 40

try:
    import tiktoken as _tiktoken

    _enc = _tiktoken.get_encoding("cl100k_base")
    _TIKTOKEN_AVAILABLE = True
except Exception:
    _tiktoken = None  # type: ignore[assignment]
    _enc = None
    _TIKTOKEN_AVAILABLE = False


def _count_tokens(text: str) -> int:
    """Count tokens accurately via tiktoken, falling back to word-count estimate."""
    if _TIKTOKEN_AVAILABLE and _enc is not None:
        return max(1, len(_enc.encode(text)))
    return max(1, int(len(text.split()) * _TOKENS_PER_WORD))


def _approx_tokens(text: str) -> int:
    """Alias for _count_tokens; kept for backward compatibility."""
    return _count_tokens(text)


# ── Configuration helpers ──────────────────────────────────────────────────────


def _cfg_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


def _cfg_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


def _cfg_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key, "")
    if val == "":
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# ── Data structures ────────────────────────────────────────────────────────────


@dataclass
class Chunk:
    index: int
    text: str
    token_count: int
    metadata_json: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentSection:
    """Minimal section structure from structured parsing (Issue 139)."""

    heading: str
    content: str
    is_table: bool = False
    is_list: bool = False


# ── Sentence splitting ─────────────────────────────────────────────────────────

# Matches sentence boundaries: end punctuation followed by whitespace + capital letter.
# Negative lookbehind prevents splitting on abbreviations like Mr., Dr., U.S., 1.5, etc.
_SENTENCE_PATTERN = re.compile(
    r"(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\!|\?)\s+(?=[A-Z])"
)


def _split_sentences(text: str) -> list[str]:
    """
    Split text into sentences using regex-based boundary detection.

    Handles common abbreviations (Mr., Dr., U.S.) and decimal numbers.
    Returns list of non-empty sentence strings.
    """
    parts = _SENTENCE_PATTERN.split(text)
    return [s.strip() for s in parts if s.strip()]


def _split_paragraphs(text: str) -> list[str]:
    """Split on blank lines; return only non-trivial paragraphs."""
    parts = re.split(r"\n{2,}", text)
    return [p.strip() for p in parts if len(p.strip()) >= MIN_PARAGRAPH_CHARS]


def _split_words(text: str, target_tokens: int) -> list[str]:
    """Split text at word boundaries into fragments of at most target_tokens each."""
    words = text.split()
    if not words:
        return []
    fragments: list[str] = []
    current_words: list[str] = []
    current_tokens = 0
    for word in words:
        wt = _count_tokens(word + " ")
        if current_words and current_tokens + wt > target_tokens:
            fragments.append(" ".join(current_words))
            current_words = [word]
            current_tokens = wt
        else:
            current_words.append(word)
            current_tokens += wt
    if current_words:
        fragments.append(" ".join(current_words))
    return fragments


def _recursive_split(text: str, target_tokens: int) -> list[str]:
    """
    Recursively split text into units of at most target_tokens.

    Cascade: paragraphs → sentences → words.
    """
    if _count_tokens(text) <= target_tokens:
        return [text]

    # Try paragraph split
    paragraphs = _split_paragraphs(text)
    if len(paragraphs) > 1:
        result: list[str] = []
        for p in paragraphs:
            result.extend(_recursive_split(p, target_tokens))
        return result

    # Try sentence split
    sentences = _split_sentences(text)
    if len(sentences) > 1:
        result = []
        for s in sentences:
            result.extend(_recursive_split(s, target_tokens))
        return result

    # Fall back to word-level split
    return _split_words(text, target_tokens)


# ── Greedy merge with percentage-based overlap ─────────────────────────────────


def _greedy_merge(
    units: list[str],
    target_tokens: int,
    overlap_tokens: int,
    min_tokens: int,
    base_metadata: dict[str, Any],
    chunk_offset: int = 0,
) -> list[Chunk]:
    """
    Greedily merge text units into chunks with percentage-based overlap.

    Args:
        units: List of text fragments (sentences, paragraphs, words).
        target_tokens: Soft token limit per chunk.
        overlap_tokens: Number of tokens to carry over from previous chunk.
        min_tokens: Minimum tokens for a chunk; tiny remainders are merged into the last chunk.
        base_metadata: Dict merged into each chunk's metadata_json.
        chunk_offset: Starting index for chunk numbering.

    Returns:
        List of Chunk objects.
    """
    # Cap min_tokens so it never exceeds half of target (avoids infinite merge loops
    # when target is smaller than the configured min_tokens default).
    effective_min = min(min_tokens, max(1, target_tokens // 2))

    chunks: list[Chunk] = []
    current_units: list[str] = []
    current_tokens = 0
    current_overlap_tok = 0

    def _flush(overlap_tok: int, *, is_final: bool = False) -> Optional[Chunk]:
        if not current_units:
            return None
        text = " ".join(current_units).strip()
        tok = _count_tokens(text)
        # Only merge tiny remainders into the previous chunk on the final flush.
        # During regular flushes (mid-iteration) we always emit a chunk so that
        # chunks at the target boundary are not swallowed into the prior chunk.
        if is_final and tok < effective_min and chunks:
            prev = chunks[-1]
            merged = prev.text + " " + text
            mtok = _count_tokens(merged)
            chunks[-1] = Chunk(
                index=prev.index,
                text=merged,
                token_count=mtok,
                metadata_json={**prev.metadata_json, "token_count": mtok},
            )
            return None
        meta = {
            **base_metadata,
            "chunk_index": chunk_offset + len(chunks),
            "overlap_tokens": overlap_tok,
        }
        return Chunk(
            index=chunk_offset + len(chunks),
            text=text,
            token_count=tok,
            metadata_json=meta,
        )

    for unit in units:
        unit_tokens = _count_tokens(unit)
        if current_units and (current_tokens + unit_tokens > target_tokens):
            chunk = _flush(current_overlap_tok)
            if chunk is not None:
                chunks.append(chunk)
            # Build overlap from the tail of the current buffer
            overlap_units: list[str] = []
            overlap_accumulated = 0
            for u in reversed(current_units):
                ut = _count_tokens(u)
                if overlap_accumulated + ut <= overlap_tokens:
                    overlap_units.insert(0, u)
                    overlap_accumulated += ut
                else:
                    break
            current_units = overlap_units + [unit]
            current_tokens = sum(_count_tokens(u) for u in current_units)
            current_overlap_tok = overlap_accumulated
        else:
            current_units.append(unit)
            current_tokens += unit_tokens

    if current_units:
        chunk = _flush(current_overlap_tok, is_final=True)
        if chunk is not None:
            chunks.append(chunk)

    return chunks


# ── Semantic chunking ──────────────────────────────────────────────────────────


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _detect_topic_boundaries(
    sentences: list[str],
    threshold: float,
) -> list[bool]:
    """
    Detect topic boundaries by cosine similarity of adjacent sentence embeddings.

    Returns list of booleans (len = len(sentences) - 1), where True means a topic
    boundary exists between sentence[i] and sentence[i+1].
    """
    if len(sentences) < 2:
        return []

    from app.rag.ingestion.embedder import embed_batch

    vectors = embed_batch(sentences)
    boundaries: list[bool] = []
    for i in range(len(vectors) - 1):
        sim = _cosine_similarity(vectors[i], vectors[i + 1])
        boundaries.append(sim < threshold)
    return boundaries


def _apply_semantic_boundaries(
    sentences: list[str],
    boundaries: list[bool],
) -> list[list[str]]:
    """Group sentences into topic-coherent groups separated by semantic boundaries."""
    if not sentences:
        return []
    groups: list[list[str]] = [[sentences[0]]]
    for i, is_boundary in enumerate(boundaries):
        if is_boundary:
            groups.append([sentences[i + 1]])
        else:
            groups[-1].append(sentences[i + 1])
    return groups


# ── Public API ─────────────────────────────────────────────────────────────────


def chunk_recursive(
    text: str,
    *,
    base_metadata: Optional[dict[str, Any]] = None,
    target_tokens: Optional[int] = None,
    overlap_pct: Optional[float] = None,
    min_chunk_tokens: Optional[int] = None,
    semantic: Optional[bool] = None,
    semantic_threshold: Optional[float] = None,
    chunk_offset: int = 0,
) -> list[Chunk]:
    """
    Recursive character chunking with percentage-based overlap.

    Splits text at paragraph → sentence → word boundaries as needed.
    Supports optional semantic chunking overlay (RAG_CHUNKING_SEMANTIC=1).

    Args:
        text: Cleaned document text.
        base_metadata: Dict merged into each chunk's metadata_json.
        target_tokens: Soft token limit per chunk (default: RAG_CHUNKING_TARGET_TOKENS env or 400).
        overlap_pct: Overlap fraction of target_tokens (default: RAG_CHUNKING_OVERLAP_PCT env or 0.15).
        min_chunk_tokens: Minimum tokens per chunk (default: RAG_CHUNKING_MIN_TOKENS env or 50).
        semantic: Enable semantic boundary detection (default: RAG_CHUNKING_SEMANTIC env or False).
        semantic_threshold: Similarity threshold for topic boundaries (default: 0.75).
        chunk_offset: Starting chunk index for multi-section documents.

    Returns:
        List of Chunk objects in order.
    """
    if base_metadata is None:
        base_metadata = {}

    _target = (
        target_tokens
        if target_tokens is not None
        else _cfg_int("RAG_CHUNKING_TARGET_TOKENS", CHUNK_TARGET_TOKENS)
    )
    _overlap_pct = (
        overlap_pct
        if overlap_pct is not None
        else _cfg_float("RAG_CHUNKING_OVERLAP_PCT", 0.15)
    )
    _min_tokens = (
        min_chunk_tokens
        if min_chunk_tokens is not None
        else _cfg_int("RAG_CHUNKING_MIN_TOKENS", 50)
    )
    _semantic = (
        semantic if semantic is not None else _cfg_bool("RAG_CHUNKING_SEMANTIC", False)
    )
    _threshold = (
        semantic_threshold
        if semantic_threshold is not None
        else _cfg_float("RAG_CHUNKING_SEMANTIC_THRESHOLD", 0.75)
    )

    overlap_tokens = max(1, int(_target * _overlap_pct))

    if not text.strip():
        return []

    if _semantic:
        sentences = _split_sentences(text)
        if len(sentences) > 1:
            try:
                boundaries = _detect_topic_boundaries(sentences, _threshold)
                groups = _apply_semantic_boundaries(sentences, boundaries)
                all_chunks: list[Chunk] = []
                for group in groups:
                    group_text = " ".join(group)
                    units = _recursive_split(group_text, _target)
                    group_chunks = _greedy_merge(
                        units,
                        _target,
                        overlap_tokens,
                        _min_tokens,
                        base_metadata,
                        chunk_offset + len(all_chunks),
                    )
                    all_chunks.extend(group_chunks)
                return all_chunks
            except Exception:
                pass  # Fall through to standard path on embedding failure

    units = _recursive_split(text, _target)
    return _greedy_merge(
        units, _target, overlap_tokens, _min_tokens, base_metadata, chunk_offset
    )


def chunk_structured(
    sections: list[DocumentSection],
    *,
    base_metadata: Optional[dict[str, Any]] = None,
    target_tokens: Optional[int] = None,
    overlap_pct: Optional[float] = None,
    min_chunk_tokens: Optional[int] = None,
    semantic: bool = False,
) -> list[Chunk]:
    """
    Section-aware chunking with recursive splitting per section.

    Never merges chunks across section boundaries.
    Tables are kept as single atomic chunks regardless of size.
    Lists are kept intact when possible.

    Args:
        sections: List of DocumentSection objects from structured parsing.
        base_metadata: Dict merged into each chunk's metadata_json.
        target_tokens: Soft token limit per chunk.
        overlap_pct: Overlap fraction of target_tokens.
        min_chunk_tokens: Minimum tokens per chunk.
        semantic: Enable semantic boundary detection.

    Returns:
        List of Chunk objects in order, never crossing section boundaries.
    """
    if base_metadata is None:
        base_metadata = {}

    all_chunks: list[Chunk] = []

    for section in sections:
        section_meta = {**base_metadata, "section_heading": section.heading}

        if section.is_table:
            # Tables are single chunks regardless of size
            tok = _count_tokens(section.content)
            meta = {
                **section_meta,
                "chunk_index": len(all_chunks),
                "overlap_tokens": 0,
                "is_table": True,
            }
            all_chunks.append(
                Chunk(
                    index=len(all_chunks),
                    text=section.content,
                    token_count=tok,
                    metadata_json=meta,
                )
            )
            continue

        section_chunks = chunk_recursive(
            section.content,
            base_metadata=section_meta,
            target_tokens=target_tokens,
            overlap_pct=overlap_pct,
            min_chunk_tokens=min_chunk_tokens,
            semantic=semantic,
            chunk_offset=len(all_chunks),
        )
        all_chunks.extend(section_chunks)

    # Re-index all chunks sequentially
    for i, chunk in enumerate(all_chunks):
        chunk.index = i
        chunk.metadata_json["chunk_index"] = i

    return all_chunks


def chunk_text(
    clean_text: str,
    *,
    base_metadata: Optional[dict[str, Any]] = None,
    target_tokens: int = CHUNK_TARGET_TOKENS,
) -> list[Chunk]:
    """
    Split clean_text into overlapping token-bounded chunks.

    Backward-compatible entry point. Internally delegates to chunk_recursive().

    Args:
        clean_text: Cleaned document text.
        base_metadata: Dict merged into each chunk's metadata_json.
                       Caller should populate: author, author_id, work_title,
                       source_url, published_at, source_type, doc_hash.
        target_tokens: Soft token limit per chunk.

    Returns:
        List of Chunk objects in order.
    """
    return chunk_recursive(
        clean_text,
        base_metadata=base_metadata,
        target_tokens=target_tokens,
    )
