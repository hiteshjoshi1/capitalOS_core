from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

LOW_QUALITY_FAILURE = "low_quality_extraction"


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


@dataclass
class QualityValidationResult:
    accepted: bool
    failure_category: Optional[str]
    reasons: list[str]
    metrics: dict[str, float | int]


def validate_logical_document(
    *,
    clean_text: str,
    title: Optional[str],
    chunk_count: int,
    section_headings: list[str],
) -> QualityValidationResult:
    text = (clean_text or "").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    word_count = len(text.split())
    char_count = len(text)
    normalized_text = _normalize(text)

    heading_candidates = {_normalize(title or "")}
    heading_candidates.update(_normalize(heading) for heading in section_headings if heading)
    heading_candidates.discard("")

    body_lines = [line for line in lines if _normalize(line) not in heading_candidates]
    body_text = "\n".join(body_lines).strip()
    body_char_count = len(body_text)
    body_word_count = len(body_text.split())
    header_ratio = 0.0 if char_count == 0 else round(body_char_count / char_count, 4)

    reasons: list[str] = []
    if not text:
        reasons.append("empty_text")
    if chunk_count < 1:
        reasons.append("no_chunks")
    if normalized_text and normalized_text in heading_candidates:
        reasons.append("title_or_heading_only")
    if char_count < 50:
        reasons.append("very_short_text")
    if word_count < 10:
        reasons.append("very_few_words")
    if body_char_count < 40:
        reasons.append("insufficient_body_text")
    if body_word_count < 8:
        reasons.append("insufficient_body_words")
    if char_count < 220 and header_ratio < 0.45:
        reasons.append("low_body_ratio")

    low_quality = False
    if "empty_text" in reasons:
        low_quality = False
    elif "title_or_heading_only" in reasons:
        low_quality = True
    elif body_char_count < 5:
        low_quality = True
    elif chunk_count < 1 and body_word_count < 5:
        low_quality = True
    elif char_count < 40 and body_word_count < 4:
        low_quality = True
    elif char_count < 30 and header_ratio < 0.55:
        low_quality = True

    return QualityValidationResult(
        accepted=bool(text) and not low_quality,
        failure_category=None if text and not low_quality else LOW_QUALITY_FAILURE,
        reasons=reasons,
        metrics={
            "char_count": char_count,
            "word_count": word_count,
            "body_char_count": body_char_count,
            "body_word_count": body_word_count,
            "chunk_count": chunk_count,
            "body_ratio": header_ratio,
            "section_count": len(section_headings),
        },
    )
