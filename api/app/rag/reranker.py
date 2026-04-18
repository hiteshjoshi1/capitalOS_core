"""
Cross-encoder reranking service for RAG retrieval.

Replaces LLM-prompt-based reranking with dedicated cross-encoder backends.
Provider is selected via RAG_RERANKER_PROVIDER env var.

Supported providers:
  cohere  — Cohere Rerank API (rerank-english-v3.0)
  jina    — Jina Reranker REST API
  local   — sentence-transformers CrossEncoder (offline)
  llm     — Deprecated: LLM-prompt-based reranking (fallback)
  none    — Disabled; caller falls back to heuristic
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

_DEFAULT_COHERE_MODEL = "rerank-english-v3.0"
_DEFAULT_JINA_MODEL = "jina-reranker-v2-base-multilingual"
_DEFAULT_LOCAL_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_JINA_RERANK_URL = "https://api.jina.ai/v1/rerank"


def _reranker_provider() -> str:
    return os.getenv("RAG_RERANKER_PROVIDER", "none").strip().lower()


def _reranker_model() -> str:
    provider = _reranker_provider()
    if provider == "cohere":
        return os.getenv("RAG_RERANKER_MODEL", _DEFAULT_COHERE_MODEL).strip()
    if provider == "jina":
        return os.getenv("RAG_RERANKER_MODEL", _DEFAULT_JINA_MODEL).strip()
    if provider == "local":
        return os.getenv("RAG_RERANKER_LOCAL_MODEL", _DEFAULT_LOCAL_MODEL).strip()
    return os.getenv("RAG_RERANKER_MODEL", "").strip()


def reranker_available() -> bool:
    """Return True if a dedicated cross-encoder reranker is configured and usable."""
    provider = _reranker_provider()
    if provider in ("none", "llm", ""):
        return False
    if provider == "cohere":
        return bool(os.getenv("COHERE_API_KEY", "").strip())
    if provider == "jina":
        return bool(os.getenv("JINA_API_KEY", "").strip())
    if provider == "local":
        try:
            import sentence_transformers  # noqa: F401
            return True
        except ImportError:
            log.debug("sentence-transformers not installed; local reranker unavailable")
            return False
    return False


# ── Result dataclass ──────────────────────────────────────────────────────────


@dataclass
class RerankedResult:
    index: int               # Original index in the passages list
    relevance_score: float   # Normalised 0.0 – 1.0 relevance
    text: str                # Passage text (convenience copy)


# ── Provider implementations ──────────────────────────────────────────────────


def _rerank_cohere(
    query: str,
    passages: list[str],
    *,
    top_k: int,
) -> list[RerankedResult]:
    import cohere  # type: ignore[import]

    api_key = os.getenv("COHERE_API_KEY", "").strip()
    model = _reranker_model()
    co = cohere.Client(api_key)
    response = co.rerank(
        model=model,
        query=query,
        documents=passages,
        top_n=top_k,
        return_documents=False,
    )
    results: list[RerankedResult] = []
    for item in response.results:
        score = float(item.relevance_score)
        results.append(RerankedResult(index=item.index, relevance_score=score, text=passages[item.index]))
    return results


def _rerank_jina(
    query: str,
    passages: list[str],
    *,
    top_k: int,
) -> list[RerankedResult]:
    api_key = os.getenv("JINA_API_KEY", "").strip()
    model = _reranker_model()
    payload: dict[str, Any] = {
        "model": model,
        "query": query,
        "documents": passages,
        "top_n": top_k,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(_JINA_RERANK_URL, json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    results: list[RerankedResult] = []
    for item in data.get("results", []):
        idx = item["index"]
        score = float(item.get("relevance_score", 0.0))
        results.append(RerankedResult(index=idx, relevance_score=score, text=passages[idx]))
    return results


# Lazy-loaded local model cache
_local_model_cache: dict[str, Any] = {}


def _rerank_local(
    query: str,
    passages: list[str],
    *,
    top_k: int,
) -> list[RerankedResult]:
    from sentence_transformers import CrossEncoder  # type: ignore[import]

    model_name = _reranker_model()
    if model_name not in _local_model_cache:
        log.info("Loading local cross-encoder model: %s", model_name)
        _local_model_cache[model_name] = CrossEncoder(model_name)
    model: Any = _local_model_cache[model_name]

    pairs = [(query, p) for p in passages]
    raw_scores: list[float] = model.predict(pairs).tolist()

    # Normalise to [0, 1] using sigmoid if scores are logits
    import math

    def _sigmoid(x: float) -> float:
        return 1.0 / (1.0 + math.exp(-x))

    # Detect logit range: if any score outside [0,1] treat as logits
    needs_sigmoid = any(s < 0 or s > 1 for s in raw_scores)
    scores = [_sigmoid(s) if needs_sigmoid else s for s in raw_scores]

    indexed = sorted(enumerate(scores), key=lambda t: -t[1])
    return [
        RerankedResult(index=i, relevance_score=scores[i], text=passages[i])
        for i, _ in indexed[:top_k]
    ]


# ── Public API ────────────────────────────────────────────────────────────────


def rerank(
    query: str,
    passages: list[str],
    *,
    top_k: int = 12,
    provider: str | None = None,
) -> list[RerankedResult]:
    """
    Score and rerank passages against query.

    Returns up to top_k RerankedResult objects sorted by descending relevance.
    Raises an exception on provider error — callers should handle gracefully.
    """
    if not passages:
        return []
    effective_provider = (provider or _reranker_provider()).strip().lower()
    top_k = min(top_k, len(passages))

    if effective_provider == "cohere":
        return _rerank_cohere(query, passages, top_k=top_k)
    if effective_provider == "jina":
        return _rerank_jina(query, passages, top_k=top_k)
    if effective_provider == "local":
        return _rerank_local(query, passages, top_k=top_k)

    raise ValueError(f"Unknown or unsupported reranker provider: {effective_provider!r}")
