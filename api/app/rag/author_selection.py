"""
Dynamic author selection for RAG query routing.

Selects the most relevant authors for a given query based on:
  - domain matching
  - expertise tag overlap
  - configured overall_weight
  - optional author_id filter

Authors come from rag_authors table (populated from config/rag_authors.yaml).
No author is hardcoded as mandatory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from app.models.rag import RagAuthor

log = logging.getLogger(__name__)

# Domain synonyms for loose query→domain matching
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "investing": ["invest", "stock", "equity", "portfolio", "valuation", "return", "capital", "shareholder"],
    "business": ["business", "company", "moat", "competitive", "market", "customer", "operator"],
    "macro": ["macro", "economy", "interest", "inflation", "cycle", "credit", "recession"],
    "technology": ["tech", "software", "platform", "product", "saas", "ai", "digital", "aggregation"],
    "strategy": ["strategy", "strategic", "disruption", "positioning", "competitive"],
    "decision_making": ["decision", "mental model", "thinking", "framework", "bias", "heuristic"],
    "psychology": ["psychology", "behaviour", "incentive", "emotion", "bias"],
    "finance": ["finance", "financial", "derivative", "regulation", "law", "structure"],
    "product": ["product", "user", "ux", "design", "consumer"],
}


@dataclass
class SelectedAuthor:
    author_id: str
    name: str
    score: float
    domains: list[str]
    expertise_tags: list[str]
    overall_weight: float
    role_type: Optional[str]
    match_reason: list[str] = field(default_factory=list)


def _query_domains(query: str) -> set[str]:
    """Infer which domain keywords appear in the query text."""
    q = query.lower()
    matched: set[str] = set()
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            matched.add(domain)
    return matched


def _score_author(author: RagAuthor, query: str, inferred_domains: set[str]) -> tuple[float, list[str]]:
    """
    Compute a relevance score for an author relative to a query.

    Score components:
      - 2.0 per matching domain (exact author domain present in inferred query domains)
      - 1.0 per matching expertise tag keyword found in query text
      - overall_weight (0-5) as a base float added at the end

    Returns (score, reasons).
    """
    score = 0.0
    reasons: list[str] = []
    q = query.lower()

    author_domains = set(author.domains or [])
    domain_hits = author_domains & inferred_domains
    if domain_hits:
        score += 2.0 * len(domain_hits)
        reasons.append(f"domain_match:{','.join(sorted(domain_hits))}")

    tag_hits = [tag for tag in (author.expertise_tags or []) if tag.replace("_", " ").lower() in q or tag.lower() in q]
    if tag_hits:
        score += 1.0 * len(tag_hits)
        reasons.append(f"tag_match:{','.join(tag_hits[:3])}")

    # overall_weight is 0-5; treat it as a continuous bonus
    score += author.overall_weight * 0.5
    return score, reasons


def select_authors(
    query: str,
    db: Session,
    *,
    author_id: Optional[str] = None,
    domains: Optional[list[str]] = None,
    expertise_tags: Optional[list[str]] = None,
    top_k: int = 4,
    min_score: float = 0.5,
) -> list[SelectedAuthor]:
    """
    Dynamically select the most relevant enabled authors for a query.

    Args:
        query:         The free-text query or topic.
        db:            Database session.
        author_id:     If provided, return only that author (if enabled).
        domains:       Explicit domain filter; if provided, only authors in these domains.
        expertise_tags: Explicit tag filter; boost authors that match.
        top_k:         Maximum number of authors to return.
        min_score:     Minimum score to be included.

    Returns a ranked list of SelectedAuthor instances.
    """
    q = db.query(RagAuthor).filter(RagAuthor.enabled == True)  # noqa: E712

    if author_id:
        q = q.filter(RagAuthor.id == author_id)
    if domains:
        # Keep authors whose domain list overlaps with the requested domains
        from sqlalchemy import or_, func
        domain_conditions = [RagAuthor.domains.any(d) for d in domains]
        q = q.filter(or_(*domain_conditions))

    authors = q.all()
    if not authors:
        return []

    inferred_domains = _query_domains(query)
    if domains:
        inferred_domains |= set(domains)

    scored: list[tuple[float, RagAuthor, list[str]]] = []
    for author in authors:
        score, reasons = _score_author(author, query, inferred_domains)
        # Apply explicit expertise_tags boost
        if expertise_tags:
            tag_overlap = set(expertise_tags) & set(author.expertise_tags or [])
            if tag_overlap:
                score += 2.0 * len(tag_overlap)
                reasons.append(f"explicit_tag:{','.join(sorted(tag_overlap))}")
        scored.append((score, author, reasons))

    scored.sort(key=lambda t: -t[0])

    results: list[SelectedAuthor] = []
    for score, author, reasons in scored[:top_k]:
        if score < min_score:
            continue
        results.append(
            SelectedAuthor(
                author_id=author.id,
                name=author.name,
                score=round(score, 3),
                domains=list(author.domains or []),
                expertise_tags=list(author.expertise_tags or []),
                overall_weight=author.overall_weight,
                role_type=author.role_type,
                match_reason=reasons,
            )
        )

    return results
