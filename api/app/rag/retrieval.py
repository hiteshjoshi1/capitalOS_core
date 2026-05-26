"""
Semantic retrieval layer for RAG Phase 1 + Phase 2.

Provides semantic similarity search over stored embeddings using pgvector's
cosine distance operator (<=>).  Supports author, domain, and expertise-tag
filters for Phase 2 author-aware retrieval.

Also provides sparse/keyword retrieval via Postgres full-text search
(tsvector/tsquery) and hybrid retrieval combining both via Reciprocal Rank
Fusion (RRF).

Returns citation-ready payloads with full metadata lineage.

Constraint-aware retrieval (Issue 145):
- retrieve_with_constraints(): strict no-fallback retrieval
- All retrieval paths accept year_from/year_to (int) and published_from/published_to (YYYY-MM-DD)
- Date filters prefer rag_documents.published_at where available (Postgres only)
- ConstrainedRetrievalResult exposes what constraints were applied vs requested
"""

from __future__ import annotations

from collections import Counter
import difflib
import json
import logging
import os
import re
from dataclasses import dataclass, field, replace
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.rag import RagChunk, RagDocument
from app.rag.ingestion.embedder import embed_query
from app.rag.retrieval_weighting import (
    apply_weight_to_score,
    merge_retrieval_metadata,
    metadata_weighting_enabled,
    ranking_sort_key,
    weighting_candidate_limit,
    weighting_feature_flag,
)

log = logging.getLogger(__name__)

SMOKE_DEFAULT_TOP_K = 5
DEFAULT_TOP_K = 5

# ── Env-driven retrieval config ───────────────────────────────────────────────
_RETRIEVAL_MODE = os.getenv("RAG_RETRIEVAL_MODE", "hybrid")
_RRF_K = int(os.getenv("RAG_RETRIEVAL_RRF_K", "60"))
_DENSE_TOP_K_MULTIPLIER = int(os.getenv("RAG_RETRIEVAL_DENSE_TOP_K_MULTIPLIER", "3"))
_RETRIEVAL_HARDENING_DEFAULT = os.getenv("RAG_RETRIEVAL_HARDENING", "1") == "1"
_NEAR_DUPLICATE_THRESHOLD = float(os.getenv("RAG_RETRIEVAL_NEAR_DUPLICATE_THRESHOLD", "0.92"))
_PARENT_CHILD_WINDOW = int(os.getenv("RAG_PARENT_CHILD_WINDOW", "4"))
_HARDENED_MIN_CANDIDATE_POOL = int(os.getenv("RAG_RETRIEVAL_HARDENED_MIN_CANDIDATES", "60"))
_RETRIEVAL_TRACE_ENV = "RAG_RETRIEVAL_TRACE"
_TRACE_TEXT_LIMIT = int(os.getenv("RAG_RETRIEVAL_TRACE_TEXT_LIMIT", "260"))

_TRANSCRIPT_HINT_RE = re.compile(
    r"\b(?:transcript|q&a|q and a|question(?:s)?|answer(?:s)?|earnings call|shareholder meeting)\b",
    re.IGNORECASE,
)
_SPARSE_GENERIC_TERMS = {
    "what",
    "when",
    "where",
    "which",
    "does",
    "did",
    "about",
    "from",
    "with",
    "on",
    "into",
    "through",
    "around",
    "letters",
    "letter",
    "essay",
    "essays",
    "report",
    "reports",
    "speech",
    "speeches",
    "transcript",
    "transcripts",
}
_QUERY_SCAFFOLDING_TERMS = {
    *list(_SPARSE_GENERIC_TERMS),
    "a",
    "an",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "do",
    "for",
    "has",
    "have",
    "he",
    "her",
    "his",
    "how",
    "it",
    "its",
    "mean",
    "means",
    "said",
    "say",
    "saying",
    "says",
    "live",
    "lived",
    "lives",
    "living",
    "me",
    "of",
    "ones",
    "some",
    "that",
    "the",
    "their",
    "them",
    "they",
    "think",
    "thinking",
    "thinks",
    "thought",
    "thoughts",
    "view",
    "views",
    "we",
    "who",
    "why",
}
_SOURCE_TYPE_TERMS_RE = re.compile(
    r"\b(?:letters?|essays?|memos?|reports?|transcripts?|speeches?|pdfs?|"
    r"writings?|articles?|annual\s+reports?)\b",
    re.IGNORECASE,
)
_KNOWN_CONCEPT_PHRASES = (
    "mental models",
    "circle of competence",
    "margin of safety",
    "pricing power",
    "intrinsic value",
    "share buybacks",
    "second level thinking",
    "scale economies shared",
    "business model",
)
_CONCEPT_EXPANSIONS = {
    "mental models": [
        "latticework",
        "inversion",
        "invert",
        "backward",
        "mental trick",
        "incentives",
        "disincentives",
        "incentive-caused",
        "reward and punishment",
        "reward superresponse",
        "operant conditioning",
        "conditioning",
        "conditioned reflex",
        "pavlovian",
        "classical conditioning",
        "psychology",
        "social proof",
        "authority",
        "authority bias",
        "milgram",
        "availability",
        "availability bias",
        "misweighing",
        "envy",
        "jealousy",
        "reciprocation",
        "deprival superreaction",
        "principles",
        "multidisciplinary",
        "discipline",
        "disciplines",
        "microeconomics",
        "physiology",
        "mathematics",
        "hard science",
        "engineering",
        "critical mass",
        "lollapalooza",
        "margin of safety",
        "checklist",
        "models",
    ],
}
_CONCEPT_ASPECTS = {
    "mental models": {
        "latticework": ["latticework", "multidisciplinary", "disciplines"],
        "inversion": ["inversion", "invert", "backward", "mental trick"],
        "incentives": [
            "incentives",
            "disincentives",
            "incentive-caused",
            "reward and punishment",
            "reward superresponse",
        ],
        "conditioning": [
            "operant conditioning",
            "conditioning",
            "conditioned reflex",
            "pavlovian",
            "classical conditioning",
        ],
        "biases": [
            "social proof",
            "authority",
            "authority bias",
            "availability",
            "availability bias",
            "envy",
            "jealousy",
            "reciprocation",
            "deprival superreaction",
            "misweighing",
            "milgram",
        ],
        "economics_and_science": [
            "microeconomics",
            "physiology",
            "mathematics",
            "hard science",
            "engineering",
        ],
        "critical_mass": ["critical mass", "lollapalooza"],
        "risk_safety": ["margin of safety", "checklist"],
    },
}
_DOMAIN_FEEDBACK_TERMS = {
    "authority",
    "availability",
    "backward",
    "bias",
    "checklist",
    "classical conditioning",
    "conditioning",
    "conditioned reflex",
    "critical mass",
    "deprival superreaction",
    "discipline",
    "disciplines",
    "disincentives",
    "engineering",
    "envy",
    "hard science",
    "incentive-caused",
    "incentives",
    "invert",
    "inversion",
    "jealousy",
    "latticework",
    "lollapalooza",
    "margin of safety",
    "mathematics",
    "microeconomics",
    "milgram",
    "misjudgment",
    "misweighing",
    "operant conditioning",
    "pavlovian",
    "physiology",
    "principles",
    "psychology",
    "reciprocation",
    "reward and punishment",
    "reward superresponse",
    "social proof",
    "tendencies",
    "tendency",
}
_FEEDBACK_STOPWORDS = {
    *_QUERY_SCAFFOLDING_TERMS,
    "also",
    "another",
    "actual",
    "after",
    "around",
    "because",
    "being",
    "before",
    "believed",
    "better",
    "berkshire",
    "buffett",
    "business",
    "businesses",
    "certain",
    "charlie",
    "cognition",
    "come",
    "comes",
    "could",
    "didn",
    "djco",
    "doesn",
    "don",
    "elementary",
    "enhances",
    "example",
    "fact",
    "financial",
    "first",
    "general",
    "good",
    "great",
    "gradually",
    "hang",
    "hathaway",
    "head",
    "important",
    "just",
    "know",
    "learn",
    "lesson",
    "life",
    "like",
    "made",
    "make",
    "most",
    "munger",
    "need",
    "other",
    "people",
    "particularly",
    "person",
    "powerful",
    "really",
    "reading",
    "revisited",
    "said",
    "same",
    "school",
    "something",
    "system",
    "talk",
    "talks",
    "than",
    "there",
    "thing",
    "things",
    "think",
    "this",
    "through",
    "today",
    "together",
    "used",
    "using",
    "want",
    "well",
    "warren",
    "wesco",
    "world",
    "worldly",
    "would",
    "wisdom",
    "your",
}


def retrieval_trace_enabled() -> bool:
    raw = os.getenv(_RETRIEVAL_TRACE_ENV, "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _json_default(value: Any) -> str:
    return str(value)


def trace_retrieval_payload(stage: str, payload: dict[str, Any]) -> None:
    if not retrieval_trace_enabled():
        return
    print(f"\n-------------- RAG RETRIEVAL TRACE: {stage} --------------", flush=True)
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=_json_default), flush=True)
    print("-------------- END RAG RETRIEVAL TRACE --------------\n", flush=True)


def _trace_chunk_item(rank: int, chunk: "RetrievedChunk") -> dict[str, Any]:
    metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
    diagnostics = metadata.get("retrieval_diagnostics") if isinstance(metadata.get("retrieval_diagnostics"), dict) else {}
    plan = metadata.get("retrieval_query_plan") if isinstance(metadata.get("retrieval_query_plan"), dict) else {}

    def safe_number(value: Any) -> Any:
        if isinstance(value, (int, float)):
            return round(float(value), 6)
        return value

    def safe_similarity() -> Any:
        try:
            return safe_number(chunk.similarity)
        except Exception:
            cosine_distance = getattr(chunk, "cosine_distance", None)
            if isinstance(cosine_distance, (int, float)) and cosine_distance < 1.0:
                return round(1.0 - float(cosine_distance), 6)
            return None

    return {
        "rank": rank,
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "chunk_index": chunk.chunk_index,
        "document_title": metadata.get("document_title") or metadata.get("title"),
        "source_section": metadata.get("source_section"),
        "source_url": metadata.get("source_url"),
        "similarity": safe_similarity(),
        "cosine_distance": safe_number(getattr(chunk, "cosine_distance", None)),
        "ts_rank": safe_number(getattr(chunk, "ts_rank", None)),
        "rrf_score": safe_number(getattr(chunk, "rrf_score", None)),
        "reranker_score": safe_number(getattr(chunk, "reranker_score", None)),
        "base_score": safe_number(getattr(chunk, "base_score", None)),
        "weighted_score": safe_number(getattr(chunk, "weighted_score", None)),
        "pool_memberships": diagnostics.get("pool_memberships"),
        "phrase_hits": diagnostics.get("phrase_hits"),
        "concept_term_hits": diagnostics.get("concept_term_hits"),
        "aspect_hits": diagnostics.get("aspect_hits"),
        "score_components": diagnostics.get("score_components"),
        "diversity": diagnostics.get("diversity"),
        "content_query": plan.get("content_query"),
        "sparse_query": plan.get("sparse_query"),
        "text": str(chunk.text or "").replace("\n", " ")[:_TRACE_TEXT_LIMIT],
    }


def trace_retrieval_chunks(
    stage: str,
    query: str,
    chunks: list["RetrievedChunk"],
    *,
    limit: int = 12,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    payload: dict[str, Any] = {
        "query": query,
        "chunk_count": len(chunks),
        "shown": min(len(chunks), limit),
        "chunks": [_trace_chunk_item(index, chunk) for index, chunk in enumerate(chunks[:limit], start=1)],
    }
    if extra:
        payload["extra"] = extra
    trace_retrieval_payload(stage, payload)


@dataclass(frozen=True)
class RetrievalQueryPlan:
    raw_query: str
    content_query: str
    sparse_query: str
    source_author_ids: list[str] = field(default_factory=list)
    source_author_names: list[str] = field(default_factory=list)
    required_phrases: list[str] = field(default_factory=list)
    concept_terms: list[str] = field(default_factory=list)
    removed_source_author_terms: list[str] = field(default_factory=list)
    topic_entities: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_query": self.raw_query,
            "content_query": self.content_query,
            "sparse_query": self.sparse_query,
            "source_author_ids": list(self.source_author_ids),
            "source_author_names": list(self.source_author_names),
            "required_phrases": list(self.required_phrases),
            "concept_terms": list(self.concept_terms),
            "removed_source_author_terms": list(self.removed_source_author_terms),
            "topic_entities": list(self.topic_entities),
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(frozen=True)
class SparseQueryPlan:
    search_query: str
    exact_phrases: list[str] = field(default_factory=list)
    entity_terms: list[str] = field(default_factory=list)
    year_terms: list[str] = field(default_factory=list)
    transcript_sensitive: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "search_query": self.search_query,
            "exact_phrases": list(self.exact_phrases),
            "entity_terms": list(self.entity_terms),
            "year_terms": list(self.year_terms),
            "transcript_sensitive": self.transcript_sensitive,
        }


@dataclass
class ConstrainedRetrievalResult:
    """
    Result of a constraint-aware retrieval operation.

    Tracks which constraints were requested, which were actually applied,
    and whether any were relaxed (and why).  Diagnostics are opt-in via
    the ``debug`` parameter on ``retrieve_with_constraints()``.
    """

    chunks: list["RetrievedChunk"]
    constraints_requested: dict[str, Any]
    constraints_applied: dict[str, Any]
    constraints_relaxed: bool = False
    constraint_relaxation_reason: Optional[str] = None
    diagnostics: Optional[dict[str, Any]] = None

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "constraints_requested": self.constraints_requested,
            "constraints_applied": self.constraints_applied,
            "constraints_relaxed": self.constraints_relaxed,
            "constraint_relaxation_reason": self.constraint_relaxation_reason,
            "evidence_chunks": [c.as_dict() for c in self.chunks],
        }
        if self.diagnostics is not None:
            d["diagnostics"] = self.diagnostics
        return d


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    chunk_index: int
    text: str
    token_count: Optional[int]
    metadata_json: dict[str, Any]
    cosine_distance: float
    ts_rank: Optional[float] = None
    rrf_score: Optional[float] = None
    reranker_score: Optional[float] = None
    metadata_weight: float = 1.0
    base_score: Optional[float] = None
    weighted_score: Optional[float] = None
    corpus_class: Optional[str] = None
    weighting_applied: bool = False

    @property
    def similarity(self) -> float:
        """Cosine similarity (1 - distance), or a normalized score for keyword/RRF results."""
        if self.cosine_distance < 1.0:
            return round(1.0 - self.cosine_distance, 6)
        # Keyword-only or RRF-merged chunk without dense score
        if self.rrf_score is not None:
            # RRF scores are small (typically 0.01-0.03); normalize to 0-1 range
            return round(min(self.rrf_score * 30, 1.0), 6)
        if self.ts_rank is not None:
            # ts_rank is typically 0-1 already but can exceed 1
            return round(min(self.ts_rank, 1.0), 6)
        return 0.0

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "token_count": self.token_count,
            "similarity": self.similarity,
            "metadata": self.metadata_json,
        }
        if self.ts_rank is not None:
            d["ts_rank"] = self.ts_rank
        if self.rrf_score is not None:
            d["rrf_score"] = self.rrf_score
        if self.reranker_score is not None:
            d["reranker_score"] = self.reranker_score
        if self.metadata_weight != 1.0:
            d["metadata_weight"] = self.metadata_weight
        if self.base_score is not None:
            d["base_score"] = self.base_score
        if self.weighted_score is not None:
            d["weighted_score"] = self.weighted_score
        if self.corpus_class is not None:
            d["corpus_class"] = self.corpus_class
        if self.weighting_applied:
            d["weighting_applied"] = True
        return d


def retrieval_hardening_enabled(*, override: Optional[bool] = None) -> bool:
    if override is not None:
        return override
    return _RETRIEVAL_HARDENING_DEFAULT


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _known_author_terms_for_ids(author_ids: list[str]) -> list[str]:
    try:
        from app.rag.intent_router import _KNOWN_AUTHORS
    except Exception:
        return []
    terms = [name for name, aid in _KNOWN_AUTHORS.items() if aid in set(author_ids)]
    return _dedupe_preserve_order(sorted((term.title() for term in terms), key=len, reverse=True))


def _parse_source_author_intent(query: str) -> tuple[list[str], list[str], list[str]]:
    try:
        from app.rag.intent_router import parse_intent_from_text

        intent = parse_intent_from_text(query)
        return list(intent.author_ids or []), list(intent.author_names or []), list(intent.topic_entities or [])
    except Exception:
        return [], [], []


def _extract_discussed_entities_for_plan(
    raw_query: str,
    *,
    author_ids: list[str],
    author_names: list[str],
    topics: list[str],
) -> list[str]:
    try:
        from app.rag.intent_router import _extract_discussed_entities

        return _extract_discussed_entities(
            raw_query,
            source_author_ids=author_ids,
            source_author_names=author_names,
            existing_topics=topics,
        )
    except Exception:
        return topics


def _remove_source_author_terms(query: str, author_terms: list[str]) -> tuple[str, list[str]]:
    cleaned = query
    removed: list[str] = []
    for term in sorted(_dedupe_preserve_order(author_terms), key=len, reverse=True):
        pattern = r"\b" + re.escape(term) + r"(?:['’]s)?\b"
        updated = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
        if updated != cleaned:
            removed.append(term)
            cleaned = updated
    return cleaned, removed


def _normalize_content_query(query: str) -> str:
    cleaned = _SOURCE_TYPE_TERMS_RE.sub(" ", query)
    cleaned = re.sub(r"\b(?:19|20)\d{2}\b", " ", cleaned)
    cleaned = re.sub(r"['’]s\b", " ", cleaned)
    cleaned = re.sub(r"[^A-Za-z0-9&./'\-\s]", " ", cleaned)
    tokens = [
        token.strip("'’").lower()
        for token in re.split(r"\s+", cleaned)
        if token.strip("'’")
    ]
    kept = [
        token
        for token in tokens
        if token not in _QUERY_SCAFFOLDING_TERMS and len(token) > 1
    ]
    return " ".join(kept).strip()


def _extract_required_phrases(raw_query: str, content_query: str) -> list[str]:
    phrases = [
        phrase.strip().lower()
        for phrase in re.findall(r'"([^"]{2,160})"', raw_query)
        if phrase.strip()
    ]
    haystack = f"{raw_query} {content_query}".lower()
    for phrase in _KNOWN_CONCEPT_PHRASES:
        if phrase in haystack:
            phrases.append(phrase)
    return _dedupe_preserve_order(phrases)


def _build_concept_terms(content_query: str, required_phrases: list[str]) -> list[str]:
    terms: list[str] = list(required_phrases)
    phrase_tokens = {
        token
        for phrase in required_phrases
        for token in re.findall(r"[a-z0-9]+", phrase.lower())
    }
    for token in re.findall(r"[a-z0-9][a-z0-9'&./-]*", content_query.lower()):
        if token in _QUERY_SCAFFOLDING_TERMS or len(token) <= 1:
            continue
        if token in phrase_tokens:
            continue
        terms.append(token)
    for phrase in required_phrases:
        terms.extend(_CONCEPT_EXPANSIONS.get(phrase.lower(), []))
    return _dedupe_preserve_order(terms)


def _build_sparse_query(required_phrases: list[str], concept_terms: list[str], content_query: str) -> str:
    parts: list[str] = []
    phrase_tokens = {
        token
        for phrase in required_phrases
        for token in re.findall(r"[a-z0-9]+", phrase.lower())
    }
    for phrase in required_phrases:
        parts.append(f'"{phrase}"')
    for term in concept_terms:
        term_key = term.lower()
        if term_key in {phrase.lower() for phrase in required_phrases}:
            continue
        if term_key in phrase_tokens:
            continue
        parts.append(term)
    if parts:
        return " OR ".join(_dedupe_preserve_order(parts))
    return content_query


def build_retrieval_query_plan(
    query: str,
    *,
    source_author_ids: Optional[list[str]] = None,
    source_author_names: Optional[list[str]] = None,
    topic_entities: Optional[list[str]] = None,
) -> RetrievalQueryPlan:
    raw_query = (query or "").strip()
    parsed_author_ids: list[str] = []
    parsed_author_names: list[str] = []
    parsed_topic_entities: list[str] = []
    if not source_author_ids and not source_author_names:
        parsed_author_ids, parsed_author_names, parsed_topic_entities = _parse_source_author_intent(raw_query)

    author_ids = _dedupe_preserve_order(list(source_author_ids or parsed_author_ids))
    author_names = _dedupe_preserve_order(list(source_author_names or parsed_author_names))
    topics = _dedupe_preserve_order(list(topic_entities or parsed_topic_entities))
    topics = _dedupe_preserve_order(
        _extract_discussed_entities_for_plan(
            raw_query,
            author_ids=author_ids,
            author_names=author_names,
            topics=topics,
        )
    )

    author_terms = _dedupe_preserve_order(
        [
            *author_names,
            *_known_author_terms_for_ids(author_ids),
        ]
    )
    without_authors, removed_terms = _remove_source_author_terms(raw_query, author_terms)
    content_query = _normalize_content_query(without_authors)
    if topics:
        topic_text = _normalize_content_query(" ".join(topics))
        if topic_text and topic_text.lower() not in content_query.lower():
            content_query = f"{content_query} {topic_text}".strip()
    if not content_query:
        content_query = _normalize_content_query(raw_query) or raw_query

    required_phrases = _extract_required_phrases(raw_query, content_query)
    concept_terms = _build_concept_terms(content_query, required_phrases)
    sparse_query = _build_sparse_query(required_phrases, concept_terms, content_query)

    return RetrievalQueryPlan(
        raw_query=raw_query,
        content_query=content_query,
        sparse_query=sparse_query,
        source_author_ids=author_ids,
        source_author_names=author_names,
        required_phrases=required_phrases,
        concept_terms=concept_terms,
        removed_source_author_terms=removed_terms,
        topic_entities=topics,
        diagnostics={
            "author_terms_considered": author_terms,
            "content_query_source": "source_author_stripped" if removed_terms else "raw_query",
            "strict_source_author_filter": len(author_ids) == 1,
        },
    )


def build_sparse_query_plan(query: str) -> SparseQueryPlan:
    raw_query = (query or "").strip()
    if not raw_query:
        return SparseQueryPlan(search_query="")

    lower_query = raw_query.lower()
    quoted_phrases = [
        phrase.strip()
        for phrase in re.findall(r'"([^"]{2,160})"', raw_query)
        if phrase.strip()
    ]
    year_terms = sorted(set(re.findall(r"\b(?:19|20)\d{2}\b", raw_query)))

    entity_candidates: set[str] = set()
    entity_candidates.update(quoted_phrases)
    entity_candidates.update(
        match.group(0).strip()
        for match in re.finditer(r"\b(?:[A-Z][A-Za-z0-9'&./-]+(?:\s+[A-Z][A-Za-z0-9'&./-]+)+)\b", raw_query)
    )
    entity_candidates.update(
        token.strip()
        for token in re.findall(r"\b(?:[A-Z]{2,}|[A-Za-z0-9]+['&./-][A-Za-z0-9'&./-]+)\b", raw_query)
    )

    entity_terms = sorted(
        {
            candidate
            for candidate in entity_candidates
            if candidate
            and candidate.lower() not in _SPARSE_GENERIC_TERMS
            and len(candidate) >= 3
        },
        key=lambda value: (-len(value), value.lower()),
    )

    return SparseQueryPlan(
        search_query=raw_query,
        exact_phrases=sorted(set(quoted_phrases), key=lambda value: (-len(value), value.lower())),
        entity_terms=entity_terms,
        year_terms=year_terms,
        transcript_sensitive=bool(_TRANSCRIPT_HINT_RE.search(lower_query)),
    )


def _should_expand_chunk_text(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    if len(cleaned) < 280:
        return True
    if cleaned.endswith("...") or cleaned.endswith("…"):
        return True
    tail = cleaned[-30:]
    return not any(p in tail for p in ".!?")


def retrieve_similar_chunks(
    query: str,
    db: Session,
    *,
    top_k: int = DEFAULT_TOP_K,
    author_id: Optional[str] = None,
    author_ids: Optional[list[str]] = None,
    source_type: Optional[str] = None,
    domains: Optional[list[str]] = None,
    expertise_tags: Optional[list[str]] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    published_from: Optional[str] = None,
    published_to: Optional[str] = None,
    weighting_enabled: Optional[bool] = None,
) -> list[RetrievedChunk]:
    """
    Embed query and return the top-k most similar chunks.

    Filters:
      author_id      -- restrict to a single author's corpus
      author_ids     -- restrict to a selected set of authors
      source_type    -- restrict to 'html', 'pdf', 'text', or 'manual'
      domains        -- restrict to authors in these domain categories (Postgres only)
      expertise_tags -- restrict to authors with these expertise tags (Postgres only)
      year_from      -- restrict to chunks whose year >= year_from
                        (prefers rag_documents.published_at on Postgres,
                         falls back to metadata_json->>'year')
      year_to        -- restrict to chunks whose year <= year_to (same precedence)
      published_from -- restrict to documents with published_at >= published_from (YYYY-MM-DD)
      published_to   -- restrict to documents with published_at <= published_to (YYYY-MM-DD)

    Returns an empty list if no embeddings exist yet.
    """
    weighting_active = metadata_weighting_enabled(override=weighting_enabled)
    trace_retrieval_payload(
        "dense_query_plan",
        {
            "query": query,
            "top_k": top_k,
            "filters": {
                "author_id": author_id,
                "author_ids": author_ids,
                "source_type": source_type,
                "domains": domains,
                "expertise_tags": expertise_tags,
                "year_from": year_from,
                "year_to": year_to,
                "published_from": published_from,
                "published_to": published_to,
            },
        },
    )
    query_vector = embed_query(query)
    vector_literal = "[" + ",".join(str(v) for v in query_vector) + "]"

    where_clauses: list[str] = []
    params: dict[str, Any] = {
        "top_k": weighting_candidate_limit(top_k, enabled=weighting_active),
        "query_vec": vector_literal,
    }

    is_postgres = _is_postgres(db)

    if author_id:
        where_clauses.append("COALESCE(rd.author_id, rs.author_id) = :author_id")
        params["author_id"] = author_id
    elif author_ids:
        author_id_conditions = " OR ".join(
            f"COALESCE(rd.author_id, rs.author_id) = :author_id_{i}" for i in range(len(author_ids))
        )
        where_clauses.append(f"({author_id_conditions})")
        for i, selected_author_id in enumerate(author_ids):
            params[f"author_id_{i}"] = selected_author_id
    if source_type:
        where_clauses.append("rs.source_type = :source_type")
        params["source_type"] = source_type
    if domains:
        domain_conditions = " OR ".join(f":domain_{i} = ANY(ra.domains)" for i in range(len(domains)))
        where_clauses.append(f"({domain_conditions})")
        for i, d in enumerate(domains):
            params[f"domain_{i}"] = d
    if expertise_tags:
        tag_conditions = " OR ".join(f":tag_{i} = ANY(ra.expertise_tags)" for i in range(len(expertise_tags)))
        where_clauses.append(f"({tag_conditions})")
        for i, t in enumerate(expertise_tags):
            params[f"tag_{i}"] = t

    _apply_date_filters(where_clauses, params, is_postgres, year_from, year_to, published_from, published_to)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    sql = text(
        f"""
        SELECT
            rc.id             AS chunk_id,
            rc.document_id,
            rc.chunk_index,
            rc.text,
            rc.token_count,
            rc.metadata_json,
            rd.collection,
            rd.title,
            rd.source_section,
            rd.canonical_status,
            rd.dedupe_priority,
            rd.work_type,
            rd.metadata_json AS document_metadata_json,
            COALESCE(rd.author_id, rs.author_id) AS author_id,
            ra.name AS author_name,
            (re.embedding <=> CAST(:query_vec AS vector)) AS cosine_distance
        FROM rag_embeddings re
        JOIN rag_chunks    rc ON rc.id = re.chunk_id
        JOIN rag_documents rd ON rd.id = rc.document_id
        JOIN rag_sources   rs ON rs.id = rd.source_id
        JOIN rag_authors   ra ON ra.id = COALESCE(rd.author_id, rs.author_id)
        {where_sql}
        ORDER BY cosine_distance ASC
        LIMIT :top_k
        """
    )

    try:
        rows = db.execute(sql, params).mappings().all()
    except Exception as exc:
        log.exception("retrieve_similar_chunks query failed: %s", exc)
        return []

    chunks = [
        RetrievedChunk(
            chunk_id=str(row["chunk_id"]),
            document_id=str(row["document_id"]),
            chunk_index=row["chunk_index"],
            text=row["text"],
            token_count=row["token_count"],
            metadata_json=merge_retrieval_metadata(
                dict(row["metadata_json"]) if row["metadata_json"] else {},
                collection=row["collection"],
                canonical_status=row["canonical_status"],
                dedupe_priority=row["dedupe_priority"],
                work_type=row["work_type"],
                document_metadata={
                    **(dict(row["document_metadata_json"]) if row["document_metadata_json"] else {}),
                    "document_title": row["title"],
                    "source_section": row["source_section"],
                    "author_id": row["author_id"],
                    "author_name": row["author_name"],
                },
            ),
            cosine_distance=float(row["cosine_distance"]),
        )
        for row in rows
    ]
    ranked_chunks = _rank_chunks(chunks, top_k=top_k, stage="dense", weighting_enabled=weighting_active)
    trace_retrieval_chunks(
        "dense_db_results",
        query,
        ranked_chunks,
        extra={"raw_result_count": len(rows), "returned_count": len(ranked_chunks)},
    )
    return ranked_chunks


def expand_chunks_with_context(
    chunks: list[RetrievedChunk],
    db: Session,
    *,
    window_size: int = 2,
    max_chars: int = 1800,
    only_when_needed: bool = False,
) -> list[RetrievedChunk]:
    """
    Expand each winning chunk with neighboring chunks from the same document.

    This keeps the selected evidence set size stable while materially enriching
    each passage with surrounding context.
    """
    if not chunks or window_size < 1:
        return chunks

    expanded: list[RetrievedChunk] = []
    for chunk in chunks:
        if only_when_needed and not _should_expand_chunk_text(str(getattr(chunk, "text", "") or "")):
            expanded.append(chunk)
            continue
        try:
            neighbors = (
                db.query(RagChunk)
                .filter(
                    RagChunk.document_id == chunk.document_id,
                    RagChunk.chunk_index >= chunk.chunk_index - window_size,
                    RagChunk.chunk_index <= chunk.chunk_index + window_size,
                )
                .order_by(RagChunk.chunk_index.asc())
                .all()
            )
        except Exception as exc:
            log.warning("expand_chunks_with_context failed for chunk=%s: %s", chunk.chunk_id, exc)
            expanded.append(chunk)
            continue

        if not neighbors:
            expanded.append(chunk)
            continue

        merged_indices = [n.chunk_index for n in neighbors]
        merged_passages = [n.text.strip() for n in neighbors if (n.text or "").strip()]
        base_text = str(getattr(chunk, "text", "") or "")
        merged_text = "\n\n".join(merged_passages).strip() or base_text
        if max_chars > 0 and len(merged_text) > max_chars:
            merged_text = merged_text[: max_chars - 3].rstrip() + "..."

        summed_tokens = sum((n.token_count or 0) for n in neighbors)
        raw_metadata = getattr(chunk, "metadata_json", None)
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        metadata["context_window"] = window_size
        metadata["anchor_chunk_index"] = chunk.chunk_index
        metadata["context_chunk_indices"] = merged_indices

        expanded.append(
            RetrievedChunk(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                text=merged_text,
                token_count=summed_tokens or chunk.token_count,
                metadata_json=metadata,
                cosine_distance=chunk.cosine_distance,
                ts_rank=chunk.ts_rank,
                rrf_score=chunk.rrf_score,
                reranker_score=chunk.reranker_score,
            )
        )

    return expanded


def _build_sparse_rank_sql(plan: SparseQueryPlan, params: dict[str, Any]) -> tuple[str, str]:
    metadata_vector = (
        "to_tsvector('english', "
        "COALESCE(rd.title, '') || ' ' || COALESCE(rd.source_section, '') || ' ' || COALESCE(rd.collection, '')"
        ")"
    )
    search_predicates = [
        "("
        "rc.tsv @@ websearch_to_tsquery('english', :fts_query) "
        f"OR {metadata_vector} @@ websearch_to_tsquery('english', :fts_query)"
        ")"
    ]
    rank_terms = [
        "ts_rank_cd(rc.tsv, websearch_to_tsquery('english', :fts_query))",
        f"ts_rank_cd({metadata_vector}, websearch_to_tsquery('english', :fts_query)) * 0.35",
    ]

    exact_terms = list(plan.exact_phrases) + [
        term for term in plan.entity_terms if term.lower() not in {phrase.lower() for phrase in plan.exact_phrases}
    ]
    for index, term in enumerate(exact_terms):
        like_key = f"exact_like_{index}"
        params[like_key] = "%" + term.lower().replace("%", "\\%").replace("_", "\\_") + "%"
        search_predicates.append(f"lower(rc.text) LIKE :{like_key} ESCAPE '\\'")
        boost = 0.75 if " " in term.strip() else 0.35
        rank_terms.append(f"CASE WHEN lower(rc.text) LIKE :{like_key} ESCAPE '\\' THEN {boost} ELSE 0 END")

    for index, year in enumerate(plan.year_terms):
        year_key = f"year_{index}"
        year_str_key = f"year_str_{index}"
        year_like_key = f"year_like_{index}"
        params[year_key] = int(year)
        params[year_str_key] = year
        params[year_like_key] = f"%{year}%"
        predicate = (
            f"(rd.publication_year = :{year_key} "
            f"OR (rc.metadata_json->>'year') = :{year_str_key} "
            f"OR lower(rc.text) LIKE :{year_like_key})"
        )
        search_predicates.append(predicate)
        rank_terms.append(f"CASE WHEN {predicate} THEN 0.2 ELSE 0 END")

    if plan.transcript_sensitive:
        transcript_predicate = (
            "("
            "lower(COALESCE(rd.work_type, '')) LIKE '%transcript%' "
            "OR lower(COALESCE(rd.source_section, '')) LIKE '%q&a%' "
            "OR lower(rc.text) LIKE 'q:%' "
            "OR lower(rc.text) LIKE '%question:%' "
            "OR lower(rc.text) LIKE '%answer:%'"
            ")"
        )
        search_predicates.append(transcript_predicate)
        rank_terms.append(f"CASE WHEN {transcript_predicate} THEN 0.18 ELSE 0 END")

    return "(" + " OR ".join(search_predicates) + ")", " + ".join(rank_terms)


def _copy_chunk_with_metadata(chunk: RetrievedChunk, metadata: dict[str, Any], *, text: Optional[str] = None, token_count: Optional[int] = None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        chunk_index=chunk.chunk_index,
        text=chunk.text if text is None else text,
        token_count=chunk.token_count if token_count is None else token_count,
        metadata_json=metadata,
        cosine_distance=chunk.cosine_distance,
        ts_rank=chunk.ts_rank,
        rrf_score=chunk.rrf_score,
        reranker_score=chunk.reranker_score,
        metadata_weight=chunk.metadata_weight,
        base_score=chunk.base_score,
        weighted_score=chunk.weighted_score,
        corpus_class=chunk.corpus_class,
        weighting_applied=chunk.weighting_applied,
    )


def _merge_context_rows(
    anchor_chunk: RetrievedChunk,
    rows: list[RagChunk],
    *,
    max_chars: int,
    delivery_mode: str,
    delivery_document_id: str,
    parent_document_id: Optional[str] = None,
) -> RetrievedChunk:
    merged_indices = [row.chunk_index for row in rows]
    merged_text = "\n\n".join(row.text.strip() for row in rows if (row.text or "").strip()).strip() or anchor_chunk.text
    if max_chars > 0 and len(merged_text) > max_chars:
        merged_text = merged_text[: max_chars - 3].rstrip() + "..."

    metadata = dict(anchor_chunk.metadata_json or {})
    metadata["delivery_mode"] = delivery_mode
    metadata["delivery_document_id"] = delivery_document_id
    metadata["anchor_chunk_index"] = anchor_chunk.chunk_index
    metadata["context_chunk_indices"] = merged_indices
    metadata["anchor_text"] = anchor_chunk.text
    if parent_document_id:
        metadata["parent_document_id"] = parent_document_id

    return _copy_chunk_with_metadata(
        anchor_chunk,
        metadata,
        text=merged_text,
        token_count=sum((row.token_count or 0) for row in rows) or anchor_chunk.token_count,
    )


def deliver_parent_sections(
    chunks: list[RetrievedChunk],
    db: Session,
    *,
    window_size: int = _PARENT_CHILD_WINDOW,
    max_chars: int = 1800,
    only_when_needed: bool = False,
) -> list[RetrievedChunk]:
    if not chunks:
        return []

    delivered: list[RetrievedChunk] = []
    for chunk in chunks:
        if only_when_needed and not _should_expand_chunk_text(str(getattr(chunk, "text", "") or "")):
            delivered.append(chunk)
            continue

        try:
            document = db.query(RagDocument).filter(RagDocument.id == chunk.document_id).first()
        except Exception as exc:
            log.warning("deliver_parent_sections failed for chunk=%s: %s", chunk.chunk_id, exc)
            delivered.append(chunk)
            continue

        if document and document.parent_document_id:
            try:
                parent_rows = (
                    db.query(RagChunk)
                    .filter(
                        RagChunk.document_id == document.parent_document_id,
                        RagChunk.chunk_index >= max(0, chunk.chunk_index - window_size),
                        RagChunk.chunk_index <= chunk.chunk_index + window_size,
                    )
                    .order_by(RagChunk.chunk_index.asc())
                    .all()
                )
            except Exception as exc:
                log.warning("parent-child delivery failed for chunk=%s: %s", chunk.chunk_id, exc)
                parent_rows = []

            if parent_rows:
                delivered.append(
                    _merge_context_rows(
                        chunk,
                        parent_rows,
                        max_chars=max_chars,
                        delivery_mode="parent_document",
                        delivery_document_id=str(document.parent_document_id),
                        parent_document_id=str(document.parent_document_id),
                    )
                )
                continue

        same_document_rows = expand_chunks_with_context(
            [chunk],
            db,
            window_size=max(1, window_size // 2),
            max_chars=max_chars,
            only_when_needed=False,
        )
        if same_document_rows:
            expanded_chunk = same_document_rows[0]
            metadata = dict(expanded_chunk.metadata_json or {})
            metadata.setdefault(
                "delivery_mode",
                "neighbor_window" if expanded_chunk.text != chunk.text else "anchor_chunk",
            )
            metadata["delivery_document_id"] = expanded_chunk.document_id
            delivered.append(_copy_chunk_with_metadata(expanded_chunk, metadata))
            continue

        delivered.append(chunk)

    return delivered


def _duplicate_comparison_text(chunk: RetrievedChunk) -> str:
    metadata = chunk.metadata_json or {}
    if isinstance(metadata, dict):
        context_text = metadata.get("context_text")
        if isinstance(context_text, str) and context_text.strip():
            return context_text
    return str(getattr(chunk, "text", "") or "")


def _normalize_duplicate_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", text.lower())).strip()
    return normalized[:1800]


def _duplicate_token_signature(normalized_text: str) -> frozenset[str]:
    tokens = normalized_text.split()
    if not tokens:
        return frozenset()
    return frozenset(tokens[:220])


def suppress_near_duplicates(
    chunks: list[RetrievedChunk],
    *,
    threshold: float = _NEAR_DUPLICATE_THRESHOLD,
) -> tuple[list[RetrievedChunk], list[dict[str, Any]]]:
    kept: list[RetrievedChunk] = []
    suppressed: list[dict[str, Any]] = []
    comparisons: list[tuple[str, RetrievedChunk]] = []

    for chunk in chunks:
        normalized = _normalize_duplicate_text(_duplicate_comparison_text(chunk))
        if not normalized:
            kept.append(chunk)
            continue

        duplicate_of: Optional[tuple[str, RetrievedChunk, float]] = None
        for existing_normalized, existing_chunk in comparisons:
            if normalized == existing_normalized:
                duplicate_of = (existing_chunk.chunk_id, existing_chunk, 1.0)
                break
            similarity = difflib.SequenceMatcher(a=normalized, b=existing_normalized).ratio()
            if similarity >= threshold:
                duplicate_of = (existing_chunk.chunk_id, existing_chunk, similarity)
                break

        if duplicate_of is not None:
            matched_chunk_id, _matched_chunk, similarity = duplicate_of
            suppressed.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "matched_chunk_id": matched_chunk_id,
                    "similarity": round(similarity, 4),
                }
            )
            continue

        metadata = dict(chunk.metadata_json or {})
        metadata["duplicate_suppression_applied"] = True
        metadata["duplicate_group_key"] = normalized[:96]
        copied = _copy_chunk_with_metadata(chunk, metadata)
        kept.append(copied)
        comparisons.append((normalized, copied))

    return kept, suppressed


# ── Sparse (keyword) retrieval ────────────────────────────────────────────────


def retrieve_keyword_chunks(
    query: str,
    db: Session,
    *,
    top_k: int = DEFAULT_TOP_K,
    author_id: Optional[str] = None,
    author_ids: Optional[list[str]] = None,
    source_type: Optional[str] = None,
    domains: Optional[list[str]] = None,
    expertise_tags: Optional[list[str]] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    published_from: Optional[str] = None,
    published_to: Optional[str] = None,
    weighting_enabled: Optional[bool] = None,
    hardening_enabled: Optional[bool] = None,
) -> list[RetrievedChunk]:
    """
    Full-text search using Postgres tsvector/tsquery.

    Uses websearch_to_tsquery on the hardened path and plainto_tsquery on the
    legacy path for safe query parsing.
    Returns an empty list on non-Postgres backends (e.g. SQLite in tests).

    Same filter parameters as retrieve_similar_chunks().
    """
    weighting_active = metadata_weighting_enabled(override=weighting_enabled)
    hardening_active = retrieval_hardening_enabled(override=hardening_enabled)
    dialect_name = db.bind.dialect.name if db.bind else "unknown"
    if dialect_name != "postgresql":
        log.debug("retrieve_keyword_chunks: skipping FTS on non-Postgres dialect=%s", dialect_name)
        return []

    if not query or not query.strip():
        return []

    query_plan = build_sparse_query_plan(query) if hardening_active else SparseQueryPlan(search_query=query)
    if not query_plan.search_query:
        return []
    trace_retrieval_payload(
        "sparse_query_plan",
        {
            "input_query": query,
            "hardening_enabled": hardening_active,
            "search_query": query_plan.search_query,
            "exact_phrases": query_plan.exact_phrases,
            "entity_terms": query_plan.entity_terms,
            "year_terms": query_plan.year_terms,
            "transcript_sensitive": query_plan.transcript_sensitive,
            "top_k": top_k,
            "filters": {
                "author_id": author_id,
                "author_ids": author_ids,
                "source_type": source_type,
                "domains": domains,
                "expertise_tags": expertise_tags,
                "year_from": year_from,
                "year_to": year_to,
                "published_from": published_from,
                "published_to": published_to,
            },
        },
    )

    params: dict[str, Any] = {
        "top_k": weighting_candidate_limit(top_k, enabled=weighting_active),
        "fts_query": query_plan.search_query,
    }

    if hardening_active:
        search_where, rank_sql = _build_sparse_rank_sql(query_plan, params)
        where_clauses: list[str] = [search_where]
    else:
        where_clauses = ["rc.tsv @@ plainto_tsquery('english', :fts_query)"]
        rank_sql = "ts_rank(rc.tsv, plainto_tsquery('english', :fts_query))"

    is_postgres = True  # already verified above

    if author_id:
        where_clauses.append("COALESCE(rd.author_id, rs.author_id) = :author_id")
        params["author_id"] = author_id
    elif author_ids:
        author_id_conditions = " OR ".join(
            f"COALESCE(rd.author_id, rs.author_id) = :author_id_{i}" for i in range(len(author_ids))
        )
        where_clauses.append(f"({author_id_conditions})")
        for i, aid in enumerate(author_ids):
            params[f"author_id_{i}"] = aid
    if source_type:
        where_clauses.append("rs.source_type = :source_type")
        params["source_type"] = source_type
    if domains:
        domain_conditions = " OR ".join(f":domain_{i} = ANY(ra.domains)" for i in range(len(domains)))
        where_clauses.append(f"({domain_conditions})")
        for i, d in enumerate(domains):
            params[f"domain_{i}"] = d
    if expertise_tags:
        tag_conditions = " OR ".join(f":tag_{i} = ANY(ra.expertise_tags)" for i in range(len(expertise_tags)))
        where_clauses.append(f"({tag_conditions})")
        for i, t in enumerate(expertise_tags):
            params[f"tag_{i}"] = t

    _apply_date_filters(where_clauses, params, is_postgres, year_from, year_to, published_from, published_to)

    where_sql = "WHERE " + " AND ".join(where_clauses)

    sql = text(
        f"""
        SELECT
            rc.id             AS chunk_id,
            rc.document_id,
            rc.chunk_index,
            rc.text,
            rc.token_count,
            rc.metadata_json,
            rd.collection,
            rd.title,
            rd.source_section,
            rd.canonical_status,
            rd.dedupe_priority,
            rd.work_type,
            rd.metadata_json AS document_metadata_json,
            COALESCE(rd.author_id, rs.author_id) AS author_id,
            ra.name AS author_name,
            ({rank_sql}) AS ts_rank
        FROM rag_chunks    rc
        JOIN rag_documents rd ON rd.id = rc.document_id
        JOIN rag_sources   rs ON rs.id = rd.source_id
        JOIN rag_authors   ra ON ra.id = COALESCE(rd.author_id, rs.author_id)
        {where_sql}
        ORDER BY ts_rank DESC
        LIMIT :top_k
        """
    )

    try:
        rows = db.execute(sql, params).mappings().all()
    except Exception as exc:
        log.exception("retrieve_keyword_chunks query failed: %s", exc)
        return []

    chunks = [
        RetrievedChunk(
            chunk_id=str(row["chunk_id"]),
            document_id=str(row["document_id"]),
            chunk_index=row["chunk_index"],
            text=row["text"],
            token_count=row["token_count"],
            metadata_json=merge_retrieval_metadata(
                dict(row["metadata_json"]) if row["metadata_json"] else {},
                collection=row["collection"],
                canonical_status=row["canonical_status"],
                dedupe_priority=row["dedupe_priority"],
                work_type=row["work_type"],
                document_metadata={
                    **(dict(row["document_metadata_json"]) if row["document_metadata_json"] else {}),
                    "document_title": row["title"],
                    "source_section": row["source_section"],
                    "author_id": row["author_id"],
                    "author_name": row["author_name"],
                },
            ),
            cosine_distance=1.0,  # no cosine distance for keyword results
            ts_rank=float(row["ts_rank"]),
        )
        for row in rows
    ]
    ranked_chunks = _rank_chunks(chunks, top_k=top_k, stage="sparse", weighting_enabled=weighting_active)
    trace_retrieval_chunks(
        "sparse_db_results",
        query,
        ranked_chunks,
        extra={
            "search_query": query_plan.search_query,
            "raw_result_count": len(rows),
            "returned_count": len(ranked_chunks),
        },
    )
    return ranked_chunks


# ── Reciprocal Rank Fusion ────────────────────────────────────────────────────


def reciprocal_rank_fusion(
    *result_lists: list[RetrievedChunk],
    k: int = _RRF_K,
    weighting_enabled: Optional[bool] = None,
) -> list[RetrievedChunk]:
    """
    Combine multiple ranked result lists using Reciprocal Rank Fusion (RRF).

    RRF score for document d = sum(1 / (k + rank_i(d))) for each ranked list i.
    Higher score = more relevant (ranked earlier across lists).

    Args:
        *result_lists: One or more ranked lists of RetrievedChunk.
        k: RRF constant (default 60). Controls how much early ranks dominate.

    Returns:
        Combined list sorted by descending RRF score, with rrf_score set.
    """
    weighting_active = metadata_weighting_enabled(override=weighting_enabled)
    scores: dict[str, float] = {}
    chunk_map: dict[str, RetrievedChunk] = {}

    for result_list in result_lists:
        for rank, chunk in enumerate(result_list):
            chunk_id = chunk.chunk_id
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
            if chunk_id not in chunk_map:
                chunk_map[chunk_id] = chunk
    combined: list[RetrievedChunk] = []
    for cid, rrf_score in scores.items():
        chunk = chunk_map[cid]
        combined.append(
            RetrievedChunk(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                token_count=chunk.token_count,
                metadata_json=chunk.metadata_json,
                cosine_distance=chunk.cosine_distance,
                ts_rank=chunk.ts_rank,
                rrf_score=rrf_score,
                reranker_score=chunk.reranker_score,
            )
        )
    return _rank_chunks(combined, top_k=len(combined), stage="rrf", weighting_enabled=weighting_active)


def _metadata_search_text(metadata: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("section_path", "heading", "title", "source_section", "document_title", "collection"):
        value = metadata.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        elif value:
            parts.append(str(value))
    return " ".join(parts).lower()


def _count_term_hits(text: str, terms: list[str]) -> list[str]:
    haystack = text.lower()
    hits: list[str] = []
    for term in terms:
        normalized = term.lower().strip()
        if not normalized:
            continue
        if " " in normalized:
            if normalized in haystack:
                hits.append(term)
        elif re.search(r"\b" + re.escape(normalized) + r"\b", haystack):
            hits.append(term)
    return _dedupe_preserve_order(hits)


def _aspect_hits_for_plan(plan: RetrievalQueryPlan, text: str, metadata_text: str = "") -> dict[str, list[str]]:
    aspect_hits: dict[str, list[str]] = {}
    active_aspects: dict[str, list[str]] = {}
    required = {phrase.lower() for phrase in plan.required_phrases}
    concepts = {term.lower() for term in plan.concept_terms}
    for concept_phrase, aspects in _CONCEPT_ASPECTS.items():
        if concept_phrase in required or concept_phrase in concepts:
            active_aspects.update(aspects)
    if not active_aspects:
        return aspect_hits

    haystack = f"{text} {metadata_text}".lower()
    for aspect, terms in active_aspects.items():
        hits = _count_term_hits(haystack, terms)
        if hits:
            aspect_hits[aspect] = hits
    return aspect_hits


def _concept_hit_score(hits: list[str]) -> float:
    weights = {
        "mental models": 0.65,
        "latticework": 0.95,
        "inversion": 0.9,
        "invert": 0.9,
        "backward": 0.65,
        "mental trick": 0.85,
        "incentives": 1.0,
        "disincentives": 0.85,
        "incentive-caused": 1.0,
        "reward superresponse": 1.0,
        "operant conditioning": 1.1,
        "conditioned reflex": 1.0,
        "pavlovian": 1.0,
        "classical conditioning": 1.1,
        "social proof": 1.0,
        "authority": 0.9,
        "milgram": 0.9,
        "availability": 0.9,
        "misweighing": 0.8,
        "envy": 0.9,
        "jealousy": 0.9,
        "principles": 0.75,
        "multidisciplinary": 0.7,
        "disciplines": 0.9,
        "microeconomics": 0.75,
        "physiology": 0.65,
        "mathematics": 0.65,
        "hard science": 0.75,
        "engineering": 0.65,
        "critical mass": 1.0,
        "lollapalooza": 1.0,
        "margin of safety": 1.0,
        "checklist": 0.75,
        "psychology": 0.45,
        "models": 0.25,
    }
    return sum(weights.get(hit.lower(), 0.55) for hit in hits)


def _aspect_coverage_score(aspect_hits: dict[str, list[str]]) -> float:
    if not aspect_hits:
        return 0.0
    aspect_count = len(aspect_hits)
    term_count = sum(len(hits) for hits in aspect_hits.values())
    return min(aspect_count, 5) * 0.85 + min(term_count, 8) * 0.12


def _feedback_seed_tokens(plan: RetrievalQueryPlan) -> set[str]:
    seed_text = " ".join(
        [
            plan.raw_query,
            plan.content_query,
            " ".join(plan.required_phrases),
            " ".join(plan.concept_terms),
            " ".join(plan.source_author_names),
            " ".join(plan.removed_source_author_terms),
        ]
    )
    return {
        token.lower()
        for token in re.findall(r"[a-z][a-z0-9-]{2,}", seed_text.lower())
    }


def _feedback_tokenize(text: str) -> list[str]:
    return [
        token.strip("-").lower()
        for token in re.findall(r"[a-z][a-z0-9-]{2,}", text.lower())
        if token.strip("-")
    ]


def _allowed_feedback_term(term: str, *, score: float, existing: set[str], seed_tokens: set[str]) -> bool:
    normalized = term.lower().strip()
    if not normalized or normalized in existing or normalized in seed_tokens:
        return False
    if any(token in _FEEDBACK_STOPWORDS for token in normalized.split()):
        return False
    if normalized in _DOMAIN_FEEDBACK_TERMS:
        return True
    # Generic corpus-local expansion: allow terms that repeatedly surface in
    # the already constrained candidate pool. This keeps expansion tied to the
    # selected author/corpus instead of a global hand-written vocabulary.
    return score >= 1.45


def _extract_salient_feedback_terms(
    plan: RetrievalQueryPlan,
    pools: dict[str, list[RetrievedChunk]],
    *,
    max_terms: int = 14,
) -> list[str]:
    seed_tokens = _feedback_seed_tokens(plan)
    existing = {term.lower() for term in plan.concept_terms}
    term_scores: Counter[str] = Counter()
    phrase_scores: Counter[str] = Counter()
    pool_order = (
        "sparse_required_phrase",
        "dense_content",
        "sparse_content",
        "sparse_feedback",
        "dense_feedback",
    )

    for pool_name in pool_order:
        for rank, chunk in enumerate(pools.get(pool_name, [])[:12], start=1):
            # Expansion should be local to retrieved evidence text. Metadata is
            # useful for scoring but too noisy for query expansion.
            search_text = str(chunk.text or "")
            tokens = _feedback_tokenize(search_text)
            filtered: list[str] = []
            weight = 1.0 / max(rank, 1)
            for token in tokens:
                if token in _FEEDBACK_STOPWORDS or token in seed_tokens or len(token) < 4:
                    continue
                if token.isdigit():
                    continue
                filtered.append(token)
                term_scores[token] += weight

            for left, right in zip(filtered, filtered[1:]):
                if left == right:
                    continue
                phrase = f"{left} {right}"
                if phrase in existing:
                    continue
                phrase_scores[phrase] += weight * 1.25

    selected: list[str] = []
    for phrase, score in phrase_scores.most_common(max_terms * 2):
        if not _allowed_feedback_term(phrase, score=score, existing=existing, seed_tokens=seed_tokens):
            continue
        if any(term in phrase.split() for term in ("section", "title", "chunk")):
            continue
        selected.append(phrase)
        if len(selected) >= max_terms // 2:
            break

    for term, score in term_scores.most_common(max_terms * 3):
        if not _allowed_feedback_term(term, score=score, existing=existing, seed_tokens=seed_tokens):
            continue
        selected.append(term)
        if len(selected) >= max_terms:
            break

    return _dedupe_preserve_order(selected)


def _copy_chunk_with_retrieval_diagnostics(
    chunk: RetrievedChunk,
    *,
    plan: RetrievalQueryPlan,
    pool_memberships: dict[str, dict[str, float]],
    score_components: dict[str, float],
    phrase_hits: list[str],
    concept_term_hits: list[str],
    metadata_hits: list[str],
    final_score: float,
    aspect_hits: Optional[dict[str, list[str]]] = None,
    diversity_diagnostics: Optional[dict[str, Any]] = None,
) -> RetrievedChunk:
    metadata = dict(chunk.metadata_json or {})
    metadata["retrieval_query_plan"] = plan.as_dict()
    metadata["retrieval_diagnostics"] = {
        "pool_memberships": pool_memberships,
        "phrase_hits": phrase_hits,
        "concept_term_hits": concept_term_hits,
        "metadata_hits": metadata_hits,
        "aspect_hits": aspect_hits or {},
        "diversity": diversity_diagnostics or {},
        "score_components": score_components,
        "final_score": round(final_score, 6),
    }
    copied = _copy_chunk_with_metadata(chunk, metadata)
    copied.rrf_score = final_score
    return copied


def _update_hardened_diagnostics(
    chunk: RetrievedChunk,
    *,
    score_components: Optional[dict[str, float]] = None,
    final_score: Optional[float] = None,
    diversity_diagnostics: Optional[dict[str, Any]] = None,
) -> RetrievedChunk:
    metadata = dict(chunk.metadata_json or {})
    diagnostics = dict(metadata.get("retrieval_diagnostics") or {})
    if score_components is not None:
        diagnostics["score_components"] = score_components
    if final_score is not None:
        diagnostics["final_score"] = round(final_score, 6)
    if diversity_diagnostics is not None:
        diagnostics["diversity"] = diversity_diagnostics
    metadata["retrieval_diagnostics"] = diagnostics
    copied = _copy_chunk_with_metadata(chunk, metadata)
    copied.rrf_score = final_score if final_score is not None else chunk.rrf_score
    return copied


def _chunk_aspect_names(chunk: RetrievedChunk) -> set[str]:
    metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
    raw_diagnostics = metadata.get("retrieval_diagnostics")
    diagnostics = raw_diagnostics if isinstance(raw_diagnostics, dict) else {}
    aspect_hits = diagnostics.get("aspect_hits")
    if not isinstance(aspect_hits, dict):
        return set()
    return {str(key) for key, value in aspect_hits.items() if value}


def _diversify_hardened_candidates(
    scored: list[tuple[float, str, RetrievedChunk]],
    *,
    top_k: int,
) -> list[RetrievedChunk]:
    if top_k <= 0 or not scored:
        return []

    remaining: list[dict[str, Any]] = []
    for base_score, chunk_id, chunk in scored:
        fingerprint = _normalize_duplicate_text(_duplicate_comparison_text(chunk))
        remaining.append(
            {
                "base_score": base_score,
                "chunk_id": chunk_id,
                "chunk": chunk,
                "fingerprint": fingerprint,
                "signature": _duplicate_token_signature(fingerprint),
                "aspects": _chunk_aspect_names(chunk),
            }
        )
    selected: list[tuple[float, float, str, RetrievedChunk, dict[str, Any]]] = []
    selected_fingerprints: list[tuple[str, str, frozenset[str]]] = []
    selected_aspects: set[str] = set()
    selected_document_counts: Counter[str] = Counter()

    while remaining and len(selected) < top_k:
        best_index = 0
        best_tuple: Optional[tuple[float, float, str, RetrievedChunk, dict[str, Any]]] = None
        for index, item in enumerate(remaining):
            base_score = float(item["base_score"])
            chunk_id = str(item["chunk_id"])
            chunk = item["chunk"]
            fingerprint = str(item["fingerprint"])
            signature = item["signature"]
            duplicate_penalty = 0.0
            matched_duplicate: Optional[str] = None
            if fingerprint:
                for selected_id, selected_fingerprint, selected_signature in selected_fingerprints:
                    if not selected_fingerprint:
                        continue
                    if fingerprint == selected_fingerprint:
                        duplicate_penalty = max(duplicate_penalty, 4.0)
                        matched_duplicate = selected_id
                        break
                    if signature and selected_signature:
                        overlap_ratio = len(signature & selected_signature) / max(1, min(len(signature), len(selected_signature)))
                    else:
                        overlap_ratio = 0.0
                    if overlap_ratio >= 0.9:
                        duplicate_penalty = max(duplicate_penalty, 2.5)
                        matched_duplicate = selected_id
                        break

            same_document_count = selected_document_counts.get(chunk.document_id, 0)
            same_document_penalty = 0.85 * same_document_count
            aspect_names = item["aspects"]
            new_aspects = sorted(aspect_names - selected_aspects)
            repeated_aspects = sorted(aspect_names & selected_aspects)
            new_aspect_bonus = min(len(new_aspects), 3) * 0.7
            repeated_aspect_penalty = min(len(repeated_aspects), 4) * 0.12
            adjusted_score = (
                base_score
                + new_aspect_bonus
                - repeated_aspect_penalty
                - same_document_penalty
                - duplicate_penalty
            )
            diversity = {
                "base_score": round(base_score, 6),
                "adjusted_score": round(adjusted_score, 6),
                "new_aspects": new_aspects,
                "repeated_aspects": repeated_aspects,
                "same_document_count_before": same_document_count,
                "same_document_penalty": round(same_document_penalty, 6),
                "duplicate_penalty": round(duplicate_penalty, 6),
            }
            if matched_duplicate:
                diversity["matched_duplicate_chunk_id"] = matched_duplicate
            candidate = (adjusted_score, base_score, chunk_id, chunk, diversity)
            if best_tuple is None or (adjusted_score, base_score, chunk_id) > (
                best_tuple[0],
                best_tuple[1],
                best_tuple[2],
            ):
                best_tuple = candidate
                best_index = index

        assert best_tuple is not None
        adjusted_score, _base_score, chunk_id, chunk, diversity = best_tuple
        selected_item = remaining.pop(best_index)
        selected_document_counts[chunk.document_id] += 1
        selected_aspects.update(selected_item["aspects"])
        selected_fingerprints.append(
            (chunk_id, str(selected_item["fingerprint"]), selected_item["signature"])
        )
        selected.append((adjusted_score, _base_score, chunk_id, chunk, diversity))

    diversified: list[RetrievedChunk] = []
    for adjusted_score, _base_score, _chunk_id, chunk, diversity in selected:
        diversified.append(
            _update_hardened_diagnostics(
                chunk,
                final_score=adjusted_score,
                diversity_diagnostics=diversity,
            )
        )
    return diversified


def fuse_hardened_candidates(
    *,
    plan: RetrievalQueryPlan,
    pools: dict[str, list[RetrievedChunk]],
    top_k: int,
    weighting_enabled: Optional[bool] = None,
) -> list[RetrievedChunk]:
    weighting_active = metadata_weighting_enabled(override=weighting_enabled)
    candidates: dict[str, RetrievedChunk] = {}
    memberships: dict[str, dict[str, dict[str, float]]] = {}

    pool_weights = {
        "sparse_required_phrase": 2.2,
        "sparse_content": 1.6,
        "dense_content": 1.25,
        "sparse_feedback": 1.15,
        "dense_feedback": 0.85,
        "topic_entity_pool": 1.0,
        "dense_raw_fallback": 0.2,
    }
    for pool_name, chunks in pools.items():
        weight = pool_weights.get(pool_name, 0.5)
        for rank, chunk in enumerate(chunks, start=1):
            candidates.setdefault(chunk.chunk_id, chunk)
            pool_score = weight / rank
            if chunk.ts_rank is not None:
                pool_score += min(float(chunk.ts_rank), 1.0) * 0.4
            if chunk.cosine_distance < 1.0:
                pool_score += max(0.0, 1.0 - chunk.cosine_distance) * 0.25
            memberships.setdefault(chunk.chunk_id, {})[pool_name] = {
                "rank": float(rank),
                "score": round(pool_score, 6),
            }

    scored: list[tuple[float, str, RetrievedChunk]] = []
    for chunk_id, chunk in candidates.items():
        text = str(chunk.text or "")
        metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
        metadata_text = _metadata_search_text(metadata)
        phrase_hits = _count_term_hits(text, plan.required_phrases)
        concept_hits = _count_term_hits(text, plan.concept_terms)
        metadata_hits = _count_term_hits(metadata_text, [*plan.required_phrases, *plan.concept_terms])
        aspect_hits = _aspect_hits_for_plan(plan, text, metadata_text)
        generic_concept_hits = {phrase.lower() for phrase in plan.required_phrases} | {"model", "models"}
        specific_concept_hits = [
            hit for hit in concept_hits if hit.lower().strip() not in generic_concept_hits
        ]

        pool_score = sum(item["score"] for item in memberships.get(chunk_id, {}).values())
        phrase_score = (2.0 if specific_concept_hits else 0.8) * len(phrase_hits)
        concept_score = _concept_hit_score(concept_hits)
        metadata_score = 0.4 * len(metadata_hits)
        exact_phrase_pool_score = 1.0 if "sparse_required_phrase" in memberships.get(chunk_id, {}) else 0.0
        neighbor_context_score = 0.0
        if "neighbor_context" in memberships.get(chunk_id, {}):
            neighbor_context_score = 6.2 if concept_hits else 2.0
        author_voice_score = (
            0.75
            if re.search(r"\b(?:i|i['’]ve|i['’]m|we|you\s+need|you['’]ve\s+got)\b", text, re.IGNORECASE)
            else 0.0
        )
        specific_concept_coverage_score = min(len(specific_concept_hits), 6) * 0.65
        aspect_coverage_score = _aspect_coverage_score(aspect_hits)
        word_count = len(re.findall(r"\b\w+\b", text))
        shallow_prompt_penalty = 0.0
        if phrase_hits and not specific_concept_hits and word_count <= 40:
            shallow_prompt_penalty = -3.0
        if re.match(r"\s*(?:questioner|question|q:)\b", text, re.IGNORECASE) and word_count <= 60:
            shallow_prompt_penalty -= 2.0

        score_components = {
            "pool_score": round(pool_score, 6),
            "required_phrase_score": round(phrase_score, 6),
            "concept_term_score": round(concept_score, 6),
            "specific_concept_coverage_score": round(specific_concept_coverage_score, 6),
            "aspect_coverage_score": round(aspect_coverage_score, 6),
            "metadata_hit_score": round(metadata_score, 6),
            "required_phrase_pool_score": exact_phrase_pool_score,
            "neighbor_context_score": neighbor_context_score,
            "author_voice_score": author_voice_score,
            "shallow_prompt_penalty": shallow_prompt_penalty,
        }
        final_score = sum(score_components.values())
        scored.append(
            (
                final_score,
                chunk_id,
                _copy_chunk_with_retrieval_diagnostics(
                    chunk,
                    plan=plan,
                    pool_memberships=memberships.get(chunk_id, {}),
                    score_components=score_components,
                    phrase_hits=phrase_hits,
                    concept_term_hits=concept_hits,
                    metadata_hits=metadata_hits,
                    aspect_hits=aspect_hits,
                    final_score=final_score,
                ),
            )
        )

    scored.sort(key=lambda item: (-item[0], item[1]))
    diversity_window = max(top_k * 8, 200)
    ranked = _diversify_hardened_candidates(scored[:diversity_window], top_k=top_k)
    return _rank_chunks(ranked, top_k=top_k, stage="hardened_fusion", weighting_enabled=weighting_active)


def _neighbor_candidate_pool(
    anchors: list[RetrievedChunk],
    db: Session,
    *,
    window_size: int,
) -> list[RetrievedChunk]:
    if not anchors or window_size < 1:
        return []

    seen: set[str] = set()
    neighbors: list[RetrievedChunk] = []
    for anchor in anchors:
        try:
            rows = (
                db.query(RagChunk)
                .filter(
                    RagChunk.document_id == anchor.document_id,
                    RagChunk.chunk_index >= max(0, anchor.chunk_index - window_size),
                    RagChunk.chunk_index <= anchor.chunk_index + window_size,
                )
                .order_by(RagChunk.chunk_index.asc())
                .all()
            )
        except Exception as exc:
            log.debug("neighbor candidate lookup failed for chunk=%s: %s", anchor.chunk_id, exc)
            continue

        for row in rows:
            chunk_id = str(row.id)
            if chunk_id == anchor.chunk_id or chunk_id in seen:
                continue
            seen.add(chunk_id)
            metadata = dict(row.metadata_json or {})
            metadata["neighbor_anchor_chunk_id"] = anchor.chunk_id
            metadata["neighbor_anchor_chunk_index"] = anchor.chunk_index
            neighbors.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    document_id=str(row.document_id),
                    chunk_index=row.chunk_index,
                    text=row.text,
                    token_count=row.token_count,
                    metadata_json=metadata,
                    cosine_distance=1.0,
                    ts_rank=0.0,
                )
            )
    return neighbors


def _chunk_author_id(chunk: RetrievedChunk) -> Optional[str]:
    metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
    raw = metadata.get("author_id")
    return str(raw) if raw else None


def _enforce_source_author_gate(
    chunks: list[RetrievedChunk],
    *,
    allowed_author_ids: Optional[list[str]],
) -> tuple[list[RetrievedChunk], list[str]]:
    if not allowed_author_ids:
        return chunks, []
    allowed = {str(author_id) for author_id in allowed_author_ids if author_id}
    if not allowed:
        return chunks, []

    kept: list[RetrievedChunk] = []
    removed: list[str] = []
    for chunk in chunks:
        chunk_author_id = _chunk_author_id(chunk)
        # Older unit-test doubles may not carry author metadata. Real DB
        # retrieval now attaches author_id to every chunk, so unknown metadata
        # is retained but visible in trace output.
        if chunk_author_id is None or chunk_author_id in allowed:
            kept.append(chunk)
        else:
            removed.append(chunk.chunk_id)
    return kept, removed


def _retrieve_hardened(
    query: str,
    db: Session,
    *,
    top_k: int,
    author_id: Optional[str],
    author_ids: Optional[list[str]],
    source_author_names: Optional[list[str]],
    source_type: Optional[str],
    domains: Optional[list[str]],
    expertise_tags: Optional[list[str]],
    year_from: Optional[int],
    year_to: Optional[int],
    published_from: Optional[str],
    published_to: Optional[str],
    weighting_enabled: Optional[bool],
    retrieval_mode: str,
    topic_entities: Optional[list[str]],
) -> list[RetrievedChunk]:
    plan = build_retrieval_query_plan(
        query,
        source_author_ids=author_ids or ([author_id] if author_id else None),
        source_author_names=source_author_names,
        topic_entities=topic_entities,
    )
    trace_retrieval_payload(
        "hardened_query_plan",
        {
            **plan.as_dict(),
            "retrieval_mode": retrieval_mode,
            "top_k": top_k,
            "requested_filters": {
                "author_id": author_id,
                "author_ids": author_ids,
                "source_author_names": source_author_names,
                "source_type": source_type,
                "domains": domains,
                "expertise_tags": expertise_tags,
                "year_from": year_from,
                "year_to": year_to,
                "published_from": published_from,
                "published_to": published_to,
            },
        },
    )
    effective_author_ids = author_ids
    effective_author_id = author_id
    if not effective_author_ids and not effective_author_id and len(plan.source_author_ids) == 1:
        effective_author_ids = plan.source_author_ids

    fetch_k = max(top_k * _DENSE_TOP_K_MULTIPLIER, top_k, _HARDENED_MIN_CANDIDATE_POOL)
    common_kwargs: dict[str, Any] = {
        "author_id": effective_author_id,
        "author_ids": effective_author_ids,
        "source_type": source_type,
        "domains": domains,
        "expertise_tags": expertise_tags,
        "year_from": year_from,
        "year_to": year_to,
        "published_from": published_from,
        "published_to": published_to,
        "weighting_enabled": weighting_enabled,
    }

    content_query = plan.content_query or query
    pools: dict[str, list[RetrievedChunk]] = {}
    if retrieval_mode in {"hybrid", "dense_only"}:
        pools["dense_content"] = retrieve_similar_chunks(content_query, db, top_k=fetch_k, **common_kwargs)
        trace_retrieval_chunks("pool_dense_content", content_query, pools["dense_content"])
        if query.strip().lower() != content_query.strip().lower():
            pools["dense_raw_fallback"] = retrieve_similar_chunks(
                query,
                db,
                top_k=max(top_k, fetch_k // 2),
                **common_kwargs,
            )
            trace_retrieval_chunks("pool_dense_raw_fallback", query, pools["dense_raw_fallback"])

    if retrieval_mode in {"hybrid", "sparse_only"}:
        pools["sparse_content"] = retrieve_keyword_chunks(
            plan.sparse_query or content_query,
            db,
            top_k=fetch_k,
            hardening_enabled=True,
            **common_kwargs,
        )
        trace_retrieval_chunks("pool_sparse_content", plan.sparse_query or content_query, pools["sparse_content"])
        phrase_chunks: list[RetrievedChunk] = []
        for phrase in plan.required_phrases:
            phrase_chunks.extend(
                retrieve_keyword_chunks(
                    f'"{phrase}"',
                    db,
                    top_k=fetch_k,
                    hardening_enabled=True,
                    **common_kwargs,
                )
            )
        if phrase_chunks:
            pools["sparse_required_phrase"] = phrase_chunks
            trace_retrieval_chunks("pool_sparse_required_phrase", " OR ".join(plan.required_phrases), phrase_chunks)

    feedback_terms = _extract_salient_feedback_terms(plan, pools) if retrieval_mode == "hybrid" else []
    trace_retrieval_payload(
        "feedback_terms",
        {
            "query": query,
            "content_query": content_query,
            "feedback_terms": feedback_terms,
            "input_pools": {name: len(chunks) for name, chunks in pools.items()},
        },
    )
    if feedback_terms:
        expanded_concept_terms = _dedupe_preserve_order([*plan.concept_terms, *feedback_terms])
        plan = replace(
            plan,
            concept_terms=expanded_concept_terms,
            sparse_query=_build_sparse_query(plan.required_phrases, expanded_concept_terms, content_query),
            diagnostics={**plan.diagnostics, "feedback_terms": feedback_terms},
        )
        feedback_query = " OR ".join(feedback_terms)
        if retrieval_mode in {"hybrid", "sparse_only"}:
            pools["sparse_feedback"] = retrieve_keyword_chunks(
                feedback_query,
                db,
                top_k=fetch_k,
                hardening_enabled=True,
                **common_kwargs,
            )
            trace_retrieval_chunks("pool_sparse_feedback", feedback_query, pools["sparse_feedback"])
        if retrieval_mode in {"hybrid", "dense_only"}:
            pools["dense_feedback"] = retrieve_similar_chunks(
                " ".join(feedback_terms[:10]),
                db,
                top_k=max(top_k, fetch_k // 2),
                **common_kwargs,
            )
            trace_retrieval_chunks("pool_dense_feedback", " ".join(feedback_terms[:10]), pools["dense_feedback"])

        secondary_terms = [
            term
            for term in _extract_salient_feedback_terms(plan, pools, max_terms=10)
            if term.lower() not in {item.lower() for item in expanded_concept_terms}
        ]
        trace_retrieval_payload(
            "secondary_feedback_terms",
            {
                "query": query,
                "secondary_feedback_terms": secondary_terms,
                "concept_terms_after_feedback": expanded_concept_terms,
            },
        )
        if secondary_terms:
            expanded_concept_terms = _dedupe_preserve_order([*expanded_concept_terms, *secondary_terms])
            plan = replace(
                plan,
                concept_terms=expanded_concept_terms,
                sparse_query=_build_sparse_query(plan.required_phrases, expanded_concept_terms, content_query),
                diagnostics={
                    **plan.diagnostics,
                    "secondary_feedback_terms": secondary_terms,
                },
            )

    if plan.topic_entities and retrieval_mode in {"hybrid", "sparse_only"}:
        pools["topic_entity_pool"] = retrieve_keyword_chunks(
            " OR ".join(plan.topic_entities),
            db,
            top_k=max(top_k, fetch_k // 2),
            hardening_enabled=True,
            **common_kwargs,
        )
        trace_retrieval_chunks("pool_topic_entity", " OR ".join(plan.topic_entities), pools["topic_entity_pool"])

    if retrieval_mode == "dense_only":
        dense = pools.get("dense_content", [])
        dense_only = [
            _copy_chunk_with_retrieval_diagnostics(
                chunk,
                plan=plan,
                pool_memberships={"dense_content": {"rank": float(index), "score": round(1.0 / index, 6)}},
                score_components={"pool_score": round(1.0 / index, 6)},
                phrase_hits=_count_term_hits(chunk.text, plan.required_phrases),
                concept_term_hits=_count_term_hits(chunk.text, plan.concept_terms),
                metadata_hits=[],
                final_score=round(1.0 / index, 6),
            )
            for index, chunk in enumerate(dense[:top_k], start=1)
        ]
        trace_retrieval_chunks("hardened_dense_only_final", query, dense_only, limit=top_k)
        return dense_only

    if retrieval_mode == "sparse_only" and not pools.get("sparse_content") and not pools.get("sparse_required_phrase"):
        return []

    fused = fuse_hardened_candidates(
        plan=plan,
        pools={name: chunks for name, chunks in pools.items() if chunks},
        top_k=top_k,
        weighting_enabled=weighting_enabled,
    )
    fused, removed_by_author_gate = _enforce_source_author_gate(
        fused,
        allowed_author_ids=effective_author_ids or ([effective_author_id] if effective_author_id else None),
    )
    trace_retrieval_chunks(
        "hardened_fused_final",
        query,
        fused,
        limit=top_k,
        extra={
            "pool_sizes": {name: len(chunks) for name, chunks in pools.items()},
            "source_author_gate": {
                "allowed_author_ids": effective_author_ids or ([effective_author_id] if effective_author_id else []),
                "removed_chunk_ids": removed_by_author_gate,
            },
        },
    )
    return fused


# ── Hybrid retrieval ──────────────────────────────────────────────────────────


def retrieve_hybrid(
    query: str,
    db: Session,
    *,
    top_k: int = DEFAULT_TOP_K,
    author_id: Optional[str] = None,
    author_ids: Optional[list[str]] = None,
    source_author_names: Optional[list[str]] = None,
    source_type: Optional[str] = None,
    domains: Optional[list[str]] = None,
    expertise_tags: Optional[list[str]] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    published_from: Optional[str] = None,
    published_to: Optional[str] = None,
    weighting_enabled: Optional[bool] = None,
    retrieval_mode: Optional[str] = None,
    hardening_enabled: Optional[bool] = None,
    topic_entities: Optional[list[str]] = None,
) -> list[RetrievedChunk]:
    """
    Hybrid retrieval combining dense vector search and sparse keyword search.

    Fetches top_k * _DENSE_TOP_K_MULTIPLIER from each source, then combines
    via Reciprocal Rank Fusion (RRF) and returns the top_k results.

    Falls back to dense-only if keyword retrieval returns no results
    (e.g. non-Postgres backend or no FTS index yet).

    Controlled by RAG_RETRIEVAL_MODE env var:
      hybrid      — dense + sparse via RRF (default)
      dense_only  — dense vector search only
      sparse_only — sparse keyword search only
    """
    weighting_active = metadata_weighting_enabled(override=weighting_enabled)
    mode = retrieval_mode or _RETRIEVAL_MODE
    hardening_active = retrieval_hardening_enabled(override=hardening_enabled)
    trace_retrieval_payload(
        "retrieve_hybrid_entry",
        {
            "query": query,
            "top_k": top_k,
            "retrieval_mode": mode,
            "hardening_enabled": hardening_active,
            "filters": {
                "author_id": author_id,
                "author_ids": author_ids,
                "source_author_names": source_author_names,
                "source_type": source_type,
                "domains": domains,
                "expertise_tags": expertise_tags,
                "year_from": year_from,
                "year_to": year_to,
                "published_from": published_from,
                "published_to": published_to,
                "topic_entities": topic_entities,
            },
        },
    )
    if hardening_active:
        return _retrieve_hardened(
            query,
            db,
            top_k=top_k,
            author_id=author_id,
            author_ids=author_ids,
            source_author_names=source_author_names,
            source_type=source_type,
            domains=domains,
            expertise_tags=expertise_tags,
            year_from=year_from,
            year_to=year_to,
            published_from=published_from,
            published_to=published_to,
            weighting_enabled=weighting_active,
            retrieval_mode=mode,
            topic_entities=topic_entities,
        )
    fetch_k = top_k * _DENSE_TOP_K_MULTIPLIER

    common_kwargs: dict[str, Any] = {
        "author_id": author_id,
        "author_ids": author_ids,
        "source_type": source_type,
        "domains": domains,
        "expertise_tags": expertise_tags,
        "year_from": year_from,
        "year_to": year_to,
        "published_from": published_from,
        "published_to": published_to,
        "weighting_enabled": weighting_active,
    }
    sparse_kwargs = {**common_kwargs, "hardening_enabled": hardening_enabled}

    if mode == "dense_only":
        dense_only = retrieve_similar_chunks(query, db, top_k=top_k, **common_kwargs)
        trace_retrieval_chunks("legacy_dense_only_final", query, dense_only, limit=top_k)
        return dense_only

    if mode == "sparse_only":
        sparse_only = retrieve_keyword_chunks(query, db, top_k=top_k, **sparse_kwargs)
        trace_retrieval_chunks("legacy_sparse_only_final", query, sparse_only, limit=top_k)
        return sparse_only

    # hybrid (default)
    dense_results = retrieve_similar_chunks(query, db, top_k=fetch_k, **common_kwargs)
    sparse_results = retrieve_keyword_chunks(query, db, top_k=fetch_k, **sparse_kwargs)
    trace_retrieval_chunks("legacy_dense_pool", query, dense_results)
    trace_retrieval_chunks("legacy_sparse_pool", query, sparse_results)

    if not sparse_results:
        # Non-Postgres or no FTS data yet — fall back to dense only
        log.debug("retrieve_hybrid: sparse retrieval returned 0 results, using dense only")
        fallback = dense_results[:top_k]
        trace_retrieval_chunks("legacy_dense_fallback_final", query, fallback, limit=top_k)
        return fallback

    combined = reciprocal_rank_fusion(
        dense_results,
        sparse_results,
        k=_RRF_K,
        weighting_enabled=weighting_active,
    )
    final = combined[:top_k]
    trace_retrieval_chunks("legacy_rrf_final", query, final, limit=top_k)
    return final


def compare_retrieval_weighting(
    query: str,
    db: Session,
    *,
    top_k: int = DEFAULT_TOP_K,
    author_id: Optional[str] = None,
    author_ids: Optional[list[str]] = None,
    source_type: Optional[str] = None,
    domains: Optional[list[str]] = None,
    expertise_tags: Optional[list[str]] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    published_from: Optional[str] = None,
    published_to: Optional[str] = None,
    retrieval_mode: Optional[str] = None,
) -> dict[str, Any]:
    common_kwargs: dict[str, Any] = {
        "top_k": top_k,
        "author_id": author_id,
        "author_ids": author_ids,
        "source_type": source_type,
        "domains": domains,
        "expertise_tags": expertise_tags,
        "year_from": year_from,
        "year_to": year_to,
        "published_from": published_from,
        "published_to": published_to,
        "retrieval_mode": retrieval_mode,
    }
    baseline = retrieve_hybrid(query, db, weighting_enabled=False, **common_kwargs)
    weighted = retrieve_hybrid(query, db, weighting_enabled=True, **common_kwargs)
    return {
        "query": query,
        "retrieval_mode": retrieval_mode or _RETRIEVAL_MODE,
        "weighting_feature_flag": weighting_feature_flag(),
        "default_weighting_enabled": metadata_weighting_enabled(),
        "baseline_results": [chunk.as_dict() for chunk in baseline],
        "weighted_results": [chunk.as_dict() for chunk in weighted],
    }


# ── Private helpers ───────────────────────────────────────────────────────────


def _is_postgres(db: Session) -> bool:
    """Return True when the session is connected to PostgreSQL."""
    try:
        return (db.bind.dialect.name if db.bind else "unknown") == "postgresql"
    except Exception:
        return False


def _rank_chunks(
    chunks: list[RetrievedChunk],
    *,
    top_k: int,
    stage: str,
    weighting_enabled: bool,
) -> list[RetrievedChunk]:
    if not chunks:
        return []

    for chunk in chunks:
        base_score = _base_score_for_stage(chunk, stage)
        decision = apply_weight_to_score(
            chunk.metadata_json,
            base_score=base_score,
            enabled=weighting_enabled,
        )
        chunk.base_score = decision.base_score
        chunk.metadata_weight = decision.weight
        chunk.weighted_score = decision.weighted_score
        chunk.corpus_class = decision.corpus_class
        chunk.weighting_applied = decision.enabled and abs(decision.weight - 1.0) > 1e-9

    ranked = sorted(chunks, key=ranking_sort_key)
    return ranked[:top_k]


def _base_score_for_stage(chunk: RetrievedChunk, stage: str) -> float:
    if stage == "dense":
        return max(0.0, 1.0 - float(chunk.cosine_distance))
    if stage == "sparse":
        return float(chunk.ts_rank or 0.0)
    if stage == "rrf":
        return float(chunk.rrf_score or 0.0)
    if stage == "hardened_fusion":
        return float(chunk.rrf_score or 0.0)
    if stage == "rerank":
        if chunk.reranker_score is not None:
            return float(chunk.reranker_score)
        return _base_score_for_stage(chunk, "dense")
    return float(chunk.weighted_score or chunk.base_score or chunk.similarity)


def _apply_date_filters(
    where_clauses: list[str],
    params: dict[str, Any],
    is_postgres: bool,
    year_from: Optional[int],
    year_to: Optional[int],
    published_from: Optional[str],
    published_to: Optional[str],
) -> None:
    """
    Append date-related WHERE clauses and bind params in-place.

    On Postgres: prefers rd.published_at, then rd.publication_year for year filters.
    On SQLite: falls back to rd.publication_year and metadata_json->>'year'
                (published_from/published_to are ignored as SQLite has no
                native DATE column; that column is stored as TEXT).
    """
    if is_postgres:
        if year_from is not None:
            where_clauses.append(
                "("
                " (rd.published_at IS NOT NULL AND EXTRACT(YEAR FROM rd.published_at) >= :year_from)"
                " OR (rd.published_at IS NULL AND rd.publication_year IS NOT NULL AND rd.publication_year >= :year_from)"
                " OR (rd.published_at IS NULL AND rd.publication_year IS NULL AND (rc.metadata_json->>'year') >= :year_from_str)"
                ")"
            )
            params["year_from"] = year_from
            params["year_from_str"] = str(year_from)
        if year_to is not None:
            where_clauses.append(
                "("
                " (rd.published_at IS NOT NULL AND EXTRACT(YEAR FROM rd.published_at) <= :year_to)"
                " OR (rd.published_at IS NULL AND rd.publication_year IS NOT NULL AND rd.publication_year <= :year_to)"
                " OR (rd.published_at IS NULL AND rd.publication_year IS NULL AND (rc.metadata_json->>'year') <= :year_to_str)"
                ")"
            )
            params["year_to"] = year_to
            params["year_to_str"] = str(year_to)
        if published_from:
            where_clauses.append("rd.published_at >= :published_from")
            params["published_from"] = published_from
        if published_to:
            where_clauses.append("rd.published_at <= :published_to")
            params["published_to"] = published_to
    else:
        # SQLite: prefer the document column, then fall back to metadata_json->>'year'
        if year_from is not None:
            where_clauses.append(
                "(rd.publication_year IS NOT NULL AND rd.publication_year >= :year_from"
                " OR rd.publication_year IS NULL AND (rc.metadata_json->>'year') >= :year_from_str)"
            )
            params["year_from"] = year_from
            params["year_from_str"] = str(year_from)
        if year_to is not None:
            where_clauses.append(
                "(rd.publication_year IS NOT NULL AND rd.publication_year <= :year_to"
                " OR rd.publication_year IS NULL AND (rc.metadata_json->>'year') <= :year_to_str)"
            )
            params["year_to"] = year_to
            params["year_to_str"] = str(year_to)


# ── Constraint-aware retrieval ────────────────────────────────────────────────


def retrieve_with_constraints(
    query: str,
    db: Session,
    *,
    top_k: int = DEFAULT_TOP_K,
    author_id: Optional[str] = None,
    author_ids: Optional[list[str]] = None,
    source_type: Optional[str] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    published_from: Optional[str] = None,
    published_to: Optional[str] = None,
    domains: Optional[list[str]] = None,
    expertise_tags: Optional[list[str]] = None,
    strict_constraints: bool = True,
    debug: bool = False,
) -> ConstrainedRetrievalResult:
    """
    Strict constraint-aware retrieval — no silent fallback.

    When ``strict_constraints=True`` (default), the query is executed once
    with the full set of requested filters.  If the corpus returns zero
    results the caller receives an empty chunk list and
    ``constraints_relaxed=False``.  The caller decides whether to retry
    with relaxed constraints.

    When ``strict_constraints=False``, the function performs staged
    fallback:
      1. Full constraints
      2. Drop source_type
      3. Drop year/date filters
      4. Fully unconstrained

    Each relaxation step is recorded in ``constraint_relaxation_reason``.

    The ``debug`` flag enables candidate count diagnostics in the response.
    """
    requested: dict[str, Any] = {
        "author_id": author_id,
        "author_ids": author_ids,
        "source_type": source_type,
        "year_from": year_from,
        "year_to": year_to,
        "published_from": published_from,
        "published_to": published_to,
        "domains": domains,
        "expertise_tags": expertise_tags,
    }
    # Prune None values for cleaner response output
    requested = {k: v for k, v in requested.items() if v is not None}

    common_base: dict[str, Any] = {
        "author_id": author_id,
        "author_ids": author_ids,
        "domains": domains,
        "expertise_tags": expertise_tags,
    }

    if strict_constraints:
        chunks = retrieve_hybrid(
            query,
            db,
            top_k=top_k,
            source_type=source_type,
            year_from=year_from,
            year_to=year_to,
            published_from=published_from,
            published_to=published_to,
            **common_base,
        )
        applied = dict(requested)
        diagnostics = {"candidate_count": len(chunks)} if debug else None
        return ConstrainedRetrievalResult(
            chunks=chunks,
            constraints_requested=requested,
            constraints_applied=applied,
            constraints_relaxed=False,
            constraint_relaxation_reason=None,
            diagnostics=diagnostics,
        )

    # Fallback mode: staged relaxation
    attempts: list[tuple[dict[str, Any], str]] = [
        (
            {"source_type": source_type, "year_from": year_from, "year_to": year_to,
             "published_from": published_from, "published_to": published_to},
            "full constraints",
        ),
        (
            {"source_type": None, "year_from": year_from, "year_to": year_to,
             "published_from": published_from, "published_to": published_to},
            "source_type relaxed",
        ),
        (
            {"source_type": source_type, "year_from": None, "year_to": None,
             "published_from": None, "published_to": None},
            "date/year filters relaxed",
        ),
        (
            {"source_type": None, "year_from": None, "year_to": None,
             "published_from": None, "published_to": None},
            "all filters relaxed",
        ),
    ]

    # Deduplicate attempt signatures
    seen_sigs: set[tuple] = set()
    deduped_attempts = []
    for attempt_filters, reason in attempts:
        sig = tuple(sorted(attempt_filters.items()))
        if sig not in seen_sigs:
            seen_sigs.add(sig)
            deduped_attempts.append((attempt_filters, reason))

    for attempt_filters, reason in deduped_attempts:
        chunks = retrieve_hybrid(
            query,
            db,
            top_k=top_k,
            **attempt_filters,
            **common_base,
        )
        if chunks:
            is_first = (attempt_filters, reason) == deduped_attempts[0]
            applied = {k: v for k, v in {**attempt_filters, **common_base}.items() if v is not None}
            relaxation_reason: Optional[str] = None if is_first else f"No results under exact constraints; {reason}."
            if not is_first:
                log.info(
                    "retrieve_with_constraints: fallback applied query=%r reason=%r",
                    query[:120],
                    relaxation_reason,
                )
            diagnostics = {"candidate_count": len(chunks)} if debug else None
            return ConstrainedRetrievalResult(
                chunks=chunks,
                constraints_requested=requested,
                constraints_applied=applied,
                constraints_relaxed=not is_first,
                constraint_relaxation_reason=relaxation_reason,
                diagnostics=diagnostics,
            )

    # All attempts returned zero results
    applied_empty = {k: v for k, v in {**deduped_attempts[-1][0], **common_base}.items() if v is not None}
    return ConstrainedRetrievalResult(
        chunks=[],
        constraints_requested=requested,
        constraints_applied=applied_empty,
        constraints_relaxed=True,
        constraint_relaxation_reason="No results found even after full constraint relaxation.",
        diagnostics={"candidate_count": 0} if debug else None,
    )
