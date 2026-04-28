"""
Generic metadata-aware weighting helpers for retrieval-time ranking.

The weighting layer is intentionally source-agnostic. It only inspects stable
document/chunk metadata already stored in the corpus and applies mild, soft
ranking multipliers when explicitly enabled.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

_WEIGHTING_FLAG = "RAG_RETRIEVAL_METADATA_WEIGHTING_ENABLED"
_WEIGHTING_CANDIDATE_MULTIPLIER = int(os.getenv("RAG_RETRIEVAL_WEIGHTING_CANDIDATE_MULTIPLIER", "3"))
_WEIGHTING_MIN = float(os.getenv("RAG_RETRIEVAL_WEIGHTING_MIN", "0.85"))
_WEIGHTING_MAX = float(os.getenv("RAG_RETRIEVAL_WEIGHTING_MAX", "1.15"))
_DEDUPE_PRIORITY_SCALE = float(os.getenv("RAG_RETRIEVAL_DEDUPE_PRIORITY_SCALE", "0.001"))
_DEDUPE_PRIORITY_MIN = float(os.getenv("RAG_RETRIEVAL_DEDUPE_PRIORITY_MIN", "0.94"))
_DEDUPE_PRIORITY_MAX = float(os.getenv("RAG_RETRIEVAL_DEDUPE_PRIORITY_MAX", "1.08"))

_DEFAULT_CLASS_WEIGHTS: dict[str, float] = {
    "canonical_talk": 1.08,
    "primary_interview": 1.05,
    "supplemental_qna": 0.97,
    "reference_material": 0.92,
}

_DEFAULT_STATUS_WEIGHTS: dict[str, float] = {
    "canonical": 1.03,
    "primary": 1.02,
    "core": 1.02,
    "supplemental": 0.99,
    "context": 0.97,
    "reference": 0.95,
}

_CORPUS_CLASSES = frozenset(_DEFAULT_CLASS_WEIGHTS.keys())
_RETRIEVAL_HINT_KEYS = ("retrieval_weight", "retrieval_weight_hint")
_TALK_TYPES = {
    "address",
    "commencement",
    "keynote",
    "lecture",
    "presentation",
    "remarks",
    "speech",
    "talk",
}
_INTERVIEW_TYPES = {
    "ask_me_anything",
    "conversation",
    "dialogue",
    "discussion",
    "fireside_chat",
    "interview",
    "podcast_interview",
}
_SUPPLEMENTAL_TYPES = {
    "meeting_notes",
    "panel_qna",
    "q_and_a",
    "qa",
    "qna",
    "roundtable",
    "seminar_qna",
}
_REFERENCE_TYPES = {
    "appendix",
    "bibliography",
    "editorial_companion",
    "foreword",
    "glossary",
    "guide",
    "index",
    "notes",
    "note",
    "reading_list",
    "reference",
    "reference_material",
    "study_guide",
    "summary",
}


@dataclass(frozen=True)
class WeightingDecision:
    enabled: bool
    weight: float
    corpus_class: Optional[str]
    base_score: float
    weighted_score: float


def weighting_feature_flag() -> str:
    return _WEIGHTING_FLAG


def metadata_weighting_enabled(*, override: Optional[bool] = None) -> bool:
    if override is not None:
        return override
    raw = os.getenv(_WEIGHTING_FLAG, "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def weighting_candidate_limit(top_k: int, *, enabled: bool) -> int:
    if not enabled:
        return top_k
    return max(top_k, top_k * max(_WEIGHTING_CANDIDATE_MULTIPLIER, 1))


def merge_retrieval_metadata(
    chunk_metadata: Optional[dict[str, Any]],
    *,
    collection: Optional[str] = None,
    canonical_status: Optional[str] = None,
    dedupe_priority: Optional[int] = None,
    work_type: Optional[str] = None,
    document_metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if isinstance(document_metadata, dict):
        merged.update(document_metadata)
    if isinstance(chunk_metadata, dict):
        merged.update(chunk_metadata)
    if collection is not None:
        merged.setdefault("collection", collection)
    if canonical_status is not None:
        merged.setdefault("canonical_status", canonical_status)
    if dedupe_priority is not None:
        merged.setdefault("dedupe_priority", dedupe_priority)
    if work_type is not None:
        merged.setdefault("work_type", work_type)
    return merged


def apply_weight_to_score(
    metadata: Optional[dict[str, Any]],
    *,
    base_score: float,
    enabled: bool,
) -> WeightingDecision:
    normalized_score = _safe_float(base_score, default=0.0)
    if not enabled:
        return WeightingDecision(
            enabled=False,
            weight=1.0,
            corpus_class=classify_corpus_class(metadata),
            base_score=normalized_score,
            weighted_score=normalized_score,
        )

    weight, corpus_class = _compute_weight(metadata)
    return WeightingDecision(
        enabled=True,
        weight=weight,
        corpus_class=corpus_class,
        base_score=normalized_score,
        weighted_score=normalized_score * weight,
    )


def classify_corpus_class(metadata: Optional[dict[str, Any]]) -> Optional[str]:
    if not isinstance(metadata, dict):
        return None

    explicit_class = _normalize_token(metadata.get("corpus_class"))
    if explicit_class in _CORPUS_CLASSES:
        return explicit_class

    work_type = _normalize_token(metadata.get("work_type"))
    if work_type in _TALK_TYPES:
        return "canonical_talk"
    if work_type in _INTERVIEW_TYPES:
        return "primary_interview"
    if work_type in _SUPPLEMENTAL_TYPES:
        return "supplemental_qna"
    if work_type in _REFERENCE_TYPES:
        return "reference_material"

    collection = _normalize_text(metadata.get("collection"))
    if collection:
        if any(term in collection for term in ("q&a", "q and a", "qna", "qa", "questions")):
            return "supplemental_qna"
        if any(term in collection for term in ("notes", "meeting", "minutes")):
            return "supplemental_qna"
        if any(term in collection for term in ("reference", "appendix", "guide", "reading list")):
            return "reference_material"
        if any(term in collection for term in ("talk", "lecture", "speech", "remarks")):
            return "canonical_talk"
        if any(term in collection for term in ("interview", "conversation", "dialogue")):
            return "primary_interview"

    canonical_status = _normalize_token(metadata.get("canonical_status"))
    if canonical_status in {"reference", "context"}:
        return "reference_material"
    if canonical_status == "supplemental":
        return "supplemental_qna"
    if canonical_status in {"canonical", "primary", "core"}:
        return "canonical_talk"
    return None


def ranking_sort_key(chunk: Any) -> tuple[float, float, float, int, str]:
    weighted_score = _safe_float(getattr(chunk, "weighted_score", None), default=0.0)
    base_score = _safe_float(getattr(chunk, "base_score", None), default=0.0)
    reranker_score = _safe_float(getattr(chunk, "reranker_score", None), default=0.0)
    chunk_index = int(getattr(chunk, "chunk_index", 0) or 0)
    chunk_id = str(getattr(chunk, "chunk_id", ""))
    return (-weighted_score, -base_score, -reranker_score, chunk_index, chunk_id)


def class_weights() -> dict[str, float]:
    raw = os.getenv("RAG_RETRIEVAL_CLASS_WEIGHTS_JSON", "").strip()
    if not raw:
        return dict(_DEFAULT_CLASS_WEIGHTS)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return dict(_DEFAULT_CLASS_WEIGHTS)
    if not isinstance(parsed, dict):
        return dict(_DEFAULT_CLASS_WEIGHTS)
    weights = dict(_DEFAULT_CLASS_WEIGHTS)
    for key, value in parsed.items():
        normalized = _normalize_token(key)
        if normalized in _CORPUS_CLASSES:
            weights[normalized] = _clamp(_safe_float(value, default=weights[normalized]))
    return weights


def _compute_weight(metadata: Optional[dict[str, Any]]) -> tuple[float, Optional[str]]:
    if not isinstance(metadata, dict):
        return 1.0, None

    corpus_class = classify_corpus_class(metadata)
    canonical_status = _normalize_token(metadata.get("canonical_status"))

    weight = 1.0
    if corpus_class:
        weight *= class_weights().get(corpus_class, 1.0)
    if canonical_status:
        weight *= _DEFAULT_STATUS_WEIGHTS.get(canonical_status, 1.0)

    dedupe_priority = _safe_float(metadata.get("dedupe_priority"), default=None)
    if dedupe_priority is not None:
        weight *= _clamp(
            1.0 + (dedupe_priority * _DEDUPE_PRIORITY_SCALE),
            minimum=_DEDUPE_PRIORITY_MIN,
            maximum=_DEDUPE_PRIORITY_MAX,
        )

    hint = _safe_hint(metadata)
    if hint is not None:
        weight *= _clamp(hint)

    return _clamp(weight), corpus_class


def _safe_hint(metadata: dict[str, Any]) -> Optional[float]:
    for key in _RETRIEVAL_HINT_KEYS:
        value = _safe_float(metadata.get(key), default=None)
        if value is not None:
            return value
    return None


def _safe_float(value: Any, *, default: Optional[float]) -> Optional[float]:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, *, minimum: Optional[float] = None, maximum: Optional[float] = None) -> float:
    lower = _WEIGHTING_MIN if minimum is None else minimum
    upper = _WEIGHTING_MAX if maximum is None else maximum
    return max(lower, min(upper, value))


def _normalize_token(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()
