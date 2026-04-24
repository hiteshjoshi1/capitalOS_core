from __future__ import annotations

import os

import pytest
from starlette.websockets import WebSocketDisconnect

from app.models.rag import RagAuthor, RagIngestionJob, RagSource
from app.rag.ingestion.events import publish_event, record_source_event
from tests.conftest import TestingSessionLocal
from tests.test_auth import _insert_user_with_password

os.environ.setdefault("RAG_EMBEDDING_MOCK", "1")


def _login_token(client, *, username: str, password: str) -> str:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_realtime_websocket_requires_access_token(client, monkeypatch, db_engine):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")

    _insert_user_with_password(db_engine, user_id=910, username="realtime_auth", password="RealtimePass1!")

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/realtime/ws"):
            pass

    assert exc_info.value.code == 4401


def test_realtime_websocket_subscribes_and_delivers_user_scoped_events(client, monkeypatch, db_engine):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")

    _insert_user_with_password(db_engine, user_id=911, username="realtime_user", password="RealtimePass1!")
    access_token = _login_token(client, username="realtime_user", password="RealtimePass1!")

    with client.websocket_connect(
        f"/realtime/ws?access_token={access_token}&topics=author-ingestion"
    ) as websocket:
        subscribed = websocket.receive_json()
        assert subscribed == {"type": "subscribed", "topics": ["author-ingestion"]}

        db = TestingSessionLocal()
        try:
            author = RagAuthor(id="realtime_author", name="Realtime Author", enabled=True)
            source = RagSource(
                user_id=911,
                author_id=author.id,
                url="https://example.com/realtime-article",
                source_type="html",
                status="queued",
            )
            job = RagIngestionJob(
                user_id=911,
                source=source,
                batch_id="72c47b64-b31e-4e57-9cb3-94fdd11f77e9",
                status="queued",
            )
            db.add(author)
            db.add(source)
            db.add(job)
            db.flush()
            event = record_source_event(
                db,
                user_id=911,
                source=source,
                job=job,
                event_name="source_queued",
                status="queued",
                batch_id=job.batch_id,
            )
            db.commit()
            db.refresh(event)
        finally:
            db.close()

        publish_event(event)
        delivered = websocket.receive_json()
        assert delivered["type"] == "event"
        assert delivered["topic"] == "author-ingestion"
        assert delivered["event_name"] == "source_queued"
        assert delivered["author_id"] == "realtime_author"
        assert delivered["status"] == "queued"
        assert delivered["payload"]["source"]["url"] == "https://example.com/realtime-article"
        assert delivered["payload"]["job"]["batch_id"] == "72c47b64-b31e-4e57-9cb3-94fdd11f77e9"
