"""
Grounded query execution for RAG intelligence retrieval.

Three query modes:
  - retrieve:  Returns top-k evidence chunks with citation metadata.
  - ask:       Returns a grounded short answer synthesized from evidence.
  - company_context: Returns relevant author lenses and evidence pack for a company.

Author selection is always dynamic (not hardcoded).
LLM synthesis degrades gracefully when no key is configured.
"""

from __future__ import annotations

import logging
import textwrap
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.rag import RagAuthorProfile
from app.rag.author_selection import SelectedAuthor, select_authors
from app.rag.inference import create_inference_client, inference_available, inference_model
from app.rag.retrieval import (
    RetrievedChunk,
    deliver_parent_sections,
    retrieval_hardening_enabled,
    retrieve_hybrid,
    retrieve_similar_chunks,
    suppress_near_duplicates,
    trace_retrieval_chunks,
    trace_retrieval_payload,
)

log = logging.getLogger(__name__)


# ── Data models ───────────────────────────────────────────────────────────────


@dataclass
class EvidenceChunk:
    chunk_id: str
    author_id: str
    author_name: str
    text: str
    similarity: float
    metadata: dict[str, Any]
    document_id: Optional[str] = None
    ranking_score: Optional[float] = None
    score_type: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "chunk_id": self.chunk_id,
            "author_id": self.author_id,
            "author_name": self.author_name,
            "text": self.text,
            "similarity": self.similarity,
            "metadata": self.metadata,
        }
        if self.document_id is not None:
            payload["document_id"] = self.document_id
        if self.ranking_score is not None:
            payload["ranking_score"] = self.ranking_score
        if self.score_type is not None:
            payload["score_type"] = self.score_type
        return payload


@dataclass
class QueryResult:
    query: str
    mode: str
    selected_authors: list[dict]
    evidence_chunks: list[dict]
    answer: Optional[str]
    missing_information: Optional[str]
    evidence_sufficient: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "mode": self.mode,
            "selected_authors": self.selected_authors,
            "evidence_chunks": self.evidence_chunks,
            "answer": self.answer,
            "missing_information": self.missing_information,
            "evidence_sufficient": self.evidence_sufficient,
        }


@dataclass
class CompanyContextResult:
    company: str
    question: str
    relevant_author_lenses: list[dict]
    evidence_pack: list[dict]
    evidence_sufficient: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "company": self.company,
            "question": self.question,
            "relevant_author_lenses": self.relevant_author_lenses,
            "evidence_pack": self.evidence_pack,
            "evidence_sufficient": self.evidence_sufficient,
        }


# ── LLM helpers ───────────────────────────────────────────────────────────────


def _synthesize_answer(query: str, evidence_texts: list[str], author_names: list[str]) -> str:
    """Use the configured inference provider to synthesize a grounded answer."""

    joined = "\n\n---\n\n".join(evidence_texts[:10])
    authors_str = ", ".join(author_names) if author_names else "the corpus"

    prompt = textwrap.dedent(f"""
        You are answering a question using only the evidence passages below from {authors_str}.

        Question: {query}

        Evidence passages:
        ---
        {joined}
        ---

        Instructions:
        - Answer based only on the evidence provided. Do not use outside knowledge.
        - Be concise (3-5 sentences).
        - If the evidence is insufficient to fully answer the question, say so.
        - Do not speculate beyond what the evidence supports.
    """).strip()

    client = create_inference_client()
    response = client.chat.completions.create(
        model=inference_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=400,
    )
    return response.choices[0].message.content or ""


# ── Core query functions ──────────────────────────────────────────────────────


def execute_retrieve(
    query: str,
    db: Session,
    *,
    top_k: int = 5,
    author_id: Optional[str] = None,
    domains: Optional[list[str]] = None,
    expertise_tags: Optional[list[str]] = None,
) -> QueryResult:
    """
    Retrieve top-k evidence chunks with full citation metadata.
    Performs author selection and filters retrieval to selected authors.
    """
    _t0 = time.monotonic()
    selected = select_authors(
        query, db,
        author_id=author_id,
        domains=domains,
        expertise_tags=expertise_tags,
        top_k=4,
    )
    selected_author_ids = [author.author_id for author in selected]
    selected_author_names = [author.name for author in selected]
    hardening_active = retrieval_hardening_enabled()
    trace_retrieval_payload(
        "query_selected_authors",
        {
            "query": query,
            "mode": "retrieve",
            "selected_author_ids": selected_author_ids,
            "selected_author_names": selected_author_names,
            "hardening_enabled": hardening_active,
        },
    )

    if hardening_active:
        chunks = retrieve_hybrid(
            query,
            db,
            top_k=top_k,
            author_id=author_id,
            author_ids=None if author_id else selected_author_ids,
            source_author_names=selected_author_names,
            domains=domains,
            expertise_tags=expertise_tags,
            hardening_enabled=True,
        )
    else:
        chunks = retrieve_similar_chunks(
            query,
            db,
            top_k=top_k,
            author_id=author_id,
            author_ids=None if author_id else selected_author_ids,
            domains=domains,
            expertise_tags=expertise_tags,
        )

    author_entries = _author_entries(selected, db)
    author_map = {entry["author_id"]: entry["name"] for entry in author_entries}
    evidence, evidence_audit = _prepare_evidence_pack(
        chunks,
        db,
        author_map,
        query_text=query,
        hardening_enabled=hardening_active,
    )

    result = QueryResult(
        query=query,
        mode="retrieve",
        selected_authors=author_entries,
        evidence_chunks=[e.as_dict() for e in evidence],
        answer=None,
        missing_information=None if chunks else "No corpus evidence found for this query.",
        evidence_sufficient=len(chunks) > 0,
    )
    _log_query_async(
        db, query, "retrieve",
        evidence=evidence,
        latency_ms=int((time.monotonic() - _t0) * 1000),
        retrieval_config={
            "top_k": top_k,
            "retrieval_hardening_enabled": hardening_active,
            "retrieval_path": "hybrid_parent_child" if hardening_active else "dense_legacy",
            **evidence_audit,
        },
    )
    return result


def execute_ask(
    query: str,
    db: Session,
    *,
    top_k: int = 8,
    author_id: Optional[str] = None,
    domains: Optional[list[str]] = None,
    expertise_tags: Optional[list[str]] = None,
) -> QueryResult:
    """
    Author-aware grounded question answering.

    Selects relevant authors, retrieves evidence, and synthesizes a short
    grounded answer (LLM if available, otherwise returns evidence summary).
    """
    _t0 = time.monotonic()
    selected = select_authors(
        query, db,
        author_id=author_id,
        domains=domains,
        expertise_tags=expertise_tags,
        top_k=4,
    )
    selected_author_ids = [author.author_id for author in selected]
    selected_author_names = [author.name for author in selected]
    hardening_active = retrieval_hardening_enabled()
    trace_retrieval_payload(
        "query_selected_authors",
        {
            "query": query,
            "mode": "ask",
            "selected_author_ids": selected_author_ids,
            "selected_author_names": selected_author_names,
            "hardening_enabled": hardening_active,
        },
    )

    if hardening_active:
        chunks = retrieve_hybrid(
            query,
            db,
            top_k=top_k,
            author_id=author_id,
            author_ids=None if author_id else selected_author_ids,
            source_author_names=selected_author_names,
            domains=domains,
            expertise_tags=expertise_tags,
            hardening_enabled=True,
        )
    else:
        chunks = retrieve_similar_chunks(
            query,
            db,
            top_k=top_k,
            author_id=author_id,
            author_ids=None if author_id else selected_author_ids,
            domains=domains,
            expertise_tags=expertise_tags,
        )

    author_entries = _author_entries(selected, db)
    author_map = {entry["author_id"]: entry["name"] for entry in author_entries}
    evidence, evidence_audit = _prepare_evidence_pack(
        chunks,
        db,
        author_map,
        query_text=query,
        hardening_enabled=hardening_active,
    )
    author_names = [a.name for a in selected]

    answer: Optional[str] = None
    missing: Optional[str] = None

    if not chunks:
        missing = "No corpus evidence found. Cannot provide a grounded answer."
    elif inference_available():
        try:
            answer = _synthesize_answer(query, [e.text for e in evidence], author_names)
        except Exception as exc:
            log.warning("LLM synthesis failed: %s", exc)
            answer = _evidence_summary(evidence)
    else:
        answer = _evidence_summary(evidence)

    result = QueryResult(
        query=query,
        mode="ask",
        selected_authors=author_entries,
        evidence_chunks=[e.as_dict() for e in evidence],
        answer=answer,
        missing_information=missing,
        evidence_sufficient=len(chunks) > 0,
    )
    _log_query_async(
        db, query, "ask",
        evidence=evidence,
        answer_text=answer,
        latency_ms=int((time.monotonic() - _t0) * 1000),
        retrieval_config={
            "top_k": top_k,
            "retrieval_hardening_enabled": hardening_active,
            "retrieval_path": "hybrid_parent_child" if hardening_active else "dense_legacy",
            **evidence_audit,
        },
    )
    return result


def execute_company_context(
    company: str,
    question: str,
    db: Session,
    *,
    top_k: int = 8,
) -> CompanyContextResult:
    """
    Prepare a company analysis context.

    Retrieves corpus evidence relevant to the company/question and returns
    which author lenses are most likely relevant.
    """
    combined_query = f"{company} {question}"

    selected = select_authors(combined_query, db, top_k=5)
    selected_author_ids = [author.author_id for author in selected]
    selected_author_names = [author.name for author in selected]

    hardening_active = retrieval_hardening_enabled()
    trace_retrieval_payload(
        "query_selected_authors",
        {
            "query": combined_query,
            "mode": "company_context",
            "selected_author_ids": selected_author_ids,
            "selected_author_names": selected_author_names,
            "hardening_enabled": hardening_active,
        },
    )
    if hardening_active:
        chunks = retrieve_hybrid(
            combined_query,
            db,
            top_k=top_k,
            author_ids=selected_author_ids,
            source_author_names=selected_author_names,
            hardening_enabled=True,
        )
    else:
        chunks = retrieve_similar_chunks(
            combined_query,
            db,
            top_k=top_k,
            author_ids=selected_author_ids,
        )

    author_entries = _author_entries(selected, db)
    author_map = {entry["author_id"]: entry["name"] for entry in author_entries}
    evidence, _evidence_audit = _prepare_evidence_pack(
        chunks,
        db,
        author_map,
        query_text=combined_query,
        hardening_enabled=hardening_active,
    )

    return CompanyContextResult(
        company=company,
        question=question,
        relevant_author_lenses=author_entries,
        evidence_pack=[e.as_dict() for e in evidence],
        evidence_sufficient=len(chunks) > 0,
    )


# ── Private helpers ───────────────────────────────────────────────────────────


def _author_dict(a: SelectedAuthor) -> dict:
    return {
        "author_id": a.author_id,
        "name": a.name,
        "score": a.score,
        "domains": a.domains,
        "expertise_tags": a.expertise_tags,
        "match_reason": a.match_reason,
    }


def _author_entries(selected: list[SelectedAuthor], db: Session) -> list[dict]:
    entries: list[dict] = []
    for author in selected:
        entry = _author_dict(author)
        profile = db.query(RagAuthorProfile).filter(
            RagAuthorProfile.author_id == author.author_id
        ).first()
        if profile:
            entry["worldview"] = profile.worldview
            entry["key_maxims"] = list(profile.key_maxims or [])
            entry["favored_decision_variables"] = list(
                profile.favored_decision_variables or []
            )
        entries.append(entry)
    return entries


def _prepare_evidence_pack(
    chunks: list[RetrievedChunk],
    db: Session,
    author_map: dict[str, str],
    *,
    query_text: str = "",
    hardening_enabled: bool,
) -> tuple[list[EvidenceChunk], dict[str, Any]]:
    delivered_chunks = chunks
    duplicates_suppressed: list[dict[str, Any]] = []

    if hardening_enabled:
        delivered_chunks = deliver_parent_sections(chunks, db, only_when_needed=False)
        trace_retrieval_chunks("delivery_parent_child", query_text, delivered_chunks, extra={"input_count": len(chunks)})
        delivered_chunks, duplicates_suppressed = suppress_near_duplicates(delivered_chunks)
        trace_retrieval_chunks(
            "delivery_after_duplicate_suppression",
            query_text,
            delivered_chunks,
            extra={
                "input_count": len(chunks),
                "duplicates_suppressed_count": len(duplicates_suppressed),
                "duplicates_suppressed": duplicates_suppressed,
            },
        )
        trace_retrieval_payload(
            "delivery_summary",
            {
                "query": query_text,
                "retrieved_child_count": len(chunks),
                "delivered_evidence_count": len(delivered_chunks),
                "duplicates_suppressed_count": len(duplicates_suppressed),
            },
        )

    evidence = _enrich_chunks(delivered_chunks, db, author_map)
    return evidence, {
        "retrieved_child_count": len(chunks),
        "delivered_evidence_count": len(evidence),
        "parent_child_delivery_enabled": hardening_enabled,
        "duplicates_suppressed": duplicates_suppressed,
        "duplicates_suppressed_count": len(duplicates_suppressed),
    }


def _enrich_chunks(
    chunks: list[RetrievedChunk],
    db: Session,
    author_map: dict[str, str],
) -> list[EvidenceChunk]:
    """Enrich retrieved chunks with author identifiers from metadata."""
    result = []
    for c in chunks:
        meta = c.metadata_json or {}
        author_id = meta.get("author_id", "unknown")
        author_name = author_map.get(author_id) or meta.get("author_name", "unknown")
        result.append(
            EvidenceChunk(
                chunk_id=c.chunk_id,
                author_id=author_id,
                author_name=author_name,
                text=c.text,
                similarity=c.similarity,
                metadata=meta,
                document_id=getattr(c, "document_id", None),
                ranking_score=float(c.weighted_score if c.weighted_score is not None else (c.base_score if c.base_score is not None else c.similarity)),
                score_type=str(meta.get("score_type", "retrieved")),
            )
        )
    return result


def _evidence_summary(evidence: list[EvidenceChunk]) -> str:
    """Build a plain-text summary from evidence chunks (no LLM)."""
    if not evidence:
        return "No evidence available."
    lines = []
    for i, e in enumerate(evidence[:5], 1):
        snippet = e.text[:200].replace("\n", " ").strip()
        lines.append(f"{i}. [{e.author_name}] {snippet}...")
    return "Evidence summary:\n" + "\n".join(lines)


def _log_query_async(
    db: Session,
    query_text: str,
    mode: str,
    *,
    evidence: list[EvidenceChunk],
    answer_text: Optional[str] = None,
    latency_ms: int = 0,
    retrieval_config: Optional[dict] = None,
    intent: Optional[dict] = None,
) -> None:
    """Fire-and-forget audit log. Failures are swallowed."""
    try:
        from app.rag.query_logger import log_query

        evidence_dicts = [
            {
                "chunk_id": e.chunk_id,
                "cosine_distance": 1.0 - e.similarity,
            }
            for e in evidence
        ]
        log_query(
            db,
            query_text,
            mode,
            intent=intent,
            evidence_chunks=evidence_dicts,
            answer_text=answer_text,
            latency_ms=latency_ms,
            retrieval_config=retrieval_config,
        )
    except Exception as exc:
        log.debug("audit log skipped: %s", exc)
