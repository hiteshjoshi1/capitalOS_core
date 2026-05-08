from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.schemas.ai_sage import ConceptQueryOut
from app.services.ai_sage import (
    AISageTurnExecution,
    _assistant_text_for_result,
    _evidence_payload_for_result,
    create_assistant_placeholder,
    create_chat,
    create_user_message,
    fail_assistant_message,
    finalize_assistant_message,
)


def _auth_headers(client, username: str, password: str) -> dict[str, str]:
    signup = client.post("/auth/signup", json={"username": username, "password": password, "display_name": username.title()})
    assert signup.status_code == 200
    login = client.post("/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _concept_payload(*, query: str) -> dict[str, object]:
    return {
        "query": query,
        "mode": "concept",
        "best_passages": [
            {
                "chunk_id": "chunk-1",
                "author_id": "warren_buffett",
                "author_name": "Warren Buffett",
                "text": "A durable business compounds capital over time.",
                "similarity": 0.91,
                "metadata": {
                    "document_id": "doc-1",
                    "title": "1996 Letter",
                    "source_url": "https://example.com/1996-letter",
                    "context_text": "A durable business compounds capital over time.",
                },
                "document_id": "doc-1",
                "ranking_score": 0.91,
                "score_type": "reranked",
            }
        ],
        "critique": "Push on durability and reinvestment.",
        "evidence_sufficient": True,
        "weak_evidence_note": None,
        "intent": {"query_type": "concept"},
        "constraints_relaxed": False,
        "constraint_relaxation_reason": None,
    }


def _make_result(payload: dict[str, object]):
    return SimpleNamespace(as_dict=lambda: payload)


def _parse_sse_events(body: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    for frame in body.split("\n\n"):
        if not frame.strip():
            continue
        event_name = "message"
        data_lines: list[str] = []
        for line in frame.splitlines():
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
        if not data_lines:
            continue
        events.append((event_name, json.loads("\n".join(data_lines))))
    return events


def test_ai_sage_local_answer_uses_context_text_and_normalizes_wrapped_sentences():
    result = ConceptQueryOut(
        query="What does Buffett emphasize about a wonderful business?",
        mode="concept",
        best_passages=[
            {
                "chunk_id": "chunk-1",
                "author_id": "warren_buffett",
                "author_name": "Warren Buffett",
                "text": "Time \r is the friend of the wonderful business, the enemy of the \r mediocre.",
                "similarity": 0.91,
                "metadata": {
                    "context_text": (
                        "Time is the friend of the wonderful business, the enemy of the mediocre. "
                        "You might think this principle is obvious, but I had to learn it the hard way."
                    ),
                    "anchor_text": "Time \r is the friend of the wonderful business, the enemy of the \r mediocre.",
                },
                "document_id": "doc-1",
                "ranking_score": 0.91,
                "score_type": "reranked",
            }
        ],
        critique=None,
        evidence_sufficient=True,
        weak_evidence_note=None,
    )

    answer = _assistant_text_for_result(result)
    assert "\r" not in answer
    assert "Grounded passages from Warren Buffett:" in answer
    assert "Time is the friend of the wonderful business, the enemy of the mediocre." in answer
    assert "hard way." in answer


def test_ai_sage_local_answer_prioritizes_topic_specific_passages_for_single_author_queries():
    result = ConceptQueryOut(
        query="What does Charlie Munger say about BYD?",
        mode="concept",
        best_passages=[
            {
                "chunk_id": "chunk-1",
                "author_id": "charlie_munger",
                "author_name": "Charlie Munger",
                "text": "Charlie Munger: The answer is: Of course. I hardly do anything else.",
                "similarity": 0.95,
                "metadata": {
                    "context_text": "Charlie Munger: The answer is: Of course. I hardly do anything else.",
                    "anchor_text": "Charlie Munger: The answer is: Of course. I hardly do anything else.",
                },
                "document_id": "doc-generic",
                "ranking_score": 0.95,
                "score_type": "retrieved",
            },
            {
                "chunk_id": "chunk-2",
                "author_id": "charlie_munger",
                "author_name": "Charlie Munger",
                "text": "BYD last year made more than $2 billion after taxes in the auto business in China.",
                "similarity": 0.82,
                "metadata": {
                    "context_text": "BYD last year made more than $2 billion after taxes in the auto business in China.",
                    "anchor_text": "BYD last year made more than $2 billion after taxes in the auto business in China.",
                },
                "document_id": "doc-byd",
                "ranking_score": 0.82,
                "score_type": "retrieved",
            },
        ],
        critique=None,
        evidence_sufficient=True,
        weak_evidence_note=None,
        intent={
            "query_type": "single_author",
            "author_ids": ["charlie_munger"],
            "author_names": ["Charlie Munger"],
            "topic_entities": ["BYD"],
        },
    )

    answer = _assistant_text_for_result(result)
    assert "Grounded passages on BYD from Charlie Munger:" in answer
    assert "BYD last year made more than $2 billion after taxes in the auto business in China." in answer
    assert "I hardly do anything else" not in answer


def test_ai_sage_evidence_payload_uses_topic_focused_snippet():
    result = ConceptQueryOut(
        query="What does Charlie Munger say about BYD?",
        mode="concept",
        best_passages=[
            {
                "chunk_id": "chunk-1",
                "author_id": "charlie_munger",
                "author_name": "Charlie Munger",
                "text": "We never worried for one second.",
                "similarity": 0.75,
                "metadata": {
                    "context_text": (
                        "We never worried for one second. "
                        "Q: What are your thoughts on BYD? "
                        "Munger: BYD is getting widely recognized as being in some kind of a sweet spot."
                    ),
                    "anchor_text": "We never worried for one second.",
                },
                "document_id": "doc-byd",
                "ranking_score": 0.75,
                "score_type": "retrieved",
            }
        ],
        critique=None,
        evidence_sufficient=True,
        weak_evidence_note=None,
        intent={
            "query_type": "single_author",
            "author_ids": ["charlie_munger"],
            "author_names": ["Charlie Munger"],
            "topic_entities": ["BYD"],
        },
    )

    evidence = _evidence_payload_for_result(result)
    assert len(evidence) == 1
    assert evidence[0]["snippet"].startswith("Q: What are your thoughts on BYD?")


def test_ai_sage_chat_crud_and_message_persistence(client, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    headers = _auth_headers(client, "sage_owner", "SageOwnerPass1!")

    with patch("app.services.ai_sage.execute_concept_query", return_value=_make_result(_concept_payload(query="What matters?"))):
        created = client.post("/ai-sage/chats", json={}, headers=headers)
        assert created.status_code == 200
        chat_id = created.json()["id"]

        turn = client.post(
            f"/ai-sage/chats/{chat_id}/messages",
            json={"content": "What matters?"},
            headers=headers,
        )
        assert turn.status_code == 200
        body = turn.json()
        assert body["user_message"]["content"] == "What matters?"
        assert body["assistant_message"]["status"] == "completed"
        assert "Grounded passages from Warren Buffett:" in body["assistant_message"]["content"]
        assert body["assistant_message"]["evidence"][0]["chunk_id"] == "chunk-1"
        assert body["assistant_message"]["evidence"][0]["document_id"] == "doc-1"

        listed = client.get("/ai-sage/chats", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["items"][0]["preview"].startswith("Grounded passages from Warren Buffett:")
        assert listed.json()["items"][0]["status"] == "answered"

        fetched = client.get(f"/ai-sage/chats/{chat_id}", headers=headers)
        assert fetched.status_code == 200
        assert [message["role"] for message in fetched.json()["messages"]] == ["user", "assistant"]

        renamed = client.patch(f"/ai-sage/chats/{chat_id}", json={"title": "Durability review"}, headers=headers)
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "Durability review"

        search = client.get("/ai-sage/chats/search?query=durable", headers=headers)
        assert search.status_code == 200
        assert search.json()["items"][0]["chat_id"] == chat_id

        deleted = client.delete(f"/ai-sage/chats/{chat_id}", headers=headers)
        assert deleted.status_code == 200
        missing = client.get(f"/ai-sage/chats/{chat_id}", headers=headers)
        assert missing.status_code == 404


def test_ai_sage_follow_up_uses_bounded_context_and_keeps_retrieval_per_turn(client, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    headers = _auth_headers(client, "sage_context", "SageContextPass1!")
    observed_queries: list[str] = []

    def _execute(query: str, _db):
        observed_queries.append(query)
        return _make_result(_concept_payload(query=query))

    with patch("app.services.ai_sage.execute_concept_query", side_effect=_execute):
        chat_id = client.post("/ai-sage/chats", json={}, headers=headers).json()["id"]
        assert client.post(f"/ai-sage/chats/{chat_id}/messages", json={"content": "Explain moat"}, headers=headers).status_code == 200
        second = client.post(f"/ai-sage/chats/{chat_id}/messages", json={"content": "Compare that with Buffett"}, headers=headers)
        assert second.status_code == 200

    assert observed_queries[0] == "Explain moat"
    assert "Recent conversation context" in observed_queries[1]
    assert "Chat title: Explain moat" in observed_queries[1]
    assert "User: Explain moat" in observed_queries[1]
    assert "Assistant:" in observed_queries[1]


def test_ai_sage_streaming_message_returns_ack_delta_and_done(client, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    headers = _auth_headers(client, "sage_stream", "SageStreamPass1!")

    with patch("app.services.ai_sage.execute_concept_query", return_value=_make_result(_concept_payload(query="What matters?"))):
        chat_id = client.post("/ai-sage/chats", json={}, headers=headers).json()["id"]
        with client.stream(
            "POST",
            f"/ai-sage/chats/{chat_id}/messages/stream",
            json={"content": "What matters?"},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

    events = _parse_sse_events(body)
    event_names = [event_name for event_name, _ in events]
    assert event_names[0] == "ack"
    assert event_names[-1] == "done"
    assert "delta" in event_names[1:-1]

    ack_payload = events[0][1]
    assert ack_payload["chat_id"] == chat_id
    assert ack_payload["user_message"]["content"] == "What matters?"

    done_payload = events[-1][1]
    assert done_payload["assistant_message"]["status"] == "completed"
    assert "Grounded passages from Warren Buffett:" in done_payload["assistant_message"]["content"]
    assert done_payload["assistant_message"]["evidence"][0]["document_id"] == "doc-1"


def test_ai_sage_retry_failed_message_and_ownership_isolation(client, db_engine, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    owner_headers = _auth_headers(client, "sage_a", "SagePassA1!")
    other_headers = _auth_headers(client, "sage_b", "SagePassB1!")

    attempts = {"count": 0}

    def _execute(query: str, _db):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("Synthetic failure")
        return _make_result(_concept_payload(query=query))

    with patch("app.services.ai_sage.execute_concept_query", side_effect=_execute):
        chat_id = client.post("/ai-sage/chats", json={}, headers=owner_headers).json()["id"]
        failed = client.post(f"/ai-sage/chats/{chat_id}/messages", json={"content": "Retry me"}, headers=owner_headers)
        assert failed.status_code == 200
        failed_body = failed.json()
        assert failed_body["assistant_message"]["status"] == "failed"
        message_id = failed_body["assistant_message"]["id"]

        retry = client.post(f"/ai-sage/chats/{chat_id}/messages/{message_id}/retry", headers=owner_headers)
        assert retry.status_code == 200
        assert retry.json()["assistant_message"]["status"] == "completed"

    unauthorized = client.get(f"/ai-sage/chats/{chat_id}", headers=other_headers)
    assert unauthorized.status_code == 404

    with db_engine.begin() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM ai_sage_turn_evidence")).scalar_one()
        assert int(count) >= 1


def test_ai_sage_finalize_and_fail_accept_detached_assistant_messages(client, db_engine, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    _auth_headers(client, "sage_detached", "SageDetachedPass1!")
    with db_engine.begin() as conn:
        owner_user_id = int(
            conn.execute(text("SELECT id FROM users WHERE username = 'sage_detached'")).scalar_one()
        )

    testing_session = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)

    with testing_session() as db:
        chat = create_chat(db, owner_user_id, "Detached test")
        user_message = create_user_message(db, chat, "What matters?")
        assistant_message = create_assistant_placeholder(db, chat, user_message.id)
        chat_id = chat.id
        user_message_id = user_message.id
        db.expunge(chat)
        db.expunge(assistant_message)

        completed = finalize_assistant_message(
            db,
            chat=chat,
            assistant_message=assistant_message,
            turn=AISageTurnExecution(
                mode="concept",
                assistant_text="Grounded answer",
                result=SimpleNamespace(),
                metadata={"mode": "concept"},
                evidence=[
                    {
                        "chunk_id": "chunk-detached",
                        "document_id": "doc-detached",
                        "author_id": "warren_buffett",
                        "author_name": "Warren Buffett",
                        "source_url": "https://example.com/detached",
                        "title": "Detached",
                        "snippet": "Detached evidence row",
                        "similarity": 0.9,
                        "ranking_score": 0.9,
                        "score_type": "reranked",
                        "metadata_json": {"kind": "test"},
                    }
                ],
            ),
        )
        assert completed.status == "completed"
        assert completed.evidence[0].document_id == "doc-detached"

        reloaded_chat = db.get(type(chat), chat_id)
        assert reloaded_chat is not None
        failed_placeholder = create_assistant_placeholder(db, reloaded_chat, user_message_id)
        db.expunge(failed_placeholder)
        failed = fail_assistant_message(
            db,
            chat=chat,
            assistant_message=failed_placeholder,
            error_message="Synthetic stream failure",
        )
        assert failed.status == "failed"
        assert failed.error_message == "Synthetic stream failure"


def test_ai_sage_retention_prunes_expired_chats(client, db_engine, monkeypatch):
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    headers = _auth_headers(client, "sage_retention", "SageRetention1!")

    with db_engine.begin() as conn:
        user_id = conn.execute(text("SELECT id FROM users WHERE username = 'sage_retention'")).scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO ai_sage_chats (id, owner_user_id, title, last_activity_at, created_at, updated_at)
                VALUES ('00000000-0000-0000-0000-000000000111', :user_id, 'Expired chat', '2023-01-01T00:00:00+00:00', '2023-01-01T00:00:00+00:00', '2023-01-01T00:00:00+00:00')
                """
            ),
            {"user_id": user_id},
        )

    listed = client.get("/ai-sage/chats", headers=headers)
    assert listed.status_code == 200
    assert all(item["id"] != "00000000-0000-0000-0000-000000000111" for item in listed.json()["items"])
