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
import os
import textwrap
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.rag import RagAuthorProfile
from app.rag.author_selection import SelectedAuthor, select_authors
from app.rag.retrieval import RetrievedChunk, retrieve_similar_chunks

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

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "author_id": self.author_id,
            "author_name": self.author_name,
            "text": self.text,
            "similarity": self.similarity,
            "metadata": self.metadata,
        }


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


def _llm_available() -> bool:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return False
    try:
        import openai  # noqa: F401
        return True
    except ImportError:
        return False


def _synthesize_answer(query: str, evidence_texts: list[str], author_names: list[str]) -> str:
    """Use OpenAI to synthesize a short grounded answer from evidence."""
    import openai

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

    client = openai.OpenAI()
    response = client.chat.completions.create(
        model=os.getenv("RAG_LLM_MODEL", "gpt-4o-mini"),
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
    selected = select_authors(
        query, db,
        author_id=author_id,
        domains=domains,
        expertise_tags=expertise_tags,
        top_k=4,
    )

    chunks = retrieve_similar_chunks(
        query,
        db,
        top_k=top_k,
        author_id=author_id,
    )

    # Enrich chunks with author info
    author_map = {a.author_id: a.name for a in selected}
    evidence = _enrich_chunks(chunks, db, author_map)

    return QueryResult(
        query=query,
        mode="retrieve",
        selected_authors=[_author_dict(a) for a in selected],
        evidence_chunks=[e.as_dict() for e in evidence],
        answer=None,
        missing_information=None if chunks else "No corpus evidence found for this query.",
        evidence_sufficient=len(chunks) > 0,
    )


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
    selected = select_authors(
        query, db,
        author_id=author_id,
        domains=domains,
        expertise_tags=expertise_tags,
        top_k=4,
    )

    chunks = retrieve_similar_chunks(
        query,
        db,
        top_k=top_k,
        author_id=author_id,
    )

    author_map = {a.author_id: a.name for a in selected}
    evidence = _enrich_chunks(chunks, db, author_map)
    author_names = [a.name for a in selected]

    answer: Optional[str] = None
    missing: Optional[str] = None

    if not chunks:
        missing = "No corpus evidence found. Cannot provide a grounded answer."
    elif _llm_available():
        try:
            answer = _synthesize_answer(query, [c.text for c in chunks], author_names)
        except Exception as exc:
            log.warning("LLM synthesis failed: %s", exc)
            answer = _evidence_summary(evidence)
    else:
        answer = _evidence_summary(evidence)

    return QueryResult(
        query=query,
        mode="ask",
        selected_authors=[_author_dict(a) for a in selected],
        evidence_chunks=[e.as_dict() for e in evidence],
        answer=answer,
        missing_information=missing,
        evidence_sufficient=len(chunks) > 0,
    )


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

    chunks = retrieve_similar_chunks(
        combined_query,
        db,
        top_k=top_k,
    )

    author_map = {a.author_id: a.name for a in selected}
    evidence = _enrich_chunks(chunks, db, author_map)

    # Build author lens cards with profile data if available
    author_lenses = []
    for author in selected:
        profile = db.query(RagAuthorProfile).filter(
            RagAuthorProfile.author_id == author.author_id
        ).first()
        lens_entry = _author_dict(author)
        if profile:
            lens_entry["worldview"] = profile.worldview
            lens_entry["key_maxims"] = list(profile.key_maxims or [])
            lens_entry["favored_decision_variables"] = list(profile.favored_decision_variables or [])
        author_lenses.append(lens_entry)

    return CompanyContextResult(
        company=company,
        question=question,
        relevant_author_lenses=author_lenses,
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
