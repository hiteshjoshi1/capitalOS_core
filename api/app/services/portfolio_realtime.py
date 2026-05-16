from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.services.realtime import realtime_service

PORTFOLIO_REFRESH_TOPIC = "portfolio-refresh"


def publish_portfolio_refresh(
    user_id: int,
    *,
    event_name: str,
    source: str,
    status: str = "completed",
    payload: dict[str, Any] | None = None,
) -> None:
    event_payload: dict[str, Any] = {"source": source}
    if payload:
        event_payload.update(payload)

    realtime_service.publish_sync(
        user_id=user_id,
        topic=PORTFOLIO_REFRESH_TOPIC,
        event={
            "id": str(uuid4()),
            "topic": PORTFOLIO_REFRESH_TOPIC,
            "event_name": event_name,
            "status": status,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "payload": event_payload,
        },
    )