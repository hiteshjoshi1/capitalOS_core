from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PlanChecklistItem(BaseModel):
    id: str
    text: str
    required: bool = True
    human_only: bool = False
    post_ship: bool = False
    planned_paths: List[str] = Field(default_factory=list)


class PlanOutput(BaseModel):
    summary: str
    architecture_decisions: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    checklist: List[PlanChecklistItem] = Field(default_factory=list)
    planned_paths: List[str] = Field(default_factory=list)
    immutable_plan_hash: Optional[str] = None
    planner_model: Optional[str] = None
    generated_at: datetime = Field(default_factory=utc_now)

    def allowed_paths(self) -> list[str]:
        paths = set(self.planned_paths)
        for item in self.checklist:
            for path in item.planned_paths:
                paths.add(path)
        return sorted(paths)