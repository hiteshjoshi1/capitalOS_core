from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.rag import RagAuthor, RagIngestionJob, RagSource, RealtimeEvent
from app.services.realtime import realtime_service

log = logging.getLogger(__name__)

AUTHOR_INGESTION_TOPIC = "author-ingestion"


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def serialize_source(source: RagSource) -> dict[str, Any]:
    author = source.author
    return {
        "id": str(source.id),
        "author_id": source.author_id,
        "author_name": author.name if author else None,
        "url": source.url,
        "source_type": source.source_type,
        "status": source.status,
        "hash": source.hash,
        "last_ingested_at": _iso(source.last_ingested_at),
        "created_at": _iso(source.created_at),
    }


def serialize_job(job: RagIngestionJob) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "source_id": str(job.source_id),
        "batch_id": str(job.batch_id) if job.batch_id else None,
        "status": job.status,
        "failure_category": job.failure_category,
        "error": job.error,
        "stats_json": job.stats_json or {},
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
        "created_at": _iso(job.created_at),
    }


def serialize_event(event: RealtimeEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "topic": event.topic,
        "event_name": event.event_name,
        "batch_id": str(event.batch_id) if event.batch_id else None,
        "author_id": event.author_id,
        "source_id": str(event.source_id) if event.source_id else None,
        "job_id": str(event.job_id) if event.job_id else None,
        "status": event.status,
        "created_at": _iso(event.created_at),
        "payload": event.payload or {},
    }


def _author_payload(source: RagSource) -> dict[str, Any]:
    author: RagAuthor | None = source.author
    return {
        "id": source.author_id,
        "name": author.name if author else source.author_id,
    }


def publish_event(event: RealtimeEvent) -> None:
    envelope = serialize_event(event)
    realtime_service.publish_sync(user_id=event.user_id, topic=event.topic, event=envelope)


def record_batch_event(
    db: Session,
    *,
    user_id: int,
    author: RagAuthor,
    batch_id: str,
    event_name: str,
    status: str,
    source_count: int,
    completed_source_count: int | None = None,
    failed_source_count: int | None = None,
) -> RealtimeEvent:
    payload: dict[str, Any] = {
        "author": {
            "id": author.id,
            "name": author.name,
        },
        "batch": {
            "id": batch_id,
            "status": status,
            "source_count": source_count,
        },
    }
    if completed_source_count is not None:
        payload["batch"]["completed_source_count"] = completed_source_count
    if failed_source_count is not None:
        payload["batch"]["failed_source_count"] = failed_source_count

    event = RealtimeEvent(
        user_id=user_id,
        topic=AUTHOR_INGESTION_TOPIC,
        event_name=event_name,
        batch_id=batch_id,
        author_id=author.id,
        status=status,
        payload=payload,
    )
    db.add(event)
    db.flush()
    log.info(
        "Recorded author-ingestion batch event: user_id=%s batch_id=%s event_name=%s",
        user_id,
        batch_id,
        event_name,
    )
    return event


def record_source_event(
    db: Session,
    *,
    user_id: int,
    source: RagSource,
    job: RagIngestionJob,
    event_name: str,
    status: str,
    batch_id: str | None = None,
) -> RealtimeEvent:
    payload = {
        "author": _author_payload(source),
        "batch": {
            "id": batch_id,
            "status": status,
        },
        "source": serialize_source(source),
        "job": serialize_job(job),
        "failure_reason": job.error,
    }
    event = RealtimeEvent(
        user_id=user_id,
        topic=AUTHOR_INGESTION_TOPIC,
        event_name=event_name,
        batch_id=batch_id,
        author_id=source.author_id,
        source_id=source.id,
        job_id=job.id,
        status=status,
        payload=payload,
    )
    db.add(event)
    db.flush()
    log.info(
        "Recorded author-ingestion source event: user_id=%s source_id=%s job_id=%s event_name=%s",
        user_id,
        source.id,
        job.id,
        event_name,
    )
    return event
