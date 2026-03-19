from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


ReviewDecision = Literal["approved", "needs_fixes", "escalate"]
ReviewRisk = Literal["low", "medium", "high"]
GateType = Literal["plan_approval", "human_review"]


class StrictHumanPayload(BaseModel):
    reviewer: str
    notes: str = ""
    questions: List[str] = Field(default_factory=list)
    response_requirements: List[str] = Field(default_factory=list)
    unresolved_comments: List[str] = Field(default_factory=list)

    @field_validator("reviewer")
    @classmethod
    def reviewer_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reviewer must not be blank")
        return value

    @field_validator("questions", "response_requirements", "unresolved_comments")
    @classmethod
    def normalize_lists(cls, values: List[str]) -> List[str]:
        return [v.strip() for v in values if v and v.strip()]


class HumanDecision(StrictHumanPayload):
    gate_type: GateType
    decision: Literal["approved", "needs_fixes"]
    decided_at: datetime = Field(default_factory=utc_now)

    @field_validator("notes")
    @classmethod
    def notes_required_for_needs_fixes(cls, value: str, info):
        decision = info.data.get("decision")
        if decision == "needs_fixes" and not value.strip():
            raise ValueError("notes are required when decision is needs_fixes")
        return value


class AgentReview(BaseModel):
    review_id: str
    model_name: str
    decision: ReviewDecision
    risk: ReviewRisk
    summary: str
    findings: List[str] = Field(default_factory=list)
    test_gaps: List[str] = Field(default_factory=list)
    verification_considered: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class HumanReview(StrictHumanPayload):
    review_id: str
    decision: Literal["approved", "needs_fixes"]
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("notes")
    @classmethod
    def notes_required_for_needs_fixes(cls, value: str, info):
        decision = info.data.get("decision")
        if decision == "needs_fixes" and not value.strip():
            raise ValueError("notes are required when decision is needs_fixes")
        return value


class ReviewCycle(BaseModel):
    review_id: str
    source: Literal["build", "rework"]
    source_rework_cycle_id: Optional[str] = None
    agent_review: Optional[AgentReview] = None
    escalation_review: Optional[AgentReview] = None
    human_review: Optional[HumanReview] = None
    status: Literal["in_review", "approved", "needs_fixes"] = "in_review"
    created_at: datetime = Field(default_factory=utc_now)

    def effective_agent_decision(self) -> Optional[str]:
        if self.escalation_review is not None:
            return self.escalation_review.decision
        if self.agent_review is not None:
            return self.agent_review.decision
        return None