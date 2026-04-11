"""
AI Sage API router — Concept Mode.

Endpoints:
  POST /ai-sage/query   — Concept Mode: single natural language query
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth_context import require_current_user
from app.db.session import get_db
from app.rag.concept_mode import ConceptQueryResult, execute_concept_query

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ai-sage",
    tags=["ai-sage"],
    dependencies=[Depends(require_current_user)],
)


# ── Request / response schemas ────────────────────────────────────────────────


class ConceptQueryIn(BaseModel):
    query: str = Field(..., min_length=1, description="A concept question in plain language.")
    top_k: int = Field(12, ge=1, le=30, description="Maximum evidence chunks to retrieve.")


class AuthorViewOut(BaseModel):
    author_id: str
    author_name: str
    view: str
    key_passages: list[str]


class SuggestedReadingOut(BaseModel):
    author_id: str
    author_name: str
    passage: str
    source_url: Optional[str]
    reason: str


class EvidenceChunkOut(BaseModel):
    chunk_id: str
    author_id: str
    author_name: str
    text: str
    similarity: float
    metadata: dict[str, Any]


class ConceptQueryOut(BaseModel):
    query: str
    best_passages: list[EvidenceChunkOut]
    author_views: list[AuthorViewOut]
    synthesis: Optional[str]
    critique: Optional[str]
    suggested_readings: list[SuggestedReadingOut]
    evidence_sufficient: bool
    weak_evidence_note: Optional[str]


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.post("/query", response_model=ConceptQueryOut)
def concept_query(body: ConceptQueryIn, db: Session = Depends(get_db)) -> ConceptQueryOut:
    """
    AI Sage Concept Mode.

    Ask a concept question in plain language. The system selects the relevant
    author corpus automatically, retrieves the best supporting passages, generates
    distinct author perspectives, a synthesis, a critique, and suggested readings.

    The user never needs to specify authors, retrieval modes, or internal controls.
    """
    result: ConceptQueryResult = execute_concept_query(
        body.query,
        db,
        top_k_chunks=body.top_k,
    )
    return ConceptQueryOut(**result.as_dict())
