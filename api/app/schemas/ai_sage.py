from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


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
    document_id: str | None = None
    ranking_score: float | None = None
    score_type: str | None = None


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
    critique: str | None
    evidence_sufficient: bool
    weak_evidence_note: str | None
    mode: str = "concept"
    thesis_question: str | None = None
    pushback_questions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    key_facts: list[str] = Field(default_factory=list)
    updated_thesis_view: UpdatedThesisViewOut | None = None
    live_sources: list[LiveSourceOut] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    intent: dict[str, Any] | None = None
    constraints_relaxed: bool = False
    constraint_relaxation_reason: str | None = None


class AISageChatCreateIn(BaseModel):
    title: str | None = None


class AISageChatUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    pinned: bool | None = None


class AISageChatMessageCreateIn(BaseModel):
    content: str = Field(..., min_length=1)


class AISageChatMessageEvidenceOut(BaseModel):
    id: str
    chunk_id: str | None
    document_id: str | None
    author_id: str | None
    author_name: str | None
    source_url: str | None
    title: str | None
    snippet: str | None
    similarity: float | None
    ranking_score: float | None
    score_type: str | None
    metadata_json: dict[str, Any] | None = None


class AISageChatMessageOut(BaseModel):
    id: str
    role: str
    content: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None
    metadata_json: dict[str, Any] | None = None
    evidence: list[AISageChatMessageEvidenceOut] = Field(default_factory=list)


class AISageChatSummaryOut(BaseModel):
    id: str
    title: str
    preview: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime
    pinned_at: datetime | None = None


class AISageChatListOut(BaseModel):
    items: list[AISageChatSummaryOut]
    total: int
    limit: int
    offset: int


class AISageChatDetailOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime
    pinned_at: datetime | None = None
    metadata_json: dict[str, Any] | None = None
    messages: list[AISageChatMessageOut] = Field(default_factory=list)


class AISageChatSearchResultOut(BaseModel):
    chat_id: str
    title: str
    snippet: str | None = None
    updated_at: datetime


class AISageChatSearchOut(BaseModel):
    items: list[AISageChatSearchResultOut]
    total: int


class AISageChatTurnOut(BaseModel):
    chat: AISageChatDetailOut
    user_message: AISageChatMessageOut
    assistant_message: AISageChatMessageOut
