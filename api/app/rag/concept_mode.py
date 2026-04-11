"""
Concept Mode — AI Sage single-query flow.

Takes one natural language concept question and returns a structured response:
  - query
  - best_passages (evidence, inspectable on demand)
  - author_views (distinct per-author perspectives grounded in corpus)
  - synthesis (cross-author synthesis)
  - critique (pushback to prevent false confidence)
  - suggested_readings (best next passages from the corpus)
  - evidence_sufficient
  - weak_evidence_note (honest signal when corpus grounding is thin)

The LLM path produces richer output; the no-LLM fallback is always honest.
"""

from __future__ import annotations

import logging
import textwrap
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.rag.author_selection import SelectedAuthor, select_authors
from app.rag.inference import create_inference_client, inference_available, inference_model
from app.rag.query import EvidenceChunk, _author_entries, _enrich_chunks
from app.rag.retrieval import RetrievedChunk, retrieve_similar_chunks

log = logging.getLogger(__name__)

_CONCEPT_TOP_K_AUTHORS = 5
_CONCEPT_TOP_K_CHUNKS = 12
_MIN_CHUNKS_FOR_CONFIDENCE = 2
_CHUNKS_PER_AUTHOR_VIEW = 4
_SUGGESTED_READINGS_COUNT = 3


# ── Data shapes ───────────────────────────────────────────────────────────────


@dataclass
class AuthorView:
    author_id: str
    author_name: str
    view: str
    key_passages: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "author_id": self.author_id,
            "author_name": self.author_name,
            "view": self.view,
            "key_passages": self.key_passages,
        }


@dataclass
class SuggestedReading:
    author_id: str
    author_name: str
    passage: str
    source_url: Optional[str]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "author_id": self.author_id,
            "author_name": self.author_name,
            "passage": self.passage,
            "source_url": self.source_url,
            "reason": self.reason,
        }


@dataclass
class ConceptQueryResult:
    query: str
    best_passages: list[dict[str, Any]]
    author_views: list[dict[str, Any]]
    synthesis: Optional[str]
    critique: Optional[str]
    suggested_readings: list[dict[str, Any]]
    evidence_sufficient: bool
    weak_evidence_note: Optional[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "best_passages": self.best_passages,
            "author_views": self.author_views,
            "synthesis": self.synthesis,
            "critique": self.critique,
            "suggested_readings": self.suggested_readings,
            "evidence_sufficient": self.evidence_sufficient,
            "weak_evidence_note": self.weak_evidence_note,
        }


# ── LLM helpers ───────────────────────────────────────────────────────────────


def _llm_author_view(
    query: str,
    author_name: str,
    author_worldview: str,
    key_maxims: list[str],
    passages: list[str],
) -> str:
    joined = "\n\n---\n\n".join(passages[:_CHUNKS_PER_AUTHOR_VIEW])
    maxims_str = "; ".join(key_maxims[:4]) if key_maxims else "not specified"

    prompt = textwrap.dedent(f"""
        You are writing a short, distinct perspective on a concept question as {author_name} would frame it.

        The user's question: {query}

        {author_name}'s worldview: {author_worldview or "not specified"}
        {author_name}'s key maxims: {maxims_str}

        Relevant passages from {author_name}'s corpus:
        ---
        {joined}
        ---

        Instructions:
        - Write 2-4 sentences expressing how {author_name} specifically would think about this question.
        - Use language and framing that reflects their worldview and corpus — not generic finance.
        - Ground every claim in what the passages support. Do not speculate.
        - If the passages do not support a clear view, say so honestly in 1-2 sentences.
        - Do NOT start with "{author_name} would say..." — just write their perspective directly.
    """).strip()

    client = create_inference_client()
    response = client.chat.completions.create(
        model=inference_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=300,
    )
    return response.choices[0].message.content or ""


def _llm_synthesis(query: str, author_views: list[AuthorView]) -> str:
    views_block = "\n\n".join(
        f"{av.author_name}: {av.view}" for av in author_views
    )

    prompt = textwrap.dedent(f"""
        You are synthesizing multiple thinker perspectives on a concept question.

        Question: {query}

        Author perspectives:
        ---
        {views_block}
        ---

        Instructions:
        - Write a 3-5 sentence synthesis that captures the most important agreements and contrasts.
        - Preserve meaningful distinctions — do not flatten differences into one generic answer.
        - Make clear where these thinkers align and where they diverge.
        - Do not invent views not present in the perspectives above.
    """).strip()

    client = create_inference_client()
    response = client.chat.completions.create(
        model=inference_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=400,
    )
    return response.choices[0].message.content or ""


def _llm_critique(query: str, synthesis: str, author_views: list[AuthorView]) -> str:
    views_block = "\n\n".join(
        f"{av.author_name}: {av.view}" for av in author_views
    )

    prompt = textwrap.dedent(f"""
        You are providing a critique of the following synthesis and author perspectives on a concept question.

        Question: {query}

        Author perspectives:
        ---
        {views_block}
        ---

        Synthesis:
        {synthesis}

        Instructions:
        - Write 2-4 sentences of genuine pushback.
        - Identify what the perspectives collectively miss, overstate, or leave unresolved.
        - Point out where the corpus-grounded views might be limited, biased, or context-dependent.
        - Do not be ritually pessimistic — make the critique substantive and specific.
        - If the synthesis is sound and the perspectives are well-balanced, say so briefly and explain what would stress-test them.
    """).strip()

    client = create_inference_client()
    response = client.chat.completions.create(
        model=inference_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=300,
    )
    return response.choices[0].message.content or ""


def _llm_suggested_readings(
    query: str,
    chunks: list[EvidenceChunk],
    count: int = _SUGGESTED_READINGS_COUNT,
) -> str:
    """Ask LLM to pick the best next-step passages from the corpus evidence."""
    if not chunks:
        return ""

    passages_block = "\n\n".join(
        f"[{i+1}] {c.author_name}: {c.text[:300]}"
        for i, c in enumerate(chunks[:10])
    )

    prompt = textwrap.dedent(f"""
        A user asked: {query}

        Below are evidence passages from the author corpus.
        Pick the {count} passages that would best help the user go deeper on this topic.

        Passages:
        ---
        {passages_block}
        ---

        Return ONLY a JSON array of integers (1-based indices) in order of recommendation quality.
        Example: [3, 1, 7]
        No other text.
    """).strip()

    client = create_inference_client()
    response = client.chat.completions.create(
        model=inference_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=50,
    )
    raw = (response.choices[0].message.content or "").strip()

    import json
    import re
    try:
        indices = json.loads(raw)
    except Exception:
        m = re.search(r"\[.*?\]", raw)
        try:
            indices = json.loads(m.group()) if m else []
        except Exception:
            indices = []

    valid = [i - 1 for i in indices if isinstance(i, int) and 1 <= i <= len(chunks)]
    return valid[:count]


# ── Fallback helpers ──────────────────────────────────────────────────────────


def _template_author_view(
    author_name: str,
    worldview: Optional[str],
    key_maxims: list[str],
    passages: list[str],
) -> str:
    parts: list[str] = []
    if worldview:
        parts.append(worldview)
    if key_maxims:
        parts.append("Key principles: " + "; ".join(key_maxims[:3]) + ".")
    if passages:
        snippet = passages[0][:200].replace("\n", " ").strip()
        parts.append(f'From corpus: "{snippet}..."')
    if not parts:
        return f"{author_name}'s corpus was matched but does not yield a strong view on this question."
    return " ".join(parts)


def _template_synthesis(author_views: list[AuthorView]) -> str:
    if not author_views:
        return "No author views could be assembled for synthesis."
    names = ", ".join(av.author_name for av in author_views)
    return (
        f"The perspectives from {names} converge on some principles while diverging on emphasis. "
        "Review each author view above for their distinct framing."
    )


# ── Core function ─────────────────────────────────────────────────────────────


def execute_concept_query(
    query: str,
    db: Session,
    *,
    top_k_chunks: int = _CONCEPT_TOP_K_CHUNKS,
    top_k_authors: int = _CONCEPT_TOP_K_AUTHORS,
) -> ConceptQueryResult:
    """
    Execute a concept-mode query for AI Sage.

    Selects relevant authors, retrieves grounding passages, generates distinct
    per-author views, synthesizes, critiques, and suggests next readings.
    Degrades gracefully when the corpus is thin or LLM is unavailable.
    """
    # 1. Author selection
    selected: list[SelectedAuthor] = select_authors(
        query, db, top_k=top_k_authors
    )
    author_entries = _author_entries(selected, db)
    author_map = {e["author_id"]: e["name"] for e in author_entries}

    # 2. Retrieve evidence
    selected_ids = [a.author_id for a in selected]
    raw_chunks: list[RetrievedChunk] = retrieve_similar_chunks(
        query,
        db,
        top_k=top_k_chunks,
        author_ids=selected_ids if selected_ids else None,
    )
    evidence: list[EvidenceChunk] = _enrich_chunks(raw_chunks, db, author_map)

    evidence_sufficient = len(evidence) >= _MIN_CHUNKS_FOR_CONFIDENCE
    weak_evidence_note: Optional[str] = None
    if not evidence:
        weak_evidence_note = (
            "The author corpus does not contain passages strongly relevant to this question. "
            "The answer below is limited and may not reflect the authors' views accurately."
        )
    elif not evidence_sufficient:
        weak_evidence_note = (
            "Evidence from the corpus is thin for this question. "
            "The author views below are based on limited passages and should be read cautiously."
        )

    best_passages = [e.as_dict() for e in evidence]

    # 3. Build per-author chunk map
    author_chunk_map: dict[str, list[str]] = {}
    for chunk in evidence:
        author_chunk_map.setdefault(chunk.author_id, []).append(chunk.text)

    # 4. Generate author views
    author_views: list[AuthorView] = []
    for entry in author_entries:
        a_id = entry["author_id"]
        a_name = entry["name"]
        passages_for_author = author_chunk_map.get(a_id, [])

        # Skip authors with zero corpus grounding
        if not passages_for_author and not evidence_sufficient:
            continue

        key_passages = [p[:280] for p in passages_for_author[:2]]
        worldview = entry.get("worldview", "")
        key_maxims = entry.get("key_maxims") or []

        if inference_available() and passages_for_author:
            try:
                view_text = _llm_author_view(
                    query, a_name, worldview or "", key_maxims, passages_for_author
                )
            except Exception as exc:
                log.warning("LLM author view failed for %s: %s", a_id, exc)
                view_text = _template_author_view(a_name, worldview, key_maxims, passages_for_author)
        else:
            view_text = _template_author_view(a_name, worldview, key_maxims, passages_for_author)

        author_views.append(
            AuthorView(
                author_id=a_id,
                author_name=a_name,
                view=view_text,
                key_passages=key_passages,
            )
        )

    # 5. Synthesis
    synthesis: Optional[str] = None
    if author_views:
        if inference_available():
            try:
                synthesis = _llm_synthesis(query, author_views)
            except Exception as exc:
                log.warning("LLM synthesis failed: %s", exc)
                synthesis = _template_synthesis(author_views)
        else:
            synthesis = _template_synthesis(author_views)

    # 6. Critique
    critique: Optional[str] = None
    if synthesis and author_views and inference_available():
        try:
            critique = _llm_critique(query, synthesis, author_views)
        except Exception as exc:
            log.warning("LLM critique failed: %s", exc)

    # 7. Suggested readings
    suggested_readings: list[SuggestedReading] = []
    if evidence:
        if inference_available() and len(evidence) > _SUGGESTED_READINGS_COUNT:
            try:
                indices = _llm_suggested_readings(query, evidence, _SUGGESTED_READINGS_COUNT)
                for idx in indices:
                    chunk = evidence[idx]
                    reason = f"Strong corpus passage from {chunk.author_name} relevant to '{query[:60]}'"
                    suggested_readings.append(
                        SuggestedReading(
                            author_id=chunk.author_id,
                            author_name=chunk.author_name,
                            passage=chunk.text[:400],
                            source_url=str(chunk.metadata.get("source_url") or "") or None,
                            reason=reason,
                        )
                    )
            except Exception as exc:
                log.warning("LLM suggested readings failed: %s", exc)

        if not suggested_readings:
            # Fallback: top distinct-author chunks
            seen_authors: set[str] = set()
            for chunk in evidence:
                if chunk.author_id not in seen_authors:
                    seen_authors.add(chunk.author_id)
                    suggested_readings.append(
                        SuggestedReading(
                            author_id=chunk.author_id,
                            author_name=chunk.author_name,
                            passage=chunk.text[:400],
                            source_url=str(chunk.metadata.get("source_url") or "") or None,
                            reason=f"Top-matched passage from {chunk.author_name} for this concept.",
                        )
                    )
                if len(suggested_readings) >= _SUGGESTED_READINGS_COUNT:
                    break

    return ConceptQueryResult(
        query=query,
        best_passages=best_passages,
        author_views=[av.as_dict() for av in author_views],
        synthesis=synthesis,
        critique=critique,
        suggested_readings=[sr.as_dict() for sr in suggested_readings],
        evidence_sufficient=evidence_sufficient,
        weak_evidence_note=weak_evidence_note,
    )
