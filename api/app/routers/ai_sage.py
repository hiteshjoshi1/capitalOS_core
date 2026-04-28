"""
AI Sage API router — Concept Mode and Company Thesis Mode.

Endpoints:
  POST /ai-sage/query   — Auto-routes to concept mode or thesis mode
                          based on query classification.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth_context import require_current_user
from app.db.session import get_db
from app.rag.company_thesis_mode import (
    ThesisQueryResult,
    classify_query_as_thesis,
    execute_thesis_query,
)
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


class EvidenceChunkOut(BaseModel):
    chunk_id: str
    author_id: str
    author_name: str
    text: str
    similarity: float
    metadata: dict[str, Any]
    document_id: Optional[str] = None
    ranking_score: Optional[float] = None
    score_type: Optional[str] = None


class LiveSourceOut(BaseModel):
    url: str
    title: str
    snippet: str
    source_type: str


class UpdatedThesisViewOut(BaseModel):
    stronger: list[str]
    weaker: list[str]
    unresolved: list[str]


class ConceptQueryOut(BaseModel):
    query: str
    best_passages: list[EvidenceChunkOut]
    critique: Optional[str]
    evidence_sufficient: bool
    weak_evidence_note: Optional[str]
    # Thesis mode fields — populated only when mode == "thesis"
    mode: str = "concept"
    thesis_question: Optional[str] = None
    pushback_questions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    key_facts: list[str] = Field(default_factory=list)
    updated_thesis_view: Optional[UpdatedThesisViewOut] = None
    live_sources: list[LiveSourceOut] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    # Intent routing metadata — included for all concept-mode responses
    intent: Optional[dict[str, Any]] = None
    # Constraint transparency fields (issue-145)
    constraints_relaxed: bool = False
    constraint_relaxation_reason: Optional[str] = None


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.post("/query", response_model=ConceptQueryOut)
def concept_query(body: ConceptQueryIn, db: Session = Depends(get_db)) -> ConceptQueryOut:
    """
    AI Sage Query.

    Automatically classifies the query and routes to the appropriate mode:
    - Company Thesis Mode: thesis pressure testing, pushback questions, live research,
      updated thesis view, and critique.
    - Concept Mode: concept question with ranked passages and optional critique.

    The user never needs to specify a mode, authors, or retrieval settings.
    """
    if classify_query_as_thesis(body.query):
        result: ThesisQueryResult = execute_thesis_query(
            body.query,
            db,
            top_k_chunks=body.top_k,
        )
        d = result.as_dict()
        # Map updated_thesis_view dict to Pydantic model if present
        if d.get("updated_thesis_view"):
            d["updated_thesis_view"] = UpdatedThesisViewOut(**d["updated_thesis_view"])
        return ConceptQueryOut(**d)

    concept_result: ConceptQueryResult = execute_concept_query(
        body.query,
        db,
        top_k_chunks=body.top_k,
    )
    return ConceptQueryOut(**concept_result.as_dict())
