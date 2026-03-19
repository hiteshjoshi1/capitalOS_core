from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ShipResult(BaseModel):
    committed: bool = False
    pushed: bool = False
    pr_created: bool = False
    pr_url: Optional[str] = None
    summary: str = ""
    created_at: datetime = Field(default_factory=utc_now)