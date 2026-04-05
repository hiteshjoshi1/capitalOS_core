"""
Text chunker for RAG ingestion.

Strategy:
1. Split clean_text into paragraphs (double-newline boundaries).
2. Filter out trivially short paragraphs (< MIN_PARAGRAPH_CHARS).
3. Greedily merge adjacent paragraphs into chunks up to CHUNK_TARGET_TOKENS.
4. Produce an overlap by appending the last paragraph of the previous chunk
   to the beginning of the next chunk.

Each Chunk carries metadata_json required for citation-ready retrieval.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

# Token count approximation: words × 1.35 (conservative estimate, no tiktoken dep required).
_TOKENS_PER_WORD = 1.35
CHUNK_TARGET_TOKENS = 400
MIN_PARAGRAPH_CHARS = 40


def _approx_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * _TOKENS_PER_WORD))


@dataclass
class Chunk:
    index: int
    text: str
    token_count: int
    metadata_json: dict[str, Any] = field(default_factory=dict)


def _split_paragraphs(text: str) -> list[str]:
    """Split on blank lines; return only non-trivial paragraphs."""
    parts = re.split(r"\n{2,}", text)
    return [p.strip() for p in parts if len(p.strip()) >= MIN_PARAGRAPH_CHARS]


def chunk_text(
    clean_text: str,
    *,
    base_metadata: Optional[dict[str, Any]] = None,
    target_tokens: int = CHUNK_TARGET_TOKENS,
) -> list[Chunk]:
    """
    Split clean_text into overlapping token-bounded chunks.

    Args:
        clean_text: Cleaned document text.
        base_metadata: Dict merged into each chunk's metadata_json.
                       Caller should populate: author, author_id, work_title,
                       source_url, published_at, source_type, doc_hash.
        target_tokens: Soft token limit per chunk.

    Returns:
        List of Chunk objects in order.
    """
    if base_metadata is None:
        base_metadata = {}

    paragraphs = _split_paragraphs(clean_text)
    if not paragraphs:
        return []

    chunks: list[Chunk] = []
    current_paras: list[str] = []
    current_tokens = 0
    overlap_para: Optional[str] = None  # last para from previous chunk

    def _flush(paras: list[str]) -> Chunk:
        text = "\n\n".join(paras)
        meta = {
            **base_metadata,
            "chunk_index": len(chunks),
        }
        return Chunk(
            index=len(chunks),
            text=text,
            token_count=_approx_tokens(text),
            metadata_json=meta,
        )

    for para in paragraphs:
        para_tokens = _approx_tokens(para)

        # If adding this paragraph would exceed target, flush current buffer.
        if current_paras and (current_tokens + para_tokens > target_tokens):
            chunks.append(_flush(current_paras))
            # Overlap: seed next chunk with the last paragraph.
            overlap_para = current_paras[-1]
            current_paras = [overlap_para] if overlap_para else []
            current_tokens = _approx_tokens(overlap_para) if overlap_para else 0

        current_paras.append(para)
        current_tokens += para_tokens

    # Flush remaining
    if current_paras:
        chunks.append(_flush(current_paras))

    return chunks
