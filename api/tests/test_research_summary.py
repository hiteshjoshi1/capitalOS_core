from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("RAG_EMBEDDING_MOCK", "1")
os.environ.setdefault("AUTH_BYPASS_USER_ID", "1")

from app.models.ai_sage_chat import AISageChat, AISageMessage
from app.models.rag import RagAuthor, RagDocument, RagIngestionJob, RagSource
from tests.conftest import TestingSessionLocal


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def test_research_summary_aggregates_ai_sage_corpus_and_ingestion_stats(client):
    # rag_* tables aren't truncated between tests (unlike ai_sage_* tables), so
    # assert on deltas rather than absolute counts to stay robust to any state
    # left behind by other tests sharing this sqlite file.
    baseline = client.get("/rag/research-summary").json()

    now = datetime.now(tz=timezone.utc)
    db = TestingSessionLocal()
    try:
        author = RagAuthor(id=_uid("marks"), name="Howard Marks", enabled=True, domains=[], expertise_tags=[])
        db.add(author)
        db.flush()

        source = RagSource(user_id=1, author_id=author.id, url="https://example.com/memo", source_type="html", status="ingested")
        db.add(source)
        db.flush()

        document = RagDocument(
            source_id=source.id,
            author_id=author.id,
            title="Sea Change",
            metadata_json={"char_count": 100},
        )
        db.add(document)

        db.add(RagIngestionJob(user_id=1, source_id=source.id, status="running", created_at=now - timedelta(minutes=10)))
        db.add(RagIngestionJob(user_id=1, source_id=source.id, status="queued", created_at=now - timedelta(minutes=8)))
        db.add(RagIngestionJob(user_id=1, source_id=source.id, status="failed", created_at=now - timedelta(minutes=5)))
        db.add(RagIngestionJob(user_id=1, source_id=source.id, status="done", created_at=now - timedelta(minutes=1)))

        chat = AISageChat(id=_uid("chat"), owner_user_id=1, title="Moat durability in payments", last_activity_at=now, created_at=now)
        db.add(chat)
        db.flush()
        db.add(AISageMessage(id=_uid("msg"), chat_id=chat.id, role="user", content="How durable are moats?", created_at=now))
        db.add(
            AISageMessage(
                id=_uid("msg"),
                chat_id=chat.id,
                role="assistant",
                content="They are narrowing.",
                status="completed",
                created_at=now,
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/rag/research-summary")
    assert response.status_code == 200
    body = response.json()

    # ai_sage_chats is truncated before every test, so these are exact.
    assert body["ai_sage"]["chats_total"] == 1
    assert body["ai_sage"]["chats_today"] == 1

    assert body["author_corpus"]["author_count"] == baseline["author_corpus"]["author_count"] + 1
    assert body["author_corpus"]["document_count"] == baseline["author_corpus"]["document_count"] + 1

    assert body["ingestion_queue"]["running_count"] == baseline["ingestion_queue"]["running_count"] + 1
    assert body["ingestion_queue"]["queued_count"] == baseline["ingestion_queue"]["queued_count"] + 1
    assert body["ingestion_queue"]["failed_count"] == baseline["ingestion_queue"]["failed_count"] + 1
    assert body["ingestion_queue"]["last_job_at"] is not None


def test_research_summary_returns_valid_shape_with_no_chats(client):
    response = client.get("/rag/research-summary")
    assert response.status_code == 200
    body = response.json()
    # ai_sage_chats is truncated before every test, so this is exact regardless
    # of what other tests have left in the shared rag_* tables.
    assert body["ai_sage"]["chats_total"] == 0
    assert body["ai_sage"]["chats_today"] == 0
    assert isinstance(body["author_corpus"]["document_count"], int)
    assert isinstance(body["ingestion_queue"]["running_count"], int)
    assert isinstance(body["ingestion_queue"]["queued_count"], int)
