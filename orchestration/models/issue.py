from __future__ import annotations

from datetime import datetime, timezone
from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IssueMetadata(BaseModel):
    issue_id: str
    slug: str
    title: str
    task_file: str
    repo_root: str
    branch: str
    created_at: datetime = Field(default_factory=utc_now)